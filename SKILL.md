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

# YYYY-MM-DD Work Summary

## Task Index
- **Task 1 · <name>**: <one-line summary>
- **Task 2 · <name>**: <one-line summary>

## Task Narrative

### Task 1 · <name>

(200-400 word narrative: why / how / decisions / artifacts)

**Session DB References**
- Main session: `file:///path/to/db#session=<id>` — "<human title>"
- Sub-sessions: <other db paths + session ids>
- Cross-harness: <only if the task spans multiple harnesses>

### Task 2 · <name>

(narrative)

**Session DB References**
- Main session: `file:///path/to/db#session=<id>`

## Todo Follow-up
- [ ] <only items explicitly mentioned in today's conversation>

## Notes
<any anomalies or warnings>
```

> **Note**: The example above is in English. If your daily notes are in Chinese, swap `Task 1 · <name>` for `任务 1 · <name>` and use the `prompts/summarize-today.zh.md` variant. See the "Locale configuration" section below.

**Session DB references are the audit trail, not decoration.** Every task's narrative ends with a `Session DB References` block listing the exact SQLite/JSONL file path and session ID where the work happened. macOS Finder `file://` links open the database directly; SQL queries by `session_id` recover the full original conversation. The daily.md is intentionally lighter than a clone — full content stays in the original harness DB; daily.md tells you *what* and *why*, the Session DB references tell you *where the truth lives*.

### Two layers, no overlap

- **Task Index (Layer 1)**: 1 line per task. Scan-only. "What happened."
- **Task Narrative (Layer 2)**: 200-400 words per task. Read-for-context. "Why + how + decisions."
- **No repetition.** Layer 1 is a hook, Layer 2 is the body.
- **Draft order matters.** Write Layer 1 first as a literal one-line summary per task, then close the file mentally before drafting Layer 2. If the agent writes both layers in the same pass it will paraphrase Layer 1 into Layer 2 — the user has hit this three times in development. Treat them as two separate writing tasks.

### Todo source discipline

The Todo Follow-up section lists ONLY items explicitly mentioned in the day's dialog (a user/agent "todo", "follow up", "remember", "next step", "tomorrow"). Do not pull candidate todos from MEMORY.md, USER.md, or any persistent state — the user has explicitly rejected unrelated topics (e.g. iCloud sync) appearing in daily todos when not discussed that day. If no dialog mentioned a todo, write `- [ ] (no explicit todo today)` instead of inventing one.

### Hermes Desktop dialog is part of the worklog

The Hermes segment MUST extract `messages` table dialog (user/assistant `content`), not only session metadata. v1 of this skill extracted only `sessions` metadata, which made the daily silent about the user's main chat activity on the day they were actually working. Treat Hermes Desktop dialog as required — same priority as OpenCode dialog.

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

### Locale configuration — pick your language for daily notes

The repo ships with **two prompt variants** for Job 2:

| File | Language | Use when |
|------|----------|----------|
| `prompts/summarize-today.md` | English | Daily notes in English |
| `prompts/summarize-today.zh.md` | Chinese (中文) | Daily notes in Chinese |

Both prompts are functionally identical — only the language differs. The slug format, task structure, backfill logic, and Session DB references are the same.

**To install the Chinese variant** (replace your `summarize-today.md`):

```bash
cp prompts/summarize-today.zh.md \
   ~/Documents/Obsidian/Agents\ Shared\ Worklog/.hermes-prompts/summarize-today.md
```

Then **edit** the cron job to read the Chinese prompt:

```bash
hermes-cron update summarize-today \
  --prompt-file /path/to/job2-prompt.zh.txt
```

(Where `job2-prompt.zh.txt` is your Chinese wrapper that `cat`s the prompt + tasks.json + today's JSON, mirroring the English wrapper.)

**The `daily.md` and `tasks.json` content language follows your prompt** — pick one and stick with it. Mixing English task names with Chinese task names will break cross-day continuity.

**Default for new installs**: English (matches the SKILL.md examples).

### Change the daily directory

Edit Job 1's `OUT` constant and Job 2's prompt paths if you want a different Vault structure.

### Add a new harness

In `aggregate_today_sessions.py`, add a new section under the existing 5. Two patterns:

**JSONL harness** (Claude Code / Codex style): glob `~/.path/**/*.jsonl`, filter by `mtime >= TODAY_TS AND mtime <= END_TS`.

**SQLite harness** (Hermes / OpenCode style): open with `mode=ro` + `uri=True` + `timeout=1.0`. **Always do `PRAGMA table_info(<table>)` first** — do not assume columns. Two traps the user hit when extending this skill:
- Hermes `state.db`: `messages.role` is a real column, `message` table does NOT exist — don't confuse them.
- OpenCode `opencode.db`: `message` table has NO `role` column — role lives inside `message.data` JSON. Same for `time_created` (epoch ms, not seconds). Assistant text lives in `part` table (not `message`), keyed by `part.message_id`.

**Time filter must always include an upper bound.** Every SQLite WHERE on a timestamp needs both `>= TODAY_TS` AND `<= END_TS`. Without the upper bound, a backfill for `2026-09-20` running on `2026-09-27` will pull today's sessions into the historical aggregate — the lower bound alone is not enough.

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