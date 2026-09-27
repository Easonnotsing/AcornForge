#!/usr/bin/env python3
"""Hermes cron "aggregate-today-sessions"

每天 22:00 跑一次，纯 shell + python，无 LLM 调用。
输出: ~/.hermes/cache/cron/aggregate/YYYY-MM-DD.json

覆盖 harness: Hermes state.db / OpenCode opencode.db /
Claude Code JSONL / Codex CLI JSONL / Claudian meta.json

时区强约束:
- 所有 SQLite 时间戳 (epoch 秒 或 epoch 毫秒) 一律按 Asia/Shanghai 解释
- 比对基准是 Beijing 时间今天 00:00 (epoch 秒, 本地时区)
- 永远不要输出 UTC 时间戳给用户或落到 Vault 文件
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 强约束:本脚本所有时间按 Asia/Shanghai 解释/输出
TZ_SH = timezone(timedelta(hours=8), name="Asia/Shanghai")
HOME = Path.home()


def _parse_args():
    p = argparse.ArgumentParser(description="Hermes cron aggregate-today-sessions")
    p.add_argument(
        "--date",
        default=None,
        help="目标日期 YYYY-MM-DD(Asia/Shanghai);不传 = 今天。补做历史 daily 时传。",
    )
    return p.parse_args()


ARGS = _parse_args()
NOW_SH = datetime.now(tz=TZ_SH)
TARGET_DAY = ARGS.date or NOW_SH.strftime("%Y-%m-%d")
TARGET_DAY_DT = datetime.strptime(TARGET_DAY, "%Y-%m-%d").replace(tzinfo=TZ_SH)
TODAY_00 = TARGET_DAY_DT
# 对今天跑:窗口是 [今天 00:00, now];对历史补做:窗口是 [那天 00:00, 那天 23:59:59]
if TARGET_DAY == NOW_SH.strftime("%Y-%m-%d"):
    END_TS = NOW_SH.timestamp()
else:
    END_TS = (TARGET_DAY_DT + timedelta(days=1)).timestamp() - 1
TODAY_TS = TODAY_00.timestamp()
OUT = HOME / ".hermes/cache/cron/aggregate" / f"{TARGET_DAY}.json"
OUT.parent.mkdir(parents=True, exist_ok=True)


def ts_to_sh(ts_epoch_seconds: float) -> str:
    """epoch 秒 → Asia/Shanghai ISO 时间字符串"""
    return datetime.fromtimestamp(ts_epoch_seconds, tz=TZ_SH).isoformat()


def ts_ms_to_sh(ts_epoch_ms: int) -> str:
    """epoch 毫秒 → Asia/Shanghai ISO 时间字符串"""
    return datetime.fromtimestamp(ts_epoch_ms / 1000.0, tz=TZ_SH).isoformat()


def _extract_text(data_json: str) -> str:
    """OpenCode part.data 是 JSON,顶层 type 决定如何抽出文本。

    text / reasoning → 直接读 .text
    tool / file / patch / step-* / compaction → 返回 ""
    """
    try:
        obj = json.loads(data_json)
    except Exception:
        return ""
    if isinstance(obj, dict) and "type" in obj:
        otype = obj.get("type")
        if otype in ("text", "reasoning"):
            return obj.get("text", "")
        return ""
    content = obj.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for chunk in content:
            if isinstance(chunk, dict) and chunk.get("type") == "text":
                out.append(chunk.get("text", ""))
        return "\n".join(out)
    return ""


def _extract_part_action(data_json: str):
    """从 tool/file/patch 类 part 抽出动作摘要(给层次 1 '做了什么'用)。

    返回 dict{type, summary} 或 None。(Python 3.9 兼容写法)
    """
    try:
        obj = json.loads(data_json)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    otype = obj.get("type")
    if otype == "tool":
        # obj: {type, tool: name, args, ...}
        return {
            "type": "tool",
            "name": obj.get("tool"),
            "args_keys": list(obj.get("args", {}).keys()) if isinstance(obj.get("args"), dict) else [],
        }
    if otype == "file":
        # obj: {type, path, content? / mime?}
        return {
            "type": "file",
            "path": obj.get("path"),
            "mime": obj.get("mime"),
        }
    if otype == "patch":
        # obj: {type, files?: [{path, hash}]}
        files = obj.get("files") or []
        return {
            "type": "patch",
            "files": [f.get("path") for f in files if isinstance(f, dict)],
        }
    return None


def _is_main_agent(agent_name):
    """判断是否为'主 agent' vs 'subagent'。

    启发式:agent 字段含 'subagent' 或 session 标题里有 '@general subagent'
    视为 subagent,其他都视为主 agent(包括 'claudian-yolo' / 'build' / None)。
    """
    if not agent_name:
        return True
    a = agent_name.lower()
    return "subagent" not in a


def _extract_msg_meta(data_json: str) -> dict:
    """从 message.data 抽出 role / agent / variant / path / tokens。"""
    try:
        obj = json.loads(data_json)
    except Exception:
        return {}
    return {
        "role": obj.get("role", "?"),
        "agent": obj.get("agent"),
        "variant": obj.get("variant"),
        "cwd": obj.get("path", {}).get("cwd") if isinstance(obj.get("path"), dict) else None,
        "model": obj.get("modelID"),
        "provider": obj.get("providerID"),
        "tokens_total": (obj.get("tokens") or {}).get("total") if isinstance(obj.get("tokens"), dict) else None,
        "finish": obj.get("finish"),
    }

results = {
    "date": TODAY_00.strftime("%Y-%m-%d"),
    "tolerance_min": 5,
    "sources": {},
}

# ---------- 1. Hermes state.db (SQLite, read-only) ----------
hermes_db = HOME / ".hermes/state.db"
if hermes_db.exists():
    try:
        con = sqlite3.connect(f"file:{hermes_db}?mode=ro", uri=True, timeout=1.0)
        cur = con.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('sessions','messages')"
        )
        tables = [r[0] for r in cur.fetchall()]
        info = {"tables": tables}
        if "sessions" in tables:
            # Hermes schema: sessions 表用 last_activity_at REAL (epoch seconds)；
            # 长期延续的 Desktop session 用 started_at (几天前) + last_activity_at (今天)
            cur.execute("PRAGMA table_info(sessions)")
            cols = [r[1] for r in cur.fetchall()]
            if "last_activity_at" in cols:
                cur.execute(
                    "SELECT COUNT(*) FROM sessions WHERE last_activity_at >= ? AND last_activity_at <= ?",
                    (TODAY_TS, END_TS),
                )
                info["active_by_last_activity"] = cur.fetchone()[0]
            if "started_at" in cols:
                cur.execute(
                    "SELECT COUNT(*) FROM sessions WHERE started_at >= ? AND started_at <= ?",
                    (TODAY_TS, END_TS),
                )
                info["started_today"] = cur.fetchone()[0]
            # 按 source 看今日活跃,确认 Desktop / cron / cli / weixin 各占多少
            if "last_activity_at" in cols and "source" in cols:
                cur.execute(
                    """SELECT source, COUNT(*) FROM sessions
                       WHERE last_activity_at >= ? AND last_activity_at <= ?
                       GROUP BY source ORDER BY 2 DESC""",
                    (TODAY_TS, END_TS),
                )
                info["by_source"] = {r[0]: r[1] for r in cur.fetchall()}
                # 最近 5 条 session 详情,给 agent 摘要用
                cur.execute(
                    """SELECT id, source, title, model, profile_name,
                              started_at, last_activity_at,
                              input_tokens+output_tokens
                       FROM sessions WHERE last_activity_at >= ? AND last_activity_at <= ?
                       ORDER BY last_activity_at DESC LIMIT 10""",
                    (TODAY_TS, END_TS),
                )
                info["recent_sessions"] = [
                    {
                        "id": r[0], "source": r[1], "title": r[2],
                        "model": r[3], "profile": r[4],
                        "started": ts_to_sh(r[5]),
                        "last": ts_to_sh(r[6]),
                        "tokens": r[7],
                    }
                    for r in cur.fetchall()
                ]
        results["sources"]["hermes"] = info
        # 同时把今日活跃 session 的 message dialog 也抓下来(给层次2用)
        if "messages" in tables and info.get("recent_sessions"):
            try:
                today_active_ids = [s["id"] for s in info["recent_sessions"]]
                if today_active_ids:
                    placeholders_msgs = ",".join("?" * len(today_active_ids))
                    cur.execute(
                        f"""SELECT session_id, role, content, timestamp
                            FROM messages
                            WHERE session_id IN ({placeholders_msgs})
                              AND timestamp >= ? AND timestamp <= ?
                              AND role IN ('user','assistant')
                            ORDER BY session_id, timestamp""",
                        (*today_active_ids, TODAY_TS, END_TS),
                    )
                    by_session: dict[str, list] = {sid: [] for sid in today_active_ids}
                    for sid, role, content, ts in cur.fetchall():
                        if not content:
                            continue
                        # 截断:每个 message 最多 2000 字,避免 JSON 爆炸
                        by_session[sid].append(
                            {
                                "role": role,
                                "time": ts_to_sh(ts),
                                "content": content[:2000],
                            }
                        )
                    # 挂到每个 session 上
                    for s in info["recent_sessions"]:
                        msgs = by_session.get(s["id"], [])
                        s["dialog"] = msgs
                        s["messages_count"] = len(msgs)
                        s["dialog_chars"] = sum(len(m["content"]) for m in msgs)
            except Exception as e:
                info.setdefault("dialog_warning", str(e))
        con.close()
    except Exception as e:
        results["sources"]["hermes"] = {"error": str(e)}

# ---------- 2. OpenCode opencode.db (SQLite, read-only, ms timestamps) ----------
oc_db = HOME / ".local/share/opencode/opencode.db"
if oc_db.exists():
    try:
        con = sqlite3.connect(f"file:{oc_db}?mode=ro", uri=True, timeout=1.0)
        cur = con.cursor()
        today_ms = int(TODAY_00.timestamp() * 1000)
        end_ms = int(END_TS * 1000)
        cur.execute(
            "SELECT COUNT(*) FROM session WHERE time_updated >= ? AND time_updated <= ?",
            (today_ms, end_ms),
        )
        n_today = cur.fetchone()[0]
        # 取今日活跃 session 元数据
        cur.execute(
            """
            SELECT id, title,
                   time_created, time_updated,
                   model, tokens_input+tokens_output, directory
            FROM session WHERE time_updated >= ? AND time_updated <= ?
            ORDER BY time_updated DESC LIMIT 50
            """,
            (today_ms, end_ms),
        )
        sessions_meta = [
            {
                "id": r[0],
                "title": r[1],
                "created": ts_ms_to_sh(r[2]),
                "updated": ts_ms_to_sh(r[3]),
                "model": r[4],
                "tokens": r[5],
                "directory": r[6],
            }
            for r in cur.fetchall()
        ]
        session_ids = [s["id"] for s in sessions_meta]
        # 取每个 session 的 message 全文(只取今日新增的,不在 session_ids 全量里)
        # message.data 是 JSON: {"role": "user"|"assistant", "content": "..."} 或更复杂
        # 用 IN 子句批量取
        messages_by_session: dict[str, list] = {sid: [] for sid in session_ids}
        placeholders = ",".join("?" * len(session_ids))
        # 1) 拿 message 元信息(不带 try,因为前序 session 元数据查询已成功)
        cur.execute(
            f"""
            SELECT id, session_id, time_created, data
            FROM message WHERE session_id IN ({placeholders})
              AND time_created >= ? AND time_created <= ?
            ORDER BY session_id, time_created
            """,
            (*session_ids, today_ms, end_ms),
        )
        message_rows = cur.fetchall()
        msg_by_id = {r[0]: r for r in message_rows}
        # 2) 拿 part 全文(按 message_id group)
        message_ids = list(msg_by_id.keys())
        parts_by_msg: dict[str, list] = {mid: [] for mid in message_ids}
        try:
            if message_ids:
                p_placeholders = ",".join("?" * len(message_ids))
                cur.execute(
                    f"""
                    SELECT message_id, time_created, data
                    FROM part WHERE message_id IN ({p_placeholders})
                      AND time_created >= ? AND time_created <= ?
                    ORDER BY message_id, time_created
                    """,
                    (*message_ids, today_ms, end_ms),
                )
                part_rows = cur.fetchall()
                for pmid, pts_ms, pdata in part_rows:
                    if pmid not in parts_by_msg:
                        continue
                    parts_by_msg[pmid].append(
                        {"time": ts_ms_to_sh(pts_ms), "data": pdata}
                    )
        except Exception as e:
            import traceback
            results["sources"]["opencode_part_warning"] = {
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc().splitlines()[-5:],
            }
        # 3) 组装:每个 message 把它的 part 分两层
        #   层次 2(dialog): text 内容,排除 subagent
        #   层次 1(actions): tool/file/patch 动作摘要
        for mid, row in msg_by_id.items():
            sid = row[1]
            ts_ms = row[2]
            data_json = row[3]
            meta = _extract_msg_meta(data_json)
            agent_name = meta.get("agent")
            is_main = _is_main_agent(agent_name)
            parts = parts_by_msg.get(mid, [])
            dialog_chunks = []
            actions = []
            for p in parts:
                txt = _extract_text(p["data"])
                if txt:
                    # 层次 2:主 agent 的所有 text + reasoning → 角色对话
                    #         subagent 的 text → 丢弃(避免污染主对话)
                    if is_main:
                        dialog_chunks.append(txt)
                # 层次 1:动作摘要(主+sub 都抽,工具调用是工作内容)
                act = _extract_part_action(p["data"])
                if act:
                    actions.append(act)
            dialog = "\n".join(dialog_chunks)
            messages_by_session[sid].append(
                {
                    "role": meta.get("role", "?"),
                    "agent": agent_name,
                    "is_main_agent": is_main,
                    "model": meta.get("model"),
                    "tokens": meta.get("tokens_total"),
                    "finish": meta.get("finish"),
                    "time": ts_ms_to_sh(ts_ms),
                    # 层次 2: 直接对话(只主 agent)
                    "dialog": dialog,
                    # 层次 1: 做了什么(tools/files/patches)
                    "actions": actions,
                    "parts_count": len(parts),
                }
            )
        # 把 messages 挂到对应 session 上
        for s in sessions_meta:
            s["messages"] = messages_by_session.get(s["id"], [])
            s["messages_count"] = len(s["messages"])
        results["sources"]["opencode"] = {
            "active_today": n_today,
            "sessions_sample": sessions_meta,
            "note": "完整 message.data 文本已展开;tool_call/非文本 part 暂时丢弃(留给后续 v2)",
        }
    except Exception as e:
        import traceback
        results["sources"]["opencode"] = {
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc().splitlines()[-8:],
        }
        if 'con' in dir() and con:
            con.close()

# ---------- 3. Claude Code JSONL ----------
claude_files = []
claude_today_bytes = 0
for jl in HOME.glob(".claude/projects/**/*.jsonl"):
    try:
        mtime = jl.stat().st_mtime
        if time.time() - mtime < 60:
            continue
        if mtime >= TODAY_TS:
            claude_files.append(
                {"file": str(jl), "mtime": mtime, "size": jl.stat().st_size}
            )
            claude_today_bytes += jl.stat().st_size
    except (FileNotFoundError, OSError):
        continue
results["sources"]["claude_code"] = {
    "today_files": claude_files[:30],
    "total_today": len(claude_files),
    "today_bytes": claude_today_bytes,
}

# ---------- 4. Codex CLI JSONL ----------
codex_files = []
codex_today_bytes = 0
for base in [HOME / ".codex/sessions", HOME / ".codex/archived_sessions"]:
    if not base.exists():
        continue
    for jl in base.glob("**/rollout-*.jsonl"):
        try:
            mtime = jl.stat().st_mtime
            if time.time() - mtime < 60:
                continue
            if mtime >= TODAY_TS:
                codex_files.append(
                    {"file": str(jl), "mtime": mtime, "size": jl.stat().st_size}
                )
                codex_today_bytes += jl.stat().st_size
        except (FileNotFoundError, OSError):
            continue
results["sources"]["codex"] = {
    "today_files": codex_files[:30],
    "total_today": len(codex_files),
    "today_bytes": codex_today_bytes,
}

# ---------- 5. Claudian (Vault 内) ----------
claudian_files = []
csdir = HOME / "Documents/Obsidian/.claudian/sessions"
if csdir.exists():
    for f in csdir.glob("conv-*.meta.json"):
        try:
            mtime = f.stat().st_mtime
            if time.time() - mtime < 60:
                continue
            if mtime >= TODAY_TS:
                claudian_files.append(
                    {"file": str(f), "mtime": mtime, "size": f.stat().st_size}
                )
        except (FileNotFoundError, OSError):
            continue
results["sources"]["claudian"] = {
    "today_files": claudian_files,
    "total_today": len(claudian_files),
}

with open(OUT, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

total = sum(
    s.get("total_today", s.get("active_today", 0))
    for s in results["sources"].values()
    if isinstance(s, dict)
)
print(f"OK 今日活跃: total={total} sources={list(results['sources'].keys())}")
print(f"   输出: {OUT}")