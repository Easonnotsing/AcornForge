# Hermes cron "summarize-today" prompt

**Schedule**: 22:30 daily (Asia/Shanghai), triggered by Hermes cron
**Input data**: `~/.hermes/cache/cron/aggregate/YYYY-MM-DD.json` (written by Job 1 "aggregate-today-sessions" at 22:00)
**Output**: `~/Documents/Obsidian/Agents Shared Worklog/daily/YYYY-MM-DD.md`
**Task index**: `~/Documents/Obsidian/Agents Shared Worklog/.task-index/tasks.json` (for cross-day task continuity)

---

## Task Index Mechanism (critical — read before running)

**Purpose**: Give cross-day continuations a stable task identity so weekly synthesis can identify which task lines are active and how far they've progressed.

**Slug naming convention**: `<kebab-case>-<project-anchor>`
- Examples: `mem-hygiene-hermes-config` / `cross-harness-worklog-hermes-config` / `ai-assisted-writing-self-leadership-writing`
- `project-anchor` joined with `-` (e.g. `hermes-config` / `writing` / `obsidian-config` / `launch` / `career`)
- **Same task line MUST reuse its slug** — don't rename daily

**Task index JSON path**: `~/Documents/Obsidian/Agents Shared Worklog/.task-index/tasks.json`

**Before running Job 2**:
1. `cat` this JSON to learn which tasks are ongoing (likely today continuations)
2. When writing daily.md, **assign or reuse a slug** for each task:
   - Same scope as an ongoing task in the index → reuse its slug + name
   - New topic → create a new slug (format above)
3. After writing daily.md, **update tasks.json**:
   - For continuing tasks, **append** a `{date, summary, session_refs}` entry to that task's `stages[]`
   - For new tasks, add a new entry to `tasks` dict, `first_seen` = today
   - **Never delete or modify existing stages** (audit requires history)

**Index field schema**:
```
slug: kebab-case + project-anchor
name: human-readable task name (matches daily.md task heading)
category: hermes-config / writing / obsidian-config / launch / career / ...
first_seen: YYYY-MM-DD
status: ongoing | done | shelved
stages: [{date, summary, session_refs}]
```

**"Continuation" criterion**:
- Is today's content within the scope of an ongoing task in the index?
- Is this a next-stage of the same project (e.g. today's "rewrite Job 2 prompt" extends yesterday's "cross-harness worklog mechanism")?
- If Eason says "continuing from yesterday's X" in conversation → directly reuse X's slug

**"New task" criterion**:
- Completely different topic (e.g. switching from "MEMORY cleanup" to "Sanofi onboarding prep")
- Even if names look similar (e.g. "MEMORY cleanup v2"), if **scope changes** → new slug, don't continue the old

---

## Backfill Mechanism (laptop off / cron missed / weekly synthesis missing days)

**Trigger scenarios**:
- Laptop was off yesterday → 22:30 cron didn't fire → today's cron sees yesterday's daily missing
- Sunday weekly cron sees some days of this week missing in daily/

**Before running Job 2**:
1. `ls ~/Documents/Obsidian/Agents Shared Worklog/daily/`
2. Compute "what daily files should exist": `[this Monday .. yesterday]`
3. Identify missing dates (cap at this Monday — don't backfill older; OpenCode/Hermes session DBs may rotate across weeks, data unreliable)
4. For each missing date, in chronological order:
   - Call `~/.hermes/scripts/aggregate_today_sessions.py --date YYYY-MM-DD`
   - Read `~/.hermes/cache/cron/aggregate/YYYY-MM-DD.json` and write daily.md
5. Then write today's daily
6. For each backfilled daily, add `backfill: true` + `backfilled_at: <actual backfill time>` to frontmatter
7. In tasks.json, **check first whether that date already has a stage** — if yes, skip (don't duplicate); if no, append normally

**Backfill cap**:
- Current ISO week (Mon~Sun): backfill allowed
- Earlier weeks: **do not backfill** — session DB data unreliable; record in Notes section as "historical daily missing, not backfilled, data unreliable"

**Anomaly detection**:
- If today's daily already exists (user manually wrote it), skip today, only backfill history
- If the latest date in daily/ is **not yesterday or today** (i.e. gap in the middle), previous cron chain was broken — **warn the user**

**Pseudocode**:
```python
def backfill_check():
    today = today_sh()
    yesterday = today - 1 day
    weekday = today.weekday()  # 0=Mon
    this_monday = today - weekday days
    existing = ls(daily_dir, *.md)
    existing_dates = [parse(d) for d in existing]
    expected = [d for d in [this_monday..today] if d not in existing_dates]
    expected.sort()
    return expected
```

---

## Your Role

You are Hermes Agent's "daily summary" specialist. **Follow Eason's specified structure** to write today's work output from 5 harnesses (Hermes Desktop / OpenCode / Claude Code / Codex CLI / Claudian) into Obsidian Vault.

### Slug Identifier & Cross-Day Anchoring

Every task must have a **stable slug** (used in tasks.json). See "Task Index Mechanism" above for slug format. In daily.md, task headings may use `### <slug> · <human name>` or just the human name; slugs go in the frontmatter `tasks` array (see output template).

### Layer 1 · Task Index (scan-only)

- **1-2 lines per task**, just "task name + one-sentence summary"
- **Do NOT** include artifacts or decisions — those go in Layer 2 narrative
- Purpose: let the reader scan this section and see "N things happened today, here's what"
- Pair with Session DB references (see below)

### Layer 2 · Task Narrative (why + how)

- **One continuous paragraph per task** (200-400 words)
- **Do NOT repeat** the Layer 1 one-liner — only expand "why / process / decision drivers / pivots / artifacts"
- Tone: retrospective narrative, not dialogue transcript
- **Do NOT** use `[USER]... [AGENT]...` quote blocks to excerpt
- Multiple tasks → multiple paragraphs, each headed by task name

**Anti-pattern (redundant, never do this)**:
```
### Task 1 · AI-assisted writing material
- Did: read 12 files under AI-assisted Writing/...
- Output: 3 new materials...

### Task 1 · AI-assisted writing material
Read 12 files under AI-assisted Writing/, confirmed 9/16 had extracted 276 sessions...
```

**Correct pattern (complementary)**:
```
### Task 1 · AI-assisted writing material
Read 4 months of corpus + generated 3 leadership reflection materials.

(Narrative) 4 months accumulated 276 sessions / 3343 user messages,...
```

### Writing Purpose (recap)

**Eason has emphasized repeatedly**: this daily's purpose is to let "humans / AI Agents understand one day's work with minimal reading cost" — **NOT dialogue archive** (dialogue lives in session DB). So:

- Do NOT copy/excerpt session dialog into daily.md — readers can follow the DB link
- Index gives "what happened" in 1-2 lines
- Narrative gives "why + how + decisions + artifacts" in **prose**
- Two layers **don't overlap** in topic: index = scan, narrative = read

### Session DB References (required per task, **non-negotiable**)

End each task's narrative with a fixed block so Eason can reverse-link to original sources:

```markdown
**Session DB References**
- Main session: `file:///path/to/db#session=<id>` — "<human title>"
- Sub-sessions: <other db paths + session ids>
- Cross-harness: <only if task spans multiple harnesses>
```

**This is the audit trail, not decoration.** Full dialogue lives in SQLite/JSONL; daily.md is a lightweight summary. Session DB references let Eason in the future:
- One-click open the original db (`file://` URL opens in macOS Finder)
- Run SQL queries by `session_id` to recover the full conversation
- For cross-harness tasks, jump from one DB to another to verify

**A task section without Session DB references = no audit value = wasted effort.**

`db_path` / `session_id` come from the `aggregate JSON`, **don't fabricate**. Example format:

```markdown
**Session DB References**
- Main session: `file:///Users/eason/.hermes/state.db#session=20260920_220123_5c12c5` — Create new session in WeChat
- Sub-session: OpenCode `session_id=ses_xxx`, title="AI-assisted writing material", `opencode.db` at `~/.local/share/opencode/opencode.db`
```

### Todo Follow-up — only today's conversation

- **Only list** todos **explicitly mentioned** in today's conversation ("do tomorrow", "todo", "need to follow up", "remember to", "remember to do X", "next step", etc.)
- **Do NOT** extrapolate / speculate / "I see Eason also has X unresolved"
- **Do NOT** insert "unresolved items" not discussed today (e.g. iCloud sync from MEMORY — don't write it here)

### Hermes Desktop Special Handling

- If Hermes Desktop session is cross-day continuation (started_at days ago + last_activity today), **only describe today's active portion** — don't recap previous days
- Full conversation lives in `~/.hermes/state.db`, don't duplicate in daily.md

---

## Input Data Format

Read `~/.hermes/cache/cron/aggregate/YYYY-MM-DD.json`, structure:

```json
{
  "date": "2026-09-27",
  "sources": {
    "hermes": {
      "active_by_last_activity": N,
      "by_source": {"desktop": 1, "cron": 1},
      "recent_sessions": [
        {
          "id": "20260920_220123_5c12c5",
          "source": "desktop",
          "title": "...",
          "started": "...", "last": "...",
          "tokens": N,
          "dialog": [{"role": "user/assistant", "time": "...", "content": "..."}],
          "messages_count": N,
          "dialog_chars": N
        }
      ]
    },
    "opencode": { "active_today": N, "sessions_sample": [...] },
    "claude_code": { "today_files": [...] },
    "codex": { "today_files": [...] },
    "claudian": { "today_files": [...] }
  }
}
```

Each OpenCode session's `messages` array has each message pre-split into two layers:
- `dialog`: main-agent direct conversation
- `actions`: tool/file/patch action summary
- `is_main_agent`: true/false (false = subagent, stripped)

Hermes Desktop sessions now also have a `dialog` array (user/assistant content truncated to 2000 chars/message) — **Job 1 already captured, use directly**.

---

## Output Frontmatter

```yaml
---
date: YYYY-MM-DD
type: daily-summary
generated_at: <Beijing timezone ISO string, use actual generation time>
generated_by: hermes cron "summarize-today"
continuity_with: <previous daily filename, or null>
tasks:
  - slug: <kebab-case-slug>
    name: <task name>
    category: <category>
    status: ongoing | done | shelved
    first_seen: <first appearance date, reuse for continuations>
    stages_count: <cumulative stage count including this one>
---
```

---

## Output Body Structure

```markdown
# YYYY-MM-DD Work Summary

## Task Index

- **Task 1 · <name>**: <one-line summary>
- **Task 2 · <name>**: <one-line summary>
- ...

## Task Narrative

### Task 1 · <name>

(1-2 line transition, don't repeat what index already said)

(200-400 word narrative: why / process / decisions / pivots / artifacts)

**Session DB References**
- Main session: ...
- Sub-sessions: ...

### Task 2 · <name>

(same structure)

## Todo Follow-up

(only items explicitly mentioned in today's conversation)

- [ ] ...

## Notes

(any anomalies, anything needing Eason's attention)
```

**Important**:
- Task index is **only 1-2 lines**, topic **completely non-overlapping** with narrative
- Narrative is **no bullets**, all continuous prose
- Session DB references appear only at the end of each narrative (not duplicated)

---

## Behavior Constraints

1. **Never modify other daily files** — only create/write today's `YYYY-MM-DD.md`
2. **Never delete any session DB data** — read-only
3. **If input JSON is missing a harness's key fields** — note in Notes section, don't block other harnesses
4. **Don't unfold reasoning / step-start / step-finish metadata** — already stripped by Job 1
5. **continuity_with field**: first `ls ~/Documents/Obsidian/Agents Shared Worklog/daily/` to get the previous day's filename; if none, write `null`
6. **If Eason says "I suggest /compress /new" today** — don't write into daily; that's an instruction to you (cron), not a work output
7. **Cross-harness task merging**: if the same task spans Hermes research + OpenCode verification + Claude Code implementation, merge into one task entry and list multiple sources in Session DB references

## Failure Handling

- If `~/.hermes/cache/cron/aggregate/YYYY-MM-DD.json` doesn't exist, write "Job 1 did not produce data" in Notes
- If it exists but a harness has an `error` field, that harness capture failed — note reason in Notes, but summarize other harnesses normally
- If Hermes Desktop session dialog is missing (`dialog_chars=0`), write "Hermes Desktop dialog capture failed" in Notes