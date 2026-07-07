# Issue — Plan card stuck on the ○ pending circle after tools ran

**Date solved:** 2026-07-03
**Area:** frontend chat / multi-tool plan gate
**Reported by:** PhD-student testing

---

## Symptom
After the user pressed **Confirm & run** on a multi-tool plan card, the tools
actually executed and produced their outputs — but one or more steps in the plan
card kept showing the `○` (pending / "not done") mark instead of the `✓` done
mark. It looked like the work had failed even though it succeeded.

## Root cause (why the bug came)
Plan steps only advance through the icons `○ pending → ◐ running → ✓ done` if the
frontend receives live tool events whose tool-name **exactly matches** the plan
step's `tool` field. The step-marking helper (`markStep` in `Chat.jsx`) flips a
step to `done` **only if it was first marked `running`**. So if a start event was
missed, arrived out of order, or the executing tool's name didn't match the
planned step's name, the step never left `pending` and stayed on the `○` circle —
even after the whole plan finished. The card already knew the plan was finished
(`planState: 'done'`), but the per-step render didn't use that fact.

## How we fixed it
In `frontend/src/features/chat/PlanCard.jsx`, the step render now computes an
**effective status**: once `planState === 'done'`, any step that didn't explicitly
`error` is rendered as `done` (`✓`). This means a step whose tool-name never
matched a live event can no longer get stuck on `○`. The circle still correctly
shows for a not-yet-run step in a *proposed* plan, and a genuinely failed step
still shows `✕` so real errors aren't hidden.

Also added the missing **"Plan complete"** header label — a finished plan used to
fall back to mislabeling itself "Proposed plan".

## Files changed
- `frontend/src/features/chat/PlanCard.jsx` — effective step status on completion
  + `done` header label

## How to verify
```bash
docker compose up -d --build
```
In the app: ask something that triggers a ≥2-tool plan, press **Confirm & run**,
let it finish. All steps should show `✓` and the header should read
"Plan complete". A step that truly errors should still show `✕`.

## Lesson
Don't derive per-item UI state purely from a stream of match-by-name events that
can be missed or misordered — reconcile against the known terminal state of the
whole operation. When the parent says "done", the children should reflect done.
