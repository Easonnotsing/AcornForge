---
name: acornforge
description: "Daily cross-harness worklog aggregation into Obsidian."
version: 1.0.0
author: Eason + Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [cross-harness, daily-summary, obsidian, session-aggregation, productivity]
    homepage: https://github.com/NousResearch/hermes-agent
---

# AcornForge

Daily aggregation of AI agent sessions across multiple harnesses (Hermes / OpenCode / Claude Code / Codex CLI / Claudian) into a single Obsidian-readable worklog. Each day's work — every commit, every conversation, every decision — is an acorn planted into the vault.

---

## What This Skill Does

Two scheduled jobs that run together:

1. **Job 1 (aggregate-today-sessions)** — shell-only cron at 22:00. Queries 5 harnesses' local SQLite/JSONL storage, extracts today's sessions + dialog + actions, writes a single JSON.
2. **Job 2 (summarize-today)** — agent LLM cron at 22:30. Reads the JSON, writes a daily summary Markdown file in Obsidian Vault. Handles backfill if previous days were missed.

Output:
- `~/Documents/Obsidian/Agents Shared Worklog/daily/YYYY-MM-DD.md` — daily worklog
- `~/Documents/Obsidian/Agents Shared Worklog/.task-index/tasks.json` — cross-day task continuity index
- `~/Documents/Obsidian/Agents Shared Worklog/weekly/YYYY-WNN.md` — weekly synthesis (manual or scheduled)

---

## Setup

### 1. Place files

| Path | Source |
|------|--------|
| `~/.hermes/scripts/aggregate_today_sessions.py` | this skill's `scripts/aggregate_today_sessions.py` |
| `~/Documents/Obsidian/Agents Shared Worklog/.hermes-prompts/summarize-today.md` | this skill's `prompts/summarize-today.md` |
| `~/Documents/Obsidian/Agents Shared Worklog/.task-index/tasks.json` | start empty `{"tasks": {}}` |
| `~/Documents/Obsidian/Agents Shared Worklog/daily/` | exists or create |
| `~/Documents/Obsidian/Agents Shared Worklog/weekly/` | exists or create |

### 2. Register cron jobs

Job 1 — pure shell, no LLM:
```
hermes-cron create \
  --name aggregate-today-sessions \
  --schedule "every day at 10pm" \
  --script aggregate_today_sessions.py \
  --no-agent
```

Job 2 — agent with full prompt:
```
hermes-cron create \
  --name summarize-today \
  --schedule "every day at 10:30pm" \
  --prompt-file /path/to/job2-prompt.txt
```

(Where `job2-prompt.txt` is the wrapper that `cat`s the full prompt + tasks.json + today's JSON, then writes daily.md.)

### 3. Manual test

Run Job 1 first:
```
TZ=Asia/Shanghai python3 ~/.hermes/scripts/aggregate_today_sessions.py
ls ~/.hermes/cache/cron/aggregate/
```

Then trigger Job 2 once via Hermes chat to verify output:
```
hermes chat -q "$(cat job2-prompt.txt)"
```

---

## What Job 1 Extracts Per Harness

| Harness | Storage | Time format | Fields extracted |
|---------|---------|-------------|-----------------|
| **Hermes** | `~/.hermes/state.db` (SQLite) | epoch seconds | session id/source/title/model/tokens; message dialog (user/assistant content) |
| **OpenCode** | `~/.local/share/opencode/opencode.db` (SQLite) | epoch milliseconds | session metadata; message.role/agent/model from `data` JSON; part.text for type='text' only |
| **Claude Code** | `~/.claude/projects/**/*.jsonl` | file mtime | file path/mtime/size |
| **Codex CLI** | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | file mtime | file path/mtime/size |
| **Claudian** | `~/Documents/Obsidian/.claudian/sessions/conv-*.meta.json` | file mtime | metadata only (no body stored) |

Each OpenCode message is split into two layers for downstream summarization:
- `dialog` — main-agent text (excludes subagent / reasoning / tool calls)
- `actions` — tool/file/patch operation summary

---

## What Job 2 Writes

### Daily file structure

```markdown
---
date: YYYY-MM-DD
type: daily-summary
generated_at: <Beijing ISO timestamp>
generated_by: hermes cron "summarize-today"
continuity_with: <previous daily filename or null>
tasks:
  - slug: <kebab-case>-<project>
    name: <task name>
    category: <category>
    status: ongoing | done | shelved
    first_seen: <YYYY-MM-DD>
    stages_count: <cumulative stage count>
backfill: <true|false, omit if not backfill>
backfilled_at: <Beijing ISO, only if backfill>
---

# YYYY-MM-DD 工作汇总

## 任务索引
- **任务 1 · <name>**: <one-line summary>
- **任务 2 · <name>**: <one-line summary>

## 任务过程
### 任务 1 · <name>
<200-400 word narrative: why / how / decisions / artifacts>

**Session DB 引用**
- 主 session: `file:///path/to/db#session=<id>`
- 支线: ...

### 任务 2 · <name>
<narrative>

## 待办跟进
- [ ] <only items explicitly mentioned in today's conversation>

## Notes
<any anomalies or warnings>
```

### Two layers, no overlap

- **任务索引 (Layer 1)**: 1 line per task. Scan-only. "What happened."
- **任务过程 (Layer 2)**: 200-400 words per task. Read-for-context. "Why + how + decisions."
- **No repetition.** Layer 1 is a hook, Layer 2 is the body.

---

## Cross-Day Task Continuity

Every task has a stable `slug` of form `<kebab-case>-<project>`:

```
mem-hygiene-hermes-config
cross-harness-worklog-hermes-config
ai-assisted-writing-self-leadership-writing
launch-prep-aml-es-nsclc
```

Job 2 reads `tasks.json` before writing daily.md:
- If today's work is a continuation of an existing ongoing task → reuse its slug + name
- If new topic → create new slug

After writing daily.md, Job 2 appends a stage entry to the task's `stages[]`. **No stage is ever deleted** (audit).

For backfill of a missed day: Job 2 checks if a stage for that date already exists in `tasks.json` — if yes, skip (don't duplicate).

---

## Backfill Logic

If the daily cron is missed (laptop off / sleep / cron daemon down), the next run will:

1. List `daily/` to see which dates exist
2. Compute missing dates from `[this Monday .. yesterday]`
3. For each missing date, in order:
   - Run Job 1 with `--date YYYY-MM-DD` (per-date window)
   - Write daily.md with `backfill: true` + `backfilled_at: <now>`
4. Then write today's daily normally
5. Don't backfill dates older than this week (session DBs may have rotated; data unreliable)

Weekly synthesis should run the same check on its 7-day window before generating.

---

## Customization

### Change the daily directory

Edit Job 1's `OUT` constant and Job 2's prompt paths if you want a different Vault structure.

### Add a new harness

In `aggregate_today_sessions.py`, add a new section under the existing 5. Two patterns:

**JSONL harness** (Claude Code / Codex style): glob `~/.path/**/*.jsonl`, filter by `mtime >= TODAY_TS`.

**SQLite harness** (Hermes / OpenCode style): open with `mode=ro` + `uri=True` + `timeout=1.0`. Always do `PRAGMA table_info(<table>)` first — don't assume columns.

### Change Beijing timezone enforcement

All timestamps are converted to Asia/Shanghai via `TZ_SH = timezone(timedelta(hours=8))`. Do NOT print raw epoch or UTC strings — the user has explicitly forbidden UTC interpretation. SQLite's `datetime(col,'unixepoch')` defaults to UTC and must NOT be used; instead fetch raw epoch and convert in Python with `datetime.fromtimestamp(..., tz=TZ_SH)`.

---

## Files in This Skill

```
AcornForge/
├── SKILL.md                          (this file)
├── scripts/
│   └── aggregate_today_sessions.py  (Job 1: shell-only collector)
└── prompts/
    └── summarize-today.md            (Job 2: agent prompt template)
```

---

## License

MIT. Fork, modify, redistribute.