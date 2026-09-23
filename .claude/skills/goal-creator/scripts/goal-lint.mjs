#!/usr/bin/env node
import { readFile } from "node:fs/promises";

const args = process.argv.slice(2);

function usage() {
  return `Usage:
  node goal-creator/scripts/goal-lint.mjs --text "<goal>" [--max-chars 4000] [--json]
  node goal-creator/scripts/goal-lint.mjs path/to/goal.txt [--max-chars 4000] [--json]

Checks whether a /goal draft contains durable done criteria, proof, scope,
constraints, operating loop, verification/review, stop policy, and receipt.`;
}

function takeFlag(name) {
  const index = args.indexOf(name);
  if (index === -1) return undefined;
  const value = args[index + 1];
  args.splice(index, 2);
  return value;
}

const json = args.includes("--json");
if (json) args.splice(args.indexOf("--json"), 1);

const help = args.includes("--help") || args.includes("-h");
if (help) {
  console.log(usage());
  process.exit(0);
}

const maxCharsRaw = takeFlag("--max-chars");
const maxChars = maxCharsRaw === undefined ? undefined : Number(maxCharsRaw);
if (maxCharsRaw !== undefined && (!Number.isInteger(maxChars) || maxChars <= 0)) {
  console.error("--max-chars must be a positive integer");
  process.exit(2);
}

const inlineText = takeFlag("--text");

async function readInput() {
  if (inlineText !== undefined) return inlineText;
  if (args.length === 1) return readFile(args[0], "utf8");
  if (!process.stdin.isTTY) {
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    return Buffer.concat(chunks).toString("utf8");
  }
  console.error(usage());
  process.exit(2);
}

const text = (await readInput()).trim();
const lower = text.toLowerCase();

const checks = [
  {
    id: "goal_marker",
    label: "Starts with or clearly contains /goal",
    weight: 5,
    pass: /(^|\s)\/goal\b/i.test(text),
    fix: "Start the contract with /goal unless the host uses a different native goal primitive.",
  },
  {
    id: "done",
    label: "Defines a done state",
    weight: 16,
    pass: /(definition of done|done means|end state|complete when|counts as done|objective)/i.test(text),
    fix: "Name the exact state that counts as complete.",
  },
  {
    id: "proof",
    label: "Requires visible proof",
    weight: 16,
    pass: /(verified by|proof|evidence|exact (command|output)|commands? and exits?|citation|log|artifact|screenshot|benchmark|test result)/i.test(text),
    fix: "Add transcript-visible proof such as exact command output, artifact checks, logs, citations, or review results.",
  },
  {
    id: "scope",
    label: "Bounds scope",
    weight: 10,
    pass: /(scope|within|only|allowed|repos?|files?|directories|worktrees?|branches?|environment|tools?)/i.test(text),
    fix: "State allowed files, repos, tools, data, services, environments, or worktrees.",
  },
  {
    id: "constraints",
    label: "States constraints or forbidden shortcuts",
    weight: 12,
    pass: /(while preserving|do not|must not|without|forbid|forbidden|avoid|no unrelated|not delete|not weaken|not skip)/i.test(text),
    fix: "Add non-negotiable constraints and shortcuts the agent must not use.",
  },
  {
    id: "loop",
    label: "Defines operating loop",
    weight: 10,
    pass: /(operating instructions|after each|inspect|hypothesis|smallest defensible|iterate|checkpoint|progress|re-plan|rerun focused)/i.test(text),
    fix: "Tell the agent how to choose the next action after partial progress or failure.",
  },
  {
    id: "verification",
    label: "Defines verification/review depth",
    weight: 14,
    pass: /(verification|review depth|adversarial review|self-review|focused checks?|broad checks?|reviewer|verifier|risk)/i.test(text),
    fix: "Specify focused checks, broad checks, and review depth based on risk.",
  },
  {
    id: "stop",
    label: "Defines stop policy",
    weight: 12,
    pass: /(stop if|blocked|blocker|no defensible path|missing (context|credential|permission)|budget|turn|time|cost|cannot run|cannot be verified)/i.test(text),
    fix: "Add when to stop as blocked and what evidence the blocker report must contain.",
  },
  {
    id: "receipt",
    label: "Requires completion receipt",
    weight: 10,
    pass: /(completion receipt|final receipt|print changed files|changed files|remaining risks|exact validation|commands and exits|review outcome)/i.test(text),
    fix: "Require a final receipt with changed files/artifacts, exact validation, review result, and risks.",
  },
];

const vaguePatterns = [
  /\bmake (it|this|the app|the code) better\b/i,
  /\bimprove\b(?![^.]{0,80}\b(by|to|below|above|from|verified|measured|test|build|metric|score|coverage)\b)/i,
  /\boptimi[sz]e\b(?![^.]{0,80}\b(by|to|below|above|from|verified|measured|baseline|metric|latency|time|score)\b)/i,
  /\bfix everything\b/i,
  /\buntil (it )?works\b/i,
  /\bas needed\b/i,
];

const vagueMatches = vaguePatterns
  .map((pattern) => lower.match(pattern))
  .filter(Boolean)
  .map((match) => match[0]);

const maxScore = checks.reduce((sum, check) => sum + check.weight, 0);
const score = checks.reduce((sum, check) => sum + (check.pass ? check.weight : 0), 0);
const percent = Math.round((score / maxScore) * 100);
const failures = checks.filter((check) => !check.pass);
const warnings = [];

if (maxChars !== undefined && text.length > maxChars) {
  warnings.push(`Length ${text.length} exceeds max ${maxChars}.`);
}
if (vagueMatches.length > 0) {
  warnings.push(`Vague phrasing detected: ${[...new Set(vagueMatches)].join(", ")}.`);
}
if (text.length > 5000) {
  warnings.push("Draft is very long; move plans/context into files and reference them from the goal.");
}
if (!/[0-9]/.test(text) && !/(checklist|artifact|review|citation|test|build|benchmark|source inspection)/i.test(text)) {
  warnings.push("No numeric target or concrete non-numeric proof anchor detected.");
}

const result = {
  score: percent,
  chars: text.length,
  maxChars: maxChars ?? null,
  pass: percent >= 82 && failures.length <= 1 && warnings.every((warning) => !warning.startsWith("Length")),
  checks: checks.map(({ id, label, pass }) => ({ id, label, pass })),
  missing: failures.map(({ id, label, fix }) => ({ id, label, fix })),
  warnings,
};

if (json) {
  console.log(JSON.stringify(result, null, 2));
} else {
  console.log(`Goal lint: ${result.score}/100 (${result.chars} chars)`);
  for (const check of result.checks) {
    console.log(`${check.pass ? "OK" : "MISS"} ${check.label}`);
  }
  for (const warning of warnings) {
    console.log(`WARN ${warning}`);
  }
  if (failures.length > 0) {
    console.log("\nFixes:");
    for (const failure of failures) console.log(`- ${failure.fix}`);
  }
}

process.exit(result.pass ? 0 : 1);
