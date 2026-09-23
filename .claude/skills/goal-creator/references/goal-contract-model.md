# Goal Contract Model

Use this reference when the goal is complex, long-running, high-risk, or easy to game.

## Principle

A goal is an exit contract plus operating loop. It should not prescribe every implementation step unless the user already did. It should constrain success, not creativity.

Strong goals make three things explicit:

1. The desired world state.
2. The verifier that can prove the state.
3. The conditions under which the agent must stop.

## Goal Fit

Good fits:
- migrations with measurable call-site or behavior parity
- debugging where reproduction and fix verification are possible
- performance work with comparable baseline and after measurements
- test reliability work with repeated pass criteria
- audits with claim inventories and citations
- generated artifacts that can be built, opened, rendered, or checked
- background work that needs checkpoints and final receipt

Bad fits:
- "explain this"
- "make it better" with no target
- exploratory product direction without extracted ontology
- work that requires credentials or production mutation not authorized by the user
- creative judgment tasks with no inspectable artifact or acceptance criteria

## Anatomy

End state:
- Prefer one primary outcome.
- Use numbers only when meaningful.
- If the outcome is qualitative, attach it to a checklist, artifact review, or accepted examples.

Proof:
- Commands and exits.
- Source inspection with file paths or citations.
- Live checks.
- Screenshots or visual diffs.
- Logs.
- Benchmarks.
- Review findings.
- Artifact existence plus content checks.

Scope:
- Repos, packages, files, directories.
- Branches or worktrees.
- Tools and integrations.
- Environments.
- Data boundaries.
- External side-effect boundaries.

Operating loop:
- Inspect current state before editing.
- Use focused checks before broad checks.
- After failures, update the hypothesis.
- Prefer smallest defensible change.
- Keep a progress artifact for long runs.
- Re-plan when evidence invalidates the path.

Stop policy:
- Missing permissions, credentials, context, source access, or realistic environment.
- Unsafe ambiguity.
- Verification cannot run.
- No defensible path remains.
- Time, turn, or cost budget.
- Repeated failed approaches without new evidence.

Receipt:
- Changed files and artifacts.
- Exact commands and exits.
- Review result.
- Proof links/logs/citations.
- Remaining risks.
- Explicit unverified items.

## Anti-Gaming Patterns

Tests:
- Require clean diff review showing tests were not deleted, skipped, weakened, or redefined away from the intended behavior.

Performance:
- Require baseline and after runs in comparable conditions.
- Require explanation of why the improvement is causal.
- For production-facing claims, require production-like flags, data, and build paths.

Visual:
- Avoid "pixel perfect" unless a real comparison harness exists.
- Require responsive viewports, states, and design-system constraints.
- Forbid image-cropping/reference-embedding shortcuts.

Research:
- Require claim inventory.
- Require evidence map.
- Label claims as confirmed, supported, uncertain, or blocked.
- Separate source facts from inference.

Data/security:
- Require dry run before mutation when possible.
- Require backup/rollback notes for destructive or migration work.
- Forbid secret printing.
- Require explicit permission for live mutation.

## Long-Running Goals

Add when duration may exceed a normal interactive session:

- checkpoint cadence
- progress artifact
- meaningful commits or draft PR updates when useful
- independent status/query path
- cleanup phase before completion
- budget and blocked bounds
- final review after failed attempts have been removed

Do not let a long-running goal become terminal chaos. If multiple workers are involved, the goal must identify ownership boundaries and handoff rules.

## Goal Versus Spec

A spec describes desired behavior. A goal binds an agent session to keep working until a verifiable stopping condition is met.

Use a spec when:
- the user only needs acceptance criteria
- no stateful agent lifecycle is needed
- orchestration, budget, blocked status, and verification can live elsewhere

Use a goal when:
- the agent must keep iterating
- the task may run unattended
- success requires transcript-visible proof
- handoffs, review loops, or status management matter

