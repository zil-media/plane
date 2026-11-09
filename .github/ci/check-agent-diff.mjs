#!/usr/bin/env node
/**
 * check-agent-diff — blast-radius guard for the agent branches (claude/**, feat/agent/**).
 *
 * The agents' rules live in prompts (docs/agents/*_INSTRUCTIONS.md). A prompt is a suggestion; this
 * script runs in CI and cuts. Two levels, on purpose:
 *
 *  - DENY: fails. A SHORT list — only what a reviewer can't catch reading a diff (a three-line auth
 *    bypass) or what would let the agent dismantle its own review (workflows, this script, its API).
 *  - ANNOTATE: passes with a ⚠ in the report. In the feature PR lane a human reads it; any ⚠ also
 *    keeps a feature out of the auto-merge lane.
 *
 * --strict (the lanes that merge with nobody reading): STRICT_DENY entries and file deletions cut too.
 *
 * Usage: node check-agent-diff.mjs [--base origin/preview] [--strict] [--report <file.md>]
 * Exit: 0 pass (with or without notes), 1 denied.
 */

import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";

/** A diff this big is skimmed, not reviewed. Locale files don't count toward the file cap. */
const MAX_FILES = 40;
const MAX_LINES = 2500;
const LOCALE_FILE = /^packages\/i18n\/src\/locales\//;

/** Every entry says WHAT breaks, so nobody "fixes" a failure by deleting the rule. */
const DENY = [
  // The agent must not weaken its own review.
  { re: /^\.github\//, why: "workflows and CI scripts ARE the review: editing them lets the agent approve itself" },
  {
    re: /^docs\/agents\//,
    why: "the agents' own instructions; a person edits them and re-pastes them into the routine",
  },
  { re: /^apps\/api\/plane\/agent_api\//, why: "the agent API: widening it widens what its key can do" },
  {
    re: /^apps\/api\/plane\/utils\/agent_pipeline\//,
    why: "routine triggers, queue rules and admin checks of the pipeline",
  },
  { re: /^apps\/api\/plane\/app\/views\/support\//, why: "human-only decisions (approve, reject, flags) live here" },
  { re: /^apps\/api\/plane\/app\/urls\/support\.py$/, why: "routes of the human-only decisions" },

  // What CI checks, and how.
  { re: /^apps\/api\/(pytest\.ini|pyproject\.toml)$/, why: "defines which tests run and which lint rules apply" },
  { re: /^apps\/api\/plane\/tests\/conftest\.py$/, why: "global test fixtures: can silence the whole suite" },
  {
    re: /(^|\/)tsconfig(\.[^/]+)?\.json$/,
    why: "defines what typecheck covers: an exclude skips the file that doesn't compile",
  },
  { re: /(^|\/)\.ox(lint|fmt)rc\.json$/, why: "lint/format rules of the gate" },
  { re: /^turbo\.json$/, why: "task graph of every gate" },

  // Authentication, tenancy and privilege.
  { re: /^apps\/api\/plane\/authentication\//, why: "sign-in, SSO with Zil Workspace and service-to-service sync" },
  { re: /^apps\/api\/plane\/license\//, why: "instance admins and instance configuration" },
  { re: /^apps\/api\/plane\/(app\/permissions|utils\/permissions)\//, why: "role and permission checks" },
  {
    re: /^apps\/api\/plane\/(middleware|app\/middleware|api\/middleware)\//,
    why: "request middleware: auth, API keys, logging",
  },
  { re: /^apps\/api\/plane\/settings\//, why: "secrets and security settings; new env vars are added by a person" },

  // Deploy, dependencies and environment.
  { re: /(^|\/)Dockerfile[^/]*$|(^|\/)\.dockerignore$|^docker-compose[^/]*\.ya?ml$/, why: "the production images" },
  { re: /^apps\/api\/bin\//, why: "container entrypoints: they run migrations on every deploy" },
  { re: /^apps\/proxy\//, why: "the public proxy in front of every app" },
  { re: /(^|\/)package\.json$|^pnpm-lock\.yaml$|^pnpm-workspace\.yaml$/, why: "dependencies: supply chain and build" },
  { re: /^apps\/api\/requirements(\/|\.txt$)/, why: "Python dependencies: supply chain" },
  { re: /(^|\/)\.env[^/]*$/, why: "environment configuration" },
];

/** Denied only under --strict: nobody reviews these in the lanes that merge alone. */
const MIGRATION = /^apps\/api\/plane\/db\/migrations\//;
const STRICT_DENY = [{ re: MIGRATION, why: "migrations run automatically on container start in production" }];

/**
 * The one migration the strict lanes may ship: a data repair for what a bug already left wrong
 * (a code fix only changes what happens next). It must go through data_repair() — savepoint, and a
 * failure is undone and filed as an incident instead of keeping the API from starting — and do
 * nothing a reviewer would have to think about: no schema, no SQL, no deletes, no other imports.
 */
const DATA_REPAIR_FILE = /^apps\/api\/plane\/db\/migrations\/\d{4}_[a-z0-9_]+\.py$/;
const DATA_REPAIR_MAX_LINES = 150;
const DATA_REPAIR_IMPORTS = new Set([
  "from django.db import migrations",
  "from plane.utils.agent_pipeline.data_repair import data_repair",
]);
const DATA_REPAIR_FORBIDDEN = [
  [/RunSQL|RawSQL|SeparateDatabaseAndState/, "raw SQL or state-only operations"],
  [/schema_editor\s*\./, "uses schema_editor"],
  [/\bconnection\b|\bcursor\b|\.execute\(|\.raw\(|\.extra\(/, "raw database access"],
  [/\.delete\(|_raw_delete|\.truncate/, "deletes rows (a repair corrects data, it never removes it)"],
  [/\b(exec|eval|compile|open|getattr|setattr|__import__)\s*\(|importlib|subprocess|\bos\./, "dynamic code or I/O"],
  [/atomic\s*=\s*False/, "turns off the migration transaction"],
];

function dataRepairProblems(file, added, testSources) {
  if (!DATA_REPAIR_FILE.test(file)) return ["not a new numbered migration file"];
  if (!added) return ["edits an existing migration (only a new one may be added)"];
  let src;
  try {
    src = execFileSync("git", ["show", `HEAD:${file}`], { encoding: "utf8" });
  } catch {
    return ["unreadable"];
  }
  const problems = [];
  const lines = src.split("\n");
  if (lines.length > DATA_REPAIR_MAX_LINES) problems.push(`${lines.length} lines (cap ${DATA_REPAIR_MAX_LINES})`);
  for (const line of lines.map((l) => l.trim()).filter((l) => /^(import|from)\s/.test(l))) {
    if (!DATA_REPAIR_IMPORTS.has(line)) problems.push(`import not allowed: ${line}`);
  }
  const ops = [...src.matchAll(/migrations\.(\w+)/g)].map((m) => m[1]);
  const others = [...new Set(ops.filter((op) => op !== "Migration" && op !== "RunPython"))];
  if (others.length) problems.push(`schema or other operations: ${others.join(", ")}`);
  if ((src.match(/migrations\.RunPython\(/g) ?? []).length !== 1) problems.push("needs exactly one RunPython");
  if (!/migrations\.RunPython\(\s*data_repair\(/.test(src)) problems.push("RunPython must wrap data_repair(...)");
  for (const [re, why] of DATA_REPAIR_FORBIDDEN) if (re.test(src)) problems.push(why);
  const module = file.split("/").pop().replace(/\.py$/, "");
  if (!testSources.some((s) => s.includes(module))) problems.push(`no test in the diff imports ${module}`);
  return problems;
}

const ANNOTATE = [
  { re: /^apps\/api\/plane\/db\/migrations\//, label: "Migration (runs on deploy)" },
  { re: /^apps\/api\/plane\/db\/models\//, label: "Schema change" },
  { re: /^apps\/api\/plane\/(bgtasks\/|celery\.py$)/, label: "Background tasks / schedules" },
  { re: /^apps\/api\/templates\/emails\//, label: "Outbound emails" },
  { re: /zil/i, label: "Zil Workspace integration" },
  { re: /^apps\/web\/app\/routes\//, label: "Route table" },
  { re: /^apps\/web\/core\/store\/root\.store\.ts$/, label: "Root store" },
  { re: /^packages\/(ui|propel)\//, label: "Shared design-system component" },
];

const FLAG_GATES = ["is_feature_enabled(", "useFeatureFlag("];

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

// execFileSync without a shell everywhere: file names come from the agent's diff.
function git(args) {
  return execFileSync("git", args, { encoding: "utf8" }).trim();
}

const base = arg("--base", "origin/preview");
const reportPath = arg("--report", null);
const strict = process.argv.includes("--strict");

let files = [];
let deletions = [];
let stat = "";
try {
  // --no-renames: a rename shows as delete + add, so the old (denied) path stays visible.
  // Three dots: against the fork point, so what preview gained meanwhile isn't counted as the agent's.
  files = git(["diff", "--no-renames", "--name-only", `${base}...HEAD`])
    .split("\n")
    .filter(Boolean);
  deletions = git(["diff", "--no-renames", "--diff-filter=D", "--name-only", `${base}...HEAD`])
    .split("\n")
    .filter(Boolean);
  stat = git(["diff", "--shortstat", `${base}...HEAD`]);
} catch (err) {
  console.error(`Could not read the diff against ${base}: ${err.message}`);
  process.exit(1);
}

if (files.length === 0) {
  console.log("The diff is empty: nothing to review.");
  if (reportPath) writeFileSync(reportPath, "## Blast-radius guard\n\nThe diff is empty.\n");
  process.exit(0);
}

let added = [];
try {
  added = git(["diff", "--no-renames", "--diff-filter=A", "--name-only", `${base}...HEAD`])
    .split("\n")
    .filter(Boolean);
} catch {
  added = [];
}
const testSources = files
  .filter((f) => /^apps\/api\/plane\/tests\/.+\.py$/.test(f) && !deletions.includes(f))
  .map((f) => {
    try {
      return execFileSync("git", ["show", `HEAD:${f}`], { encoding: "utf8" });
    } catch {
      return "";
    }
  });

const denyRules = strict ? [...DENY, ...STRICT_DENY] : DENY;
const violations = [];
const notes = [];
const migrations = files.filter((f) => MIGRATION.test(f));
for (const file of files) {
  const hit = denyRules.find((rule) => rule.re.test(file));
  if (!hit) continue;
  if (strict && MIGRATION.test(file)) {
    const problems = dataRepairProblems(file, added.includes(file), testSources);
    if (migrations.length > 1) problems.push(`${migrations.length} migrations in one diff (one repair at a time)`);
    if (!problems.length) {
      notes.push({ file, label: "Data repair migration (shape checked: data_repair, no schema/SQL/deletes)" });
      continue;
    }
    violations.push({ file, why: `${hit.why}; as a data repair: ${problems.join("; ")}` });
    continue;
  }
  violations.push({ file, why: hit.why });
}

for (const file of files) {
  if (violations.some((v) => v.file === file) || notes.some((n) => n.file === file)) continue;
  const rule = ANNOTATE.find((r) => r.re.test(file));
  if (rule) notes.push({ file, label: rule.label });
}

const countedFiles = files.filter((f) => !LOCALE_FILE.test(f)).length;
const changedLines = Number(stat.match(/(\d+) insertion/)?.[1] ?? 0) + Number(stat.match(/(\d+) deletion/)?.[1] ?? 0);
const sizeWarnings = [];
if (countedFiles > MAX_FILES) sizeWarnings.push(`${countedFiles} files touched (suggested cap ${MAX_FILES})`);
if (changedLines > MAX_LINES) sizeWarnings.push(`${changedLines} lines changed (suggested cap ${MAX_LINES})`);
if (deletions.length) sizeWarnings.push(`${deletions.length} file(s) deleted: ${deletions.join(", ")}`);

// Everything the feature agent builds must ship dark behind its flag.
const usesFlag = files.some((f) => {
  try {
    const diff = execFileSync("git", ["diff", `${base}...HEAD`, "--", f], { encoding: "utf8" });
    return diff
      .split("\n")
      .some((l) => l.startsWith("+") && !l.startsWith("+++") && FLAG_GATES.some((gate) => l.includes(gate)));
  } catch {
    return false;
  }
});

const lines = ["## Blast-radius guard", "", `**${files.length} file(s)**, ${stat || "no stats"}.`, ""];
if (violations.length) {
  lines.push("### ⛔ Denied files", "", "| File | Why it is blocked |", "|---|---|");
  for (const v of violations) lines.push(`| \`${v.file}\` | ${v.why} |`);
  lines.push("");
}
if (notes.length) {
  lines.push("### ⚠ Needs a human look", "", "| File | What it is |", "|---|---|");
  for (const n of notes) lines.push(`| \`${n.file}\` | ${n.label} |`);
  lines.push("");
}
if (sizeWarnings.length) lines.push("### ⚠ Size", "", ...sizeWarnings.map((w) => `- ${w}`), "");
if (!usesFlag) {
  lines.push(
    "### ⚠ No flag",
    "",
    "Neither `is_feature_enabled(` nor `useFeatureFlag(` appears in the added lines. Every agent-built feature must merge dark behind its flag.",
    ""
  );
}
if (!violations.length && !notes.length && !sizeWarnings.length && usesFlag) {
  lines.push("No sensitive files, within the size caps and behind its flag.", "");
}

// `::error::` only makes sense when Actions reads the log (the guard's tests run it as a subprocess).
const err = process.env.GITHUB_ACTIONS === "true" ? "::error::" : "";
const report = lines.join("\n");
console.log(report);
if (reportPath) writeFileSync(reportPath, report);

if (violations.length) {
  console.error(`\n${err}The diff touches ${violations.length} denied file(s). Stopping here.`);
  console.error(`${err}If the change is needed, a person makes it in a separate commit — the rule stays on the list.`);
  process.exit(1);
}

// With nobody reviewing, a deletion cuts: deleting tests is the cheapest way to empty a gate.
if (strict && deletions.length) {
  console.error(`\n${err}The diff deletes ${deletions.length} file(s): ${deletions.join(", ")}`);
  console.error(`${err}This lane merges without human review, so deletions stop here. If intended, it goes in a PR.`);
  process.exit(1);
}

process.exit(0);
