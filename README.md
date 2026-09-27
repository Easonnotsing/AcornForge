# AcornForge

> Each day's work — every commit, every conversation, every decision — is an acorn planted into the vault.

Daily aggregation of AI agent sessions across multiple harnesses (Hermes / OpenCode / Claude Code / Codex CLI / Claudian) into a single Obsidian-readable worklog. Three cron jobs run on a nightly/weekly cadence: one collects, one summarizes the day, one synthesizes the week.

## What it does

```
22:00  Job 1 (shell, daily)   ──>  ~/.hermes/cache/cron/aggregate/YYYY-MM-DD.json
                                    (5 harnesses' sessions + dialog + actions)

22:30  Job 2 (agent, daily)   ──>  ~/Documents/Obsidian/Agents Shared Worklog/daily/YYYY-MM-DD.md
                                    (task-indexed narrative with Session DB refs)
                                    ~/Documents/Obsidian/Agents Shared Worklog/.task-index/tasks.json
                                    (cross-day task continuity index)

Sun 23:00  Job 3 (agent, weekly) ──> ~/Documents/Obsidian/Agents Shared Worklog/weekly/YYYY-WNN.md
                                    (theme-organized synthesis of the week's 7 dailies)
```

If your laptop was off and a day was missed, the next run will **backfill** missing days (within the current ISO week — older session DBs may have rotated).

## Quick start

1. Copy `scripts/aggregate_today_sessions.py` to `~/.hermes/scripts/`
2. Copy `prompts/summarize-today.md` to `~/Documents/Obsidian/Agents Shared Worklog/.hermes-prompts/`
3. Copy `prompts/weekly-synthesis.md` to the same `.hermes-prompts/` directory
4. Copy `templates/tasks.json.template` to `~/Documents/Obsidian/Agents Shared Worklog/.task-index/tasks.json`
5. Register three cron jobs (see SKILL.md for `hermes-cron create` commands)

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
    name: Cross-Harness Worklog Mechanism
    status: ongoing
    stages_count: 2
---

# 2026-09-27 Work Summary

## Task Index
- **Task 1 · Cross-Harness Worklog Mechanism**: design + implementation ...
- **Task 2 · AI-Assisted Writing Material**: ...

## Task Narrative

### Task 1 · Cross-Harness Worklog Mechanism

(200-400 word narrative: why / how / decisions / artifacts)

**Session DB References**
- Main session: `file:///Users/eason/.hermes/state.db#session=20260920_220123_5c12c5` — "Create new session in WeChat"
- Sub-sessions: OpenCode `file:///Users/eason/.local/share/opencode/opencode.db#session=ses_f1f672292ffeyjFIQzaBhuznCX`
- Cross-harness: list all sources if the task spans harnesses

### Task 2 · AI-Assisted Writing Material

(narrative ...)

**Session DB References**
- Main session: `file:///Users/eason/.local/share/opencode/opencode.db#session=ses_f1f672292ffeyjFIQzaBhuznCX`

## Todo Follow-up
- [ ] (only items explicitly mentioned today)

## Notes
```

> **Localization**: If you write daily notes in Chinese, use `prompts/summarize-today.zh.md` instead — swap `Task 1 · <name>` for `任务 1 · <name>`. Both prompts are functionally identical.

**Two layers, no overlap:** Layer 1 (task index) is one line per task — scan-only. Layer 2 (task narrative) is 200-400 words per task — read-for-context. Layer 1 hooks; Layer 2 delivers the body.

**Session DB References are the audit trail, not decoration.** Every task's narrative points back to the exact session database file and session ID where the work happened. Click a `file://` link on macOS Finder and it opens the SQLite DB; pair with the session_id and you can run a SQL query to recover the full original conversation. The daily.md itself is intentionally lighter than a clone — full session content stays in the original harness DB; the daily.md tells you *what* and *why*, the Session DB References tell you *where the truth lives*.

## Why "AcornForge"

Two daily sessions across five harnesses is a lot of small acorns. Each commit, each decision, each session is a seed. AcornForge forges them into a single readable day-file that becomes part of the long-term vault. The pattern extends: weekly synthesis, monthly synthesis, yearly review — all built from the same daily acorns.

## License

MIT. Fork, modify, redistribute.

## Related

- [VaultForge](https://github.com/Easonnotsing/VaultForge) — long-term knowledge assets from learning materials
- [Cruxlide](https://github.com/Easonnotsing/Cruxlide) — structured storyline presentations