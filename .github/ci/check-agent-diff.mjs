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
const STRICT_DENY = [
  { re: /^apps\/api\/plane\/db\/migrations\//, why: "migrations run automatically on container start in production" },
];

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

const denyRules = strict ? [...DENY, ...STRICT_DENY] : DENY;
const violations = [];
for (const file of files) {
  const hit = denyRules.find((rule) => rule.re.test(file));
  if (hit) violations.push({ file, why: hit.why });
}

const notes = [];
for (const file of files) {
  if (violations.some((v) => v.file === file)) continue;
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
