# Escalation Reference — worked examples and edge cases

## Worked routing examples

| Task | Decisions | Tier | Why |
|---|---|---|---|
| "Add a `phone` field to the users table + form + tests, spec below" | 0 | C | Fully specified, follows existing patterns |
| "Migrate these 40 components off prop X to prop Y (mechanical, listed)" | 0, large | B | Mechanical but big; parallel Sonnet arms |
| "Build notification system; we need in-app + email, decide transport" | 2+ | A | Transport choice shapes everything downstream |
| "Why is the production build flaky in CI, sometimes times out?" | 2+ | A | Unknown-unknowns debugging, hypotheses needed |
| "Find every endpoint returning 200 with an error body, report list" | 0 | C | Search + report, no judgment |
| "Write the commit message for this diff" | 0 | C | Trivial, but bounded |
| "Review this 800-line PR" | 1 | B | Contained: review against stated criteria |
| "Design the testing strategy for the new payments module" | 2+ | A | Strategy = design judgment |
| "Fix the 12 failing tests, names listed, they regressed after bump X" | 1 | B | Repro known, judgment is in reading failures |
| "Figure out whether we should shard or cache; write a one-pager" | 2+ | A | Writing the recommendation IS the deliverable |

## Edge cases

**"Start with Opus to scope it, then fan out."** Correct pattern. Explicit:
1. Spawn ONE Opus agent with "produce the plan and STOP. No implementation."
2. Plan comes back → apply the routing test per execution arm.
3. Most arms are Sonnet; pure grunt arms are Pi.

**Task grew mid-flight.** Agent at tier C reports "this is actually 3 component redesigns." Do not let it wing it. Kill, regenerate a proper plan (Tier A if redesigns are cross-cutting), re-route arms.

**Can't tell if it's 1 or 2+ decisions.** Route A (Opus) for the FIRST turn only — ask it to reduce the task to a spec — then re-route the execution at B/C. One expensive scoping pass beats three cheap failed passes.

**Quota pressure (late in the 5x window).** When Claude quota is scarce, shift the boundary: mechanical work that would normally be B drops to C even at 10+ files (do it in serial Pi passes instead of parallel Sonnet). Opus stays reserved for decisions that can't be made any other way — at quota exhaustion the right "model" for tier-B work is a better Py\\ prompt to Pi, not spending the last Opus tokens.

**Tighten the prompt before escalating tier.** Escalation ladder per failed attempt:
1st fail → same tier, sharpened prompt (the failure is often under-specification)
2nd fail → next tier up with prior report attached
Never skip: two cheap failures teach you exactly which decision the task actually requires.

## Prompt template (per dispatched agent)

```
Task: <one sentence>
Tier: <A/B/C> — Model: <exact model name in T3 Code picker>
Files in scope: <explicit paths or globs>
May run commands: yes/no
Decisions you may make unprompted: <0, or list — anything else: STOP and report>
Do NOT: <new deps / renames / format passes / opening editor etc.>
Report back: result (done/blocked/failed) + files touched + deviations + questions
```

Fill the template every dispatch. It is the contract that makes tiers re-routable: a blocked tier-C report is the input to a tier-B or tier-A dispatch, and no context is lost.

## Edge cases

**"Start with Opus to scope it, then fan out."** Correct pattern. Explicit:
1. Spawn ONE Opus agent with "produce the plan and STOP. No implementation."
2. Plan comes back → apply the routing test per execution arm.
3. Most arms are Sonnet; pure grunt arms are Pi.

**Task grew mid-flight.** Agent at tier C reports "this is actually 3 component redesigns." Do not let it wing it. Kill, regenerate a proper plan (Tier A if redesigns are cross-cutting), re-route arms.

**Can't tell if it's 1 or 2+ decisions.** Route A (Opus) for the FIRST turn only — ask it to reduce the task to a spec — then re-route the execution at B/C. One expensive scoping pass beats three cheap failed passes.

**Quota pressure (late in the 5x window).** When Claude quota is scarce, shift the boundary: mechanical work that would normally be B drops to C even at 10+ files (do it in serial Pi passes instead of parallel Sonnet). Opus stays reserved for decisions that can't be made any other way — at quota exhaustion the right "model" for tier-B work is a better-written prompt to Pi, not spending the last Opus tokens.

**Tighten the prompt before escalating tier.** Escalation ladder per failed attempt:
1st fail → same tier, sharpened prompt (the failure is often under-specification)
2nd fail → next tier up with prior report attached
Never skip: two cheap failures teach you exactly which decision the task actually requires.
