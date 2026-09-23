# Example Goals

Use these as shape references. Do not copy blindly; compile to the user's actual context.

## Code Migration

```text
/goal Definition of done: the billing module uses the v2 API at every intended call site, verified by transcript-visible source inspection plus passing focused billing tests and the relevant typecheck/build command, while preserving public billing behavior, existing data contracts, and unrelated files. Operating instructions: use the migration docs, billing tests, and local commands; migrate in small slices, inspect failures after each run, and keep a progress receipt of migrated call sites. Verification: high risk because this changes behavior; require two consecutive adversarial reviews with no medium-or-above findings. Stop if API behavior cannot be confirmed, verification cannot run, or no defensible path remains; report attempted paths, evidence, blocker, and next input needed. Completion receipt: changed files, exact commands/exits, review outcome, and remaining risks.
```

## Flaky Test Debugging

```text
/goal Definition of done: the flaky checkout test either passes reliably or has a transcript-supported blocker, verified by reproducing the failure when possible and surfacing exact focused test results plus the relevant regression command output, while preserving checkout behavior and existing coverage. Operating instructions: inspect the test, fixtures, logs, and implementation; after each failure update the hypothesis, make the smallest defensible change, and rerun focused verification before broad checks. Verification: medium risk; require one adversarial review and resolve all medium-or-above findings. Stop after 20 turns, if the failure cannot be reproduced after reasonable attempts, or if no valid path remains; report reproductions, evidence, blocker, unresolved findings, and next input needed.
```

## Performance

```text
/goal Definition of done: production build time is reduced by at least 30% against the current baseline, verified by before/after timed runs in comparable production-like configuration and a transcript-visible explanation of the causal change, while preserving build outputs and deployment behavior. Operating instructions: first establish the baseline and bottlenecks, then make the smallest defensible changes; do not disable build paths, tests, production flags, or cache correctness to win the metric. Verification: medium/high depending on deploy impact; run focused build checks plus adversarial review. Stop if the environment cannot mimic production well enough for the claim, or if no defensible improvement remains.
```

## Research Or Audit

```text
/goal Definition of done: produce a claim inventory and evidence-backed report for <topic>, verified by source links/file citations for every material claim and explicit labels for confirmed, supported, uncertain, or blocked findings. Operating instructions: inspect primary sources first, keep notes in <artifact>, avoid unsupported synthesis, and challenge the strongest assumptions before finalizing. Verification: low/medium depending on operational impact; run one adversarial review for missing evidence or overclaims. Stop if source access blocks material claims; report what is missing and why.
```

## Better As A Prompt

```text
Better As A Prompt:
Explain this error message in plain English, identify the likely cause, and suggest the next command or file to inspect.

Why Not A Goal:
This is a one-off explanation request without a durable objective that needs continued work.
```

