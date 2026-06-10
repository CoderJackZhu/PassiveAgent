# PassiveAgent Weekly Report + Feishu Push Implementation Plan

> **For Hermes:** Use Codex CLI for code implementation. Hermes owns planning, progress notes, independent verification, and final summary. Keep this file updated after each phase so long conversations can resume from disk.

**Goal:** Add a weekly report feature that summarizes article recommendation exposure, click/reading interactions, explicit ignores, passive non-response, and pushes the report to Feishu every Sunday night.

**Architecture:** Add a lightweight item-event layer separate from the existing negative-feedback table. Weekly reporting aggregates `pushed` and card-action events over the current week, renders a Markdown report to `data/reports`, optionally sends a compact Feishu card, and is scheduled by launchd on Sunday evening. Keep the existing daily/weekend pipeline behavior intact.

**Tech Stack:** Python 3.11, SQLite, Click CLI, Feishu interactive cards, launchd plist, pytest, uv, Codex CLI.

---

## Current State Snapshot

- Date checked: 2026-06-10 21:08 CST
- Repo: `/Users/jackzhu/Code/Agents/PassiveAgent`
- Branch: `main` tracking `origin/main`
- Initial git status: clean
- Codex CLI: `/opt/homebrew/bin/codex`, version `0.138.0`
- Existing weekly support:
  - `passive_agent.pipeline.generate_weekly_report()` generates local Markdown only.
  - CLI has `passive-agent weekly-report` but no `--push`.
  - No launchd plist for weekly report push.
- Gaps to fix:
  - No durable item-level exposure/click event log.
  - Feishu callback clicks are not uniformly recorded.
  - `read` action does not save feedback/event rows.
  - Weekly report cannot accurately distinguish clicked/read/ignored/passively ignored.
  - Feishu has no weekly report card sender.

---

## Event Taxonomy

Use a new table `item_events`; do not overload `feedback` because `feedback` drives recommendation penalties.

| event_type | Meaning | Producer |
|---|---|---|
| `pushed` | Item was exposed in a Feishu card | daily/weekend/manual push |
| `expand` | User clicked expand | Feishu callback / CLI action if applicable |
| `weekend` | User added item to weekend queue | callback / CLI action |
| `ignore` | User explicitly ignored item | callback / CLI action |
| `read` | User marked item read | callback / CLI action |
| `generate_card` | User generated interview card | callback / CLI action |
| `generate_note` | User generated tech note | callback / CLI action |
| `link` | User linked notes | callback / CLI action |
| `mute` | User muted similar items | callback / CLI action |
| `weekly_report_pushed` | Weekly report was pushed | weekly report command |

MVP definition:

- **Clicked / engaged:** any of `expand`, `read`, `generate_card`, `generate_note`, `weekend`, `link`, `mute`.
- **Read:** `read` event, or `stage='archived'` with `actioned_at` inside the week.
- **Explicitly ignored:** `ignore` event.
- **Passively ignored / no response:** item had `pushed` event in the week and no engagement/ignore event after the first push within that week.

---

## Acceptance Criteria

1. Database schema includes `item_events` and `weekly_reports` with migrations for existing DBs.
2. Daily/weekend/manual Feishu sends record `pushed` events only after the card send succeeds.
3. Feishu callbacks and CLI `action` record item events for supported actions.
4. `weekly-report` writes a Markdown report with:
   - collection/process/push totals from `daily_log`
   - distinct pushed item count
   - engaged/clicked count and rate
   - read count
   - explicit ignore count
   - passive non-response count
   - topic/source distributions for pushed, engaged, ignored, passive non-response
   - top clicked/read and ignored/non-response item lists
   - short next-week suggestions
5. `weekly-report --push` sends a compact Feishu card and is idempotent by week unless `--force` is supplied.
6. Sunday night launchd job exists: `com.passive-agent.weekly-report`, scheduled Sunday 21:30, command `weekly-report --push`.
7. `scripts/install_launchd.sh` installs the new plist and prints it in service summary.
8. Tests cover DB event recording, weekly aggregation/report rendering, Feishu card construction, CLI flags or command behavior where practical, and launchd installer/plist awareness.
9. Verification commands pass:
   - targeted pytest for touched tests
   - full `uv run pytest tests/ -v`
   - `git diff --check`
   - `plutil -lint scripts/*.plist`
   - `uv run passive-agent --help`
   - `uv run passive-agent weekly-report --help`
10. No secrets are written to repo files or prompts.

---

## Implementation Tasks

### Task 1: Add DB event and weekly report persistence primitives

**Files:**
- Modify: `src/passive_agent/storage/database.py`
- Modify: `tests/test_database.py`

**Steps:**
1. Write failing tests for:
   - fresh DB creates `item_events` and `weekly_reports`
   - `record_item_event()` persists metadata and timestamp
   - `get_item_events_between()` returns events within inclusive/exclusive week window
   - weekly report push state can be saved/read for idempotency
2. Run targeted tests and confirm failure.
3. Implement schema version bump and migration.
4. Implement DB helper methods.
5. Run targeted tests and confirm pass.

### Task 2: Record pushed and action events

**Files:**
- Modify: `src/passive_agent/feishu/bot.py`
- Modify: `src/passive_agent/feishu/callbacks.py`
- Modify: `src/passive_agent/main.py`
- Modify: tests touching Feishu/pipeline/action behavior

**Steps:**
1. Write failing tests that successful daily/weekend/manual push records `pushed` with correct surface.
2. Write failing tests that callback/CLI actions record mapped event types.
3. Implement event recording after successful send/action.
4. Preserve existing negative-feedback behavior for `ignore`.
5. Run targeted tests and confirm pass.

### Task 3: Build weekly report aggregation/rendering module

**Files:**
- Create: `src/passive_agent/reports/__init__.py`
- Create: `src/passive_agent/reports/weekly.py`
- Modify: `src/passive_agent/pipeline.py` or keep compatibility wrapper only
- Modify: `tests/test_pipeline.py` or add `tests/test_weekly_report.py`

**Steps:**
1. Write failing tests with synthetic items/events covering pushed, engaged, read, explicit ignore, passive no-response, topic/source stats.
2. Implement dataclasses and aggregation.
3. Render Markdown report with stable headings/metrics.
4. Keep `generate_weekly_report(config, db)` as a wrapper for backwards compatibility.
5. Run targeted tests and confirm pass.

### Task 4: Add Feishu weekly report card and push CLI

**Files:**
- Modify: `src/passive_agent/feishu/cards.py`
- Modify: `src/passive_agent/feishu/bot.py`
- Modify: `src/passive_agent/main.py`
- Add/modify tests for cards and CLI/help

**Steps:**
1. Write failing tests for card content and `weekly-report --push` idempotency behavior.
2. Add `CardBuilder.build_weekly_report_card(report)`.
3. Add `FeishuBot.send_weekly_report_card(report)`.
4. Extend CLI: `weekly-report --push --force`.
5. On successful push, record `weekly_reports.pushed_at` and item event `weekly_report_pushed` with metadata.
6. Run targeted tests and confirm pass.

### Task 5: Add launchd weekly schedule and docs/progress updates

**Files:**
- Create: `scripts/com.passive-agent.weekly-report.plist`
- Modify: `scripts/install_launchd.sh`
- Modify: `tests/test_launchd_installer.py`
- Modify docs if existing README/config docs reference service list
- Update this plan's Progress Log

**Steps:**
1. Write/adjust tests for installer handling four plist files/service summary.
2. Add plist: Sunday 21:30, `weekly-report --push`, logs under `data/logs` if the project convention is updated.
3. Update installer output.
4. Run shell/plist validation.

### Task 6: Independent verification and Codex review loop

**Steps:**
1. Hermes runs full verification commands from acceptance criteria.
2. Hermes inspects `git diff --stat` and critical hunks.
3. Run Codex read-only review: no modifications, findings only.
4. If findings exist, run Codex fix pass with minimal scope.
5. Hermes reruns full verification.
6. Update Progress Log and final status.

---

## Progress Log

| Time | Status | Notes |
|---|---|---|
| 2026-06-10 21:08 CST | started | Repo clean; Codex available; implementation plan created. |
| 2026-06-10 21:13 CST | red tests written | Added failing tests for DB event/report persistence, Feishu pushed/action events, weekly aggregation/card/CLI push idempotency, and weekly launchd plist/installer awareness. Targeted pytest failed as expected: 15 failed, 21 passed. |
| 2026-06-10 21:18 CST | storage/events green | Implemented schema v5 with `item_events` and `weekly_reports`; storage tests pass (`11 passed`). Wired Feishu push/callback/CLI action event recording; targeted event tests pass (`7 passed`, third-party lark warnings only). |
| 2026-06-10 21:23 CST | weekly report/push green | Added `passive_agent.reports.weekly`, preserved `generate_weekly_report` path-returning wrapper, added weekly Feishu card, `weekly-report --push/--force`, and Sunday 21:30 plist/installer summary. Weekly/launchd tests pass (`7 passed`). |
| 2026-06-10 21:25 CST | Codex implementation verified | Added passive-after-first-push edge test and fix. Final verification: `uv run pytest tests/ -v` passed (`68 passed, 1 warning`); `git diff --check` passed with no output; `plutil -lint scripts/*.plist` passed; `uv run passive-agent --help` and `uv run passive-agent weekly-report --help` passed. No commit made. |
| 2026-06-10 21:24 CST | Hermes verification pass 1 | Hermes independently ran targeted tests (`25 passed`), full tests (`68 passed, 1 warning`), `git diff --check`, plist lint, `bash -n scripts/install_launchd.sh`, CLI help via `/Users/jackzhu/.local/bin/uv`, and a temp-config weekly-report smoke test. Note: bare `uv` was not on non-login shell PATH, so Hermes reran CLI checks with the resolved uv path. |
| 2026-06-10 21:31 CST | Codex review fixes green | Codex read-only review found no blocker/high issues and raised medium/low gaps. Added regression coverage for legacy ignore feedback backfill, click-time Feishu callback events on unconfigured/failed paths, weekly push send failure state, and scheduled-task docs. Implemented idempotent legacy ignore event backfill, moved callback event recording to dispatch-time single insert, and updated launchd docs to 4 tasks. Hermes reverified targeted tests (`26 passed`), full suite (`72 passed, 1 warning`), lint/check commands, CLI help, and smoke test. Follow-up Codex review found no blocker/high issues. |
| 2026-06-10 21:36 CST | launchd log convention fix | Codex updated all launchd plist templates to write stdout/stderr under `data/logs/`, updated installer/docs, and added tests for this convention. Hermes verified launchd tests (`7 passed`), `git diff --check`, plist lint, `bash -n`, and full test suite (`74 passed, 1 warning`). |

## Current TODO State

- [x] Check repo status/date/Codex availability.
- [x] Write local implementation plan.
- [x] Codex implementation pass: complete and verified; no commit made.
- [x] Hermes independent verification.
- [x] Codex read-only review and fix/reverify loop.
- [x] Final progress update and user summary.

---

## Resume Instructions

If context is lost, resume by reading this file and running:

```bash
cd /Users/jackzhu/Code/Agents/PassiveAgent
git status --short --branch
git diff --stat
uv run pytest tests/ -v
```

Then continue from the first unchecked item in **Current TODO State**.
