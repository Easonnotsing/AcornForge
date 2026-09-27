#!/usr/bin/env python3
"""Hermes cron "aggregate-today-sessions"

Shell-only cron running nightly (default 22:00) with no LLM invocation.
Output: ~/.hermes/cache/cron/aggregate/YYYY-MM-DD.json

Covers 5 harnesses:
  - Hermes      ~/.hermes/state.db                   (SQLite, epoch seconds)
  - OpenCode    ~/.local/share/opencode/opencode.db  (SQLite, epoch milliseconds)
  - Claude Code ~/.claude/projects/**/*.jsonl        (file mtime)
  - Codex CLI   ~/.codex/sessions/**/*.jsonl         (file mtime)
  - Claudian    ~/Documents/Obsidian/.claudian/sessions/ (file mtime)

Timezone constraint:
  - All SQLite timestamps (epoch seconds or milliseconds) MUST be interpreted
    as Asia/Shanghai (UTC+8). Do NOT print raw epoch or UTC strings.
  - The reference baseline is Beijing local midnight (epoch seconds, local TZ).
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Strict: this script interprets/outputs everything in Asia/Shanghai
TZ_SH = timezone(timedelta(hours=8), name="Asia/Shanghai")
HOME = Path.home()


def _parse_args():
    p = argparse.ArgumentParser(description="Hermes cron aggregate-today-sessions")
    p.add_argument(
        "--date",
        default=None,
        help="Target date YYYY-MM-DD (Asia/Shanghai). Default = today. Pass an explicit date for backfill.",
    )
    return p.parse_args()


ARGS = _parse_args()
NOW_SH = datetime.now(tz=TZ_SH)
TARGET_DAY = ARGS.date or NOW_SH.strftime("%Y-%m-%d")
TARGET_DAY_DT = datetime.strptime(TARGET_DAY, "%Y-%m-%d").replace(tzinfo=TZ_SH)
TODAY_00 = TARGET_DAY_DT
# Today: window is [today 00:00, now]; historical backfill: [that day 00:00, that day 23:59:59]
if TARGET_DAY == NOW_SH.strftime("%Y-%m-%d"):
    END_TS = NOW_SH.timestamp()
else:
    END_TS = (TARGET_DAY_DT + timedelta(days=1)).timestamp() - 1
TODAY_TS = TODAY_00.timestamp()
OUT = HOME / ".hermes/cache/cron/aggregate" / f"{TARGET_DAY}.json"
OUT.parent.mkdir(parents=True, exist_ok=True)


def ts_to_sh(ts_epoch_seconds: float) -> str:
    """epoch seconds → Asia/Shanghai ISO timestamp string"""
    return datetime.fromtimestamp(ts_epoch_seconds, tz=TZ_SH).isoformat()


def ts_ms_to_sh(ts_epoch_ms: int) -> str:
    """epoch milliseconds → Asia/Shanghai ISO timestamp string"""
    return datetime.fromtimestamp(ts_epoch_ms / 1000.0, tz=TZ_SH).isoformat()


def _extract_text(data_json: str) -> str:
    """OpenCode part.data is JSON; top-level `type` decides how to extract text.

    type='text' / 'reasoning' → return .text
    type='tool' / 'file' / 'patch' / 'step-*' / 'compaction' → return ""

    Also handles message.data where content is a list of {type, text} chunks.
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
    """Extract action summary from tool/file/patch parts (used in Layer 1 "what was done").

    Returns dict {type, ...summary fields} or None. (Python 3.9 compatible style.)
    """
    try:
        obj = json.loads(data_json)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    otype = obj.get("type")
    if otype == "tool":
        return {
            "type": "tool",
            "name": obj.get("tool"),
            "args_keys": list(obj.get("args", {}).keys()) if isinstance(obj.get("args"), dict) else [],
        }
    if otype == "file":
        return {
            "type": "file",
            "path": obj.get("path"),
            "mime": obj.get("mime"),
        }
    if otype == "patch":
        files = obj.get("files") or []
        return {
            "type": "patch",
            "files": [f.get("path") for f in files if isinstance(f, dict)],
        }
    return None


def _is_main_agent(agent_name):
    """Decide whether the agent is 'main' vs 'subagent'.

    Heuristic: agent field contains 'subagent' → subagent.
    Everything else (including 'claudian-yolo', 'build', None) is treated as main agent.
    """
    if not agent_name:
        return True
    a = agent_name.lower()
    return "subagent" not in a


def _extract_msg_meta(data_json: str) -> dict:
    """Extract role / agent / variant / path / tokens from message.data."""
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
            # Hermes schema: sessions table uses last_activity_at REAL (epoch seconds);
            # long-running Desktop sessions have started_at (days ago) + last_activity_at (today).
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
            # Per-source breakdown of today's activity (desktop / cron / cli / weixin)
            if "last_activity_at" in cols and "source" in cols:
                cur.execute(
                    """SELECT source, COUNT(*) FROM sessions
                       WHERE last_activity_at >= ? AND last_activity_at <= ?
                       GROUP BY source ORDER BY 2 DESC""",
                    (TODAY_TS, END_TS),
                )
                info["by_source"] = {r[0]: r[1] for r in cur.fetchall()}
                # Recent 10 sessions for the summarizer agent
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
        # Also fetch today's active sessions' message dialog (for Layer 2 narrative)
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
                    by_session = {}
                    for sid, role, content, ts in cur.fetchall():
                        if not content:
                            continue
                        # Truncate: cap each message to 2000 chars to avoid JSON explosion
                        by_session.setdefault(sid, []).append(
                            {
                                "role": role,
                                "time": ts_to_sh(ts),
                                "content": content[:2000],
                            }
                        )
                    # Attach dialog to each session
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
        # Fetch active session metadata
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
        # Per-session message full text (IN-clause batch fetch)
        # message.data is JSON: {"role": "user"|"assistant", ...} — schema may vary
        messages_by_session = {sid: [] for sid in session_ids}
        placeholders = ",".join("?" * len(session_ids))
        # 1) Fetch message metadata
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
        # 2) Fetch part full text (group by message_id)
        message_ids = list(msg_by_id.keys())
        parts_by_msg = {mid: [] for mid in message_ids}
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
                        # Orphan part (parent message not in scope); skip
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
        # 3) Assemble: split each message into two layers
        #    Layer 2 (dialog): text content, exclude subagent
        #    Layer 1 (actions): tool/file/patch action summary
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
                    # Layer 2: main-agent text + reasoning → role dialog
                    #         subagent text → discard (don't pollute main dialog)
                    if is_main:
                        dialog_chunks.append(txt)
                # Layer 1: action summary (main + sub both extracted — tool calls are work)
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
                    # Layer 2: direct dialog (main agent only)
                    "dialog": dialog,
                    # Layer 1: what was done (tools/files/patches)
                    "actions": actions,
                    "parts_count": len(parts),
                }
            )
        # Attach messages to each session
        for s in sessions_meta:
            s["messages"] = messages_by_session.get(s["id"], [])
            s["messages_count"] = len(s["messages"])
        results["sources"]["opencode"] = {
            "active_today": n_today,
            "sessions_sample": sessions_meta,
            "note": "Full message.data text expanded; tool_call / non-text parts dropped (left for v2).",
        }
        con.close()
    except Exception as e:
        import traceback
        results["sources"]["opencode"] = {
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc().splitlines()[-8:],
        }

# ---------- 3. Claude Code JSONL ----------
claude_files = []
claude_today_bytes = 0
for jl in HOME.glob(".claude/projects/**/*.jsonl"):
    try:
        mtime = jl.stat().st_mtime
        # Skip files written within the last 60s (likely being written)
        if time.time() - mtime < 60:
            continue
        if TODAY_TS <= mtime <= END_TS:
            claude_files.append(
                {"file": str(jl), "mtime": mtime, "size": jl.stat().st_size}
            )
            claude_today_bytes += jl.stat().st_size
    except (FileNotFoundError, OSError):
        continue
results["sources"]["claude_code"] = {
    "today_files": claude_files,
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
            if TODAY_TS <= mtime <= END_TS:
                codex_files.append(
                    {"file": str(jl), "mtime": mtime, "size": jl.stat().st_size}
                )
                codex_today_bytes += jl.stat().st_size
        except (FileNotFoundError, OSError):
            continue
results["sources"]["codex"] = {
    "today_files": codex_files,
    "total_today": len(codex_files),
    "today_bytes": codex_today_bytes,
}

# ---------- 5. Claudian (in-Vault metadata) ----------
claudian_files = []
csdir = HOME / "Documents/Obsidian/.claudian/sessions"
if csdir.exists():
    for f in csdir.glob("conv-*.meta.json"):
        try:
            mtime = f.stat().st_mtime
            if time.time() - mtime < 60:
                continue
            if TODAY_TS <= mtime <= END_TS:
                claudian_files.append({"file": str(f), "mtime": mtime})
        except (FileNotFoundError, OSError):
            continue
results["sources"]["claudian"] = {
    "today_files": claudian_files,
    "count": len(claudian_files),
    "note": "Metadata only; Claudian does not store transcript body. Use the OpenCode/Hermes sessions it bridges for full dialog.",
}

# ---------- Write JSON ----------
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

total_active = sum(
    info.get("active_today", info.get("active_by_last_activity", info.get("total_today", info.get("count", 0))))
    for info in results["sources"].values()
    if isinstance(info, dict)
)
print(f"OK today active: total={total_active} sources={list(results['sources'].keys())}")
print(f"   output: {OUT}")