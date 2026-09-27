# AcornForge

> Each day's work — every commit, every conversation, every decision — is an acorn planted into the vault.

Daily aggregation of AI agent sessions across multiple harnesses (Hermes / OpenCode / Claude Code / Codex CLI / Claudian) into a single Obsidian-readable worklog. Two cron jobs run nightly: one collects, one summarizes.

## What it does

```
22:00  Job 1 (shell)   ──>  ~/.hermes/cache/cron/aggregate/YYYY-MM-DD.json
                              (5 harnesses' sessions + dialog + actions)

22:30  Job 2 (agent)   ──>  ~/Documents/Obsidian/Agents Shared Worklog/daily/YYYY-MM-DD.md
                              (task-indexed narrative with Session DB refs)
                              ~/Documents/Obsidian/Agents Shared Worklog/.task-index/tasks.json
                              (cross-day task continuity index)
```

If your laptop was off and a day was missed, the next run will **backfill** missing days (within the current ISO week — older session DBs may have rotated).

## Quick start

1. Copy `scripts/aggregate_today_sessions.py` to `~/.hermes/scripts/`
2. Copy `prompts/summarize-today.md` to `~/Documents/Obsidian/Agents Shared Worklog/.hermes-prompts/`
3. Copy `templates/tasks.json.template` to `~/Documents/Obsidian/Agents Shared Worklog/.task-index/tasks.json`
4. Register two cron jobs (see SKILL.md for `hermes-cron create` commands)

## Output structure

Each daily file looks like:

```markdown
---
date: 2026-09-27
type: daily-summary
generated_at: 2026-09-27T22:30:00+08:00
generated_by: hermes cron "summarize-today"
tasks:
  - slug: cross-harness-worklog-hermes-config
    name: 跨 Harness 工作日志机制
    status: ongoing
    stages_count: 2
---

# 2026-09-27 工作汇总

## 任务索引
- **任务 1 · 跨 Harness 工作日志机制**: 设计与实现 ...
- **任务 2 · AI 辅助写作素材整理**: ...

## 任务过程

### 任务 1 · 跨 Harness 工作日志机制

(200-400 字叙述:为什么做 / 过程 / 决策 / 产物)

**Session DB 引用**
- 主 session: `file:///Users/eason/.hermes/state.db#session=20260920_220123_5c12c5` — "Create new session in WeChat"
- 支线: OpenCode `file:///Users/eason/.local/share/opencode/opencode.db#session=ses_f1f672292ffeyjFIQzaBhuznCX`
- 跨 harness: 任务叙述涉及多 harness 时全列

### 任务 2 · AI 辅助写作素材整理

(narrative ...)

**Session DB 引用**
- 主 session: `file:///Users/eason/.local/share/opencode/opencode.db#session=ses_f1f672292ffeyjFIQzaBhuznCX`

## 待办跟进
- [ ] (only items explicitly mentioned today)

## Notes
```

**Two layers, no overlap:** Layer 1 (task index) is one line per task — scan-only. Layer 2 (task narrative) is 200-400 words per task — read-for-context. Layer 1 hooks; Layer 2 delivers the body.

**Session DB references are not decoration — they are the audit trail.** Every task's narrative points back to the exact session database file and session ID where the work happened. Click a `file://` link on macOS Finder and it opens the SQLite DB; pair with the session_id and you can run a SQL query to recover the full original conversation. The daily.md itself is intentionally lighter than a clone — full session content stays in the original harness DB; the daily.md tells you *what* and *why*, the Session DB reference tells you *where the truth lives*.

## Why "AcornForge"

Two daily sessions across five harnesses is a lot of small acorns. Each commit, each decision, each session is a seed. AcornForge forges them into a single readable day-file that becomes part of the long-term vault. The pattern extends: weekly synthesis, monthly synthesis, yearly review — all built from the same daily acorns.

## License

MIT. Fork, modify, redistribute.

## Related

- [VaultForge](https://github.com/Easonnotsing/VaultForge) — long-term knowledge assets from learning materials
- [Cruxlide](https://github.com/Easonnotsing/Cruxlide) — structured storyline presentations