---
name: agent-router
description: "MANDATORY before spawning ANY agent, subagent, background task, or thread, and before answering whether a task is heavy or light: route the task to the correct model tier (Opus 5.5 medium / Sonnet 5.5 / Pi Agent GLM-5.3-flash) by decision density, not by vibes. Default-to-cheapest, escalate only on failure signals, de-escalate once a plan exists."
---

# Agent Router (T3 Code)

**Purpose:** stop every spawned agent from starting as Opus 5.5 medium. Route by task class, burn the 5x Claude quota only on reasoning-heavy work, and run cheap bulk work outside the Claude quota entirely (Pi + GLM-5.3-flash rides the OpenCode Go key, not the Max sub).

## The three tiers

| Tier | Model | Burns | Role |
|---|---|---|---|
| C | Pi Agent + GLM-5.3-flash | OpenCode Go quota (Claude quota untouched) | Mechanical work, single-file edits, research dumps, command runs, summarization |
| B | Claude Code Sonnet 5.5 | Claude quota (cheap) | Well-specified multi-file work: implementation, tests, refactors, review of contained changes |
| A | Claude Code Opus 5.5 (medium) | Claude quota (expensive — the 5x burn) | Reasoning-heavy: planning, architecture, debugging, judgment, ambiguity resolution |

**Decision density is the axis — not task "importance."** A critical hotfix that touches one file with an obvious fix is Tier B or C. A "low priority" investigation that requires choosing between three architectures is Tier A.

## Routing procedure (run before EVERY spawn)

1. **Count the decisions the task must make unprompted:**
   - 0 → mechanical (edit exactly what's specified, follow conventions, no choices)
   - 1 → contained judgment (pick between known options with a stated criterion)
   - 2+ → design judgment (ambiguous spec, tradeoffs, architecture, debugging unknowns)
2. **Pick the tier:**
   - 0 decisions → **Tier C (Pi/GLM-5.3-flash)** unless the change touches >10 files or a concurrent critical path — then Tier B.
   - 1 decision, or >10-file mechanical work → **Tier B (Sonnet 5.5)**.
   - 2+ decisions, or the task says "should we / which / why is this failing" → **Tier A (Opus 5.5)**.
3. **Never spawn without naming the model.** The default profile exists to be overridden; if you are about to hit spawn without a deliberate model choice, stop and route.
4. **Cap every spawned agent** regardless of tier, in the task prompt: file budget, whether it may run commands, required report format (`result + files touched + deviations from spec`). This is what makes tier-C output verifiable and cheap.

## Escalation (only on failure signals, not on vibes)

Escalate C → B, B → A ONLY when one of these is observed while reading the agent's output:

- Two failed attempts on the same subtask with different approaches
- The agent invented an architecture or deviated from the spec's shape to make the problem easier
- Task revealed hidden coupling: it can't proceed without deciding something that wasn't in the prompt
- Context coherence loss: agent lost the plot of a multi-part task

Escalation = re-dispatch the same task to the next tier with the failed agent's report attached. Read the report yourself first — a tier-C agent that reports "blocked, need decision on X" is a success (correct escalation), not a failure.

**Tighten the prompt before escalating tier.** Escalation ladder per failed attempt:
1st fail → same tier, sharpened prompt (most failures are under-specification, not under-modeling)
2nd fail → next tier up with the prior report attached

## De-escalation

- After any Tier A pass produces a **plan or spec**, all remaining execution arms are re-routed by the same decision test — they will mostly be Tier B/C.
- Never keep a Tier A agent alive past its last hard decision. Kill it, keep the plan, spawn cheap doers.

## Anti-patterns (these are the whole point of this skill)

- Opus for everything "because it's the default."
- First at-bat failure → escalate. At-bat failures are often prompt problems; escalate the tier only after a second failure with a tightened prompt.
- Routing by deadline pressure or task drama instead of decision count.
- Sending Pi a vague prompt: Pi is minimal by design. Your prompt IS its spec. If the task couldn't be done by a careful junior dev from your prompt alone, it doesn't go to Tier C.

## Tier-specific prompting

- **Pi / GLM-5.3-flash:** one task, explicit file paths, explicit "do NOT:" list (no new deps, no renames, no editor opening). Ask for a structured report back.
- **Sonnet 5.5:** the spec plus acceptance criteria; parallel fan-out is fine since each arm is contained. Review its diff yourself before accepting.
- **Opus 5.5 (medium):** looser prompt, ask for the plan first and a checkpoint before executing. Medium is intentional — agent-strategy work doesn't need max.

## Reference

Full worked examples and edge cases: `references/escalation.md`
