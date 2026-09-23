# Host Profiles

Use this reference when compiling for a specific agent/runtime.

## Codex

Optimize for durable progress toward a real objective.

Include:
- objective and done state
- validation loop
- checkpoint evidence
- allowed tools and files
- scope boundary
- blocked behavior
- final receipt

Codex goals can run across long periods, so include checkpoint artifacts and clear stop conditions for non-trivial work.

## Claude Code

Optimize for a session-scoped completion evaluator.

The evaluator does not independently run commands or inspect files. Require Claude to surface proof in the transcript.

Include:
- one measurable end state
- exact proof that must be printed
- relevant constraints
- turn/time/cost bound when runaway work is possible
- compact wording

Keep under the host's character limit when known. If a hard budget is provided, verify with a character count.

## Cursor, OpenClaw, Generic Coding Agents

Optimize for portable acceptance contracts.

Avoid host-specific commands unless the user named them. Prefer:
- Definition of done
- allowed context
- verification commands
- forbidden shortcuts
- stop policy
- receipt

If the host lacks native goal state, make the goal usable as the first prompt and require the agent to maintain `PROGRESS.md` or an equivalent state artifact.

## Orchestrators

Optimize for workflow state, ownership, and independent verification.

Separate roles:
- Orchestrator: queue, decomposition, worker selection, status, handoffs, final verification.
- Builder: implementation.
- Reviewer: defect discovery.
- Verifier: command execution and artifact inspection independent of builder self-report.

Add:
- card/task status model
- worktree or branch ownership
- one writer per file/module
- review-to-fix loop
- final independent verification
- skipped-step receipt when conditional cards are not needed

## CI, Batch, and Background Workers

Optimize for deterministic execution.

Include:
- machine-readable artifacts
- exact commands
- exit criteria
- logs and output paths
- retries and stop policy
- notification or report destination
- no interactive assumptions unless explicitly available

