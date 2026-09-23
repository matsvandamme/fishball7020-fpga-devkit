---
name: goal-creator
description: Compile plain-language work into concise, host-aware, verifiable agent goals. Use when drafting, rewriting, tightening, auditing, or deciding whether to use a /goal-style contract for Codex, Claude Code, Cursor, OpenClaw, GitHub Copilot, orchestrators, CI agents, background workers, coding agents, review agents, research agents, migrations, debugging, refactors, audits, long-running tasks, or any multi-step work that needs explicit done criteria, proof, stop policy, anti-gaming constraints, review depth, and a completion receipt.
---

# Goal Creator

## Operating Mode

Act as a goal compiler, not a prompt decorator. Convert the user's real objective into the shortest durable execution contract that makes success checkable and fake completion difficult.

Default to a normal prompt instead of a goal when the task is one-shot, explanatory, trivial, or lacks a durable proof surface.

## Fast Path

1. Extract the real objective. Ignore mentions of this skill.
2. Identify the host: Codex, Claude Code, Cursor, OpenClaw, orchestrator, CI/background worker, or generic agent. If unspecified, write a portable goal and mention host assumptions only when they affect behavior.
3. Decide whether a goal is appropriate.
4. Compile the goal with:
   - one primary end state
   - transcript-visible proof
   - allowed scope, context, tools, and environment
   - constraints and forbidden shortcuts
   - operating loop
   - verification and review depth
   - stop policy
   - completion receipt
5. Run the checklist below. Use `scripts/goal-lint.mjs` when a draft is non-trivial, user-facing, or has a hard length budget.
6. Return the ready-to-use goal plus only the assumptions and compiler notes that matter.

## Contract Shape

Prefer this structure:

```text
/goal Definition of done: <one durable end state>, verified by <specific transcript-visible proof>, while preserving <non-negotiable constraints> and staying within <scope>.

Operating instructions: use <allowed context/tools/files/environments>; first inspect <source-of-truth inputs>; after each failure or partial result, update the hypothesis and make the smallest defensible next move. Maintain <progress artifact or checkpoint cadence if long-running>. Do not <forbidden shortcuts>.

Verification: run <focused checks> before <broad checks>; require <review tier>; independent verifier/reviewer must confirm <critical proof> when risk warrants it.

Stop if <blocked condition, unsafe ambiguity, missing credential, no defensible path, or budget bound>; report attempted paths, evidence gathered, blocker, unresolved findings, and next input needed.

Completion receipt: print changed files/artifacts, exact validation commands and exits, review result, proof links/logs, and remaining risks.
```

For hosts with strict character budgets, compress to one paragraph while preserving done, proof, constraints, verification, stop policy, and receipt.

## Decision Checklist

A draft is not done until these are clear:

- End state: What is true when work is complete?
- Proof: What exact output, command, artifact, citation, screenshot, log, or review result proves it?
- Scope: What repos, files, services, data, tools, branches, worktrees, and environments are allowed?
- Constraints: What must not regress, mutate, leak, delete, or be faked?
- Context: What specs, docs, issues, plans, logs, or prior decisions must be referenced instead of buried in the goal?
- Loop: How should the agent choose the next move after failures or partial progress?
- Review: What risk tier and review loop protect the objective?
- Stop: When should the run stop as blocked instead of thrashing?
- Receipt: What must be printed before completion?

If a missing answer could change product semantics, architecture, migration behavior, security, data safety, permissions, cost, or long-term maintainability, ask targeted questions before compiling.

## Risk Tiers

Low:
- Read-only research, docs, small content edits, local cleanup.
- Require one self-review or adversarial review and resolve medium-or-above findings.

Medium:
- Normal code changes, refactors, tests, generated artifacts, or docs that describe behavior.
- Require focused verification plus one adversarial review.
- Resolve all medium/high/critical findings.

High:
- Public APIs, migrations, security, auth, permissions, data loss, release/publish flows, activation, packaging, command behavior, broad cross-file behavior, or production-affecting changes.
- Require two consecutive clean adversarial reviews with no medium-or-above findings.
- If a review finds a medium-or-above issue, fix it and restart the clean-review count.

## Anti-Gaming Defaults

Add explicit "Do not" clauses when the agent could satisfy the metric while violating intent:

- Do not delete, skip, weaken, or rewrite tests just to pass.
- Do not hide failures behind mocks when real integration proof is required.
- Do not disable production build paths, flags, or safety checks to improve a metric.
- Do not crop/embed a reference image to claim visual fidelity.
- Do not declare success without exact validation output.
- Do not broaden scope to make an easier unrelated improvement.
- Do not mutate live data, secrets, permissions, billing, or external systems unless the user explicitly authorized it.

## Host Notes

Read `references/host-profiles.md` when host behavior matters.

Use these defaults:

- Codex: durable objective, validation loop, checkpoint evidence, scope boundary, blocked behavior, final receipt.
- Claude Code: completion evaluator needs proof in transcript; keep the condition compact and under the host limit.
- Generic agents: write as an acceptance contract with proof and stop policy; avoid host-specific commands.
- Orchestrators: separate builder, reviewer, verifier, handoff, queue state, worktree/branch boundaries, and final independent verification.

## Resources

- `scripts/goal-lint.mjs`: deterministic draft checker for structure, length, vague language, missing proof, missing stop policy, and missing receipt.
- `references/goal-contract-model.md`: deeper model, anti-gaming patterns, long-running goals, and task-specific contract guidance.
- `references/host-profiles.md`: host-specific goal semantics.
- `references/example-goals.md`: compact examples for common task types.

## Output Format

When a goal is appropriate:

```text
Recommended Goal:
<ready-to-use /goal block>

Assumptions:
<only material assumptions, or omit>

Compiler Notes:
- Host: <host/profile>
- Proof: <main proof surface>
- Review: <risk tier>
- Stop: <main bound>
```

When a goal is not appropriate:

```text
Better As A Prompt:
<concise normal prompt>

Why Not A Goal:
<one sentence naming the missing durable objective or proof surface>
```

Keep the answer concise. The user came for the goal, not a lecture about goals.
