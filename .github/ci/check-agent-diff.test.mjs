// Tests for check-agent-diff.mjs: each case builds a throwaway repo (origin/preview + an agent
// commit) and runs the guard on it as a subprocess, the way the lanes do.
// Run: node --test .github/ci/check-agent-diff.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const GUARD = join(dirname(fileURLToPath(import.meta.url)), "check-agent-diff.mjs");
const MIG_DIR = "apps/api/plane/db/migrations";
const EXISTING = `${MIG_DIR}/0133_existing.py`;
const NEW = `${MIG_DIR}/0134_repair_folder_access.py`;
const TEST = "apps/api/plane/tests/unit/test_repair_folder_access.py";

const REPAIR = `from django.db import migrations
from plane.utils.agent_pipeline.data_repair import data_repair


def repair(apps):
    Page = apps.get_model("db", "Page")
    return Page.objects.filter(access=0, parent__access=1).update(access=1)


class Migration(migrations.Migration):
    dependencies = [("db", "0133_existing")]
    operations = [migrations.RunPython(data_repair("repair_folder_access", repair), migrations.RunPython.noop)]
`;
const REPAIR_TEST = `import importlib

repair = importlib.import_module("plane.db.migrations.0134_repair_folder_access").repair
`;

function repo(agentFiles, { base = {} } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "guard-"));
  const git = (...args) => execFileSync("git", args, { cwd: dir, encoding: "utf8" });
  const write = (files) => {
    for (const [path, content] of Object.entries(files)) {
      mkdirSync(join(dir, dirname(path)), { recursive: true });
      writeFileSync(join(dir, path), content);
    }
  };
  git("init", "-q", "-b", "preview");
  git("config", "user.email", "t@t");
  git("config", "user.name", "t");
  write({ "README.md": "x\n", [EXISTING]: "# old\n", ...base });
  git("add", "-A");
  git("commit", "-qm", "base");
  git("update-ref", "refs/remotes/origin/preview", "HEAD");
  write(agentFiles);
  git("add", "-A");
  git("commit", "-qm", "fix: something");
  return dir;
}

function guard(dir, strict = true) {
  const args = [GUARD, "--base", "origin/preview", ...(strict ? ["--strict"] : [])];
  const r = spawnSync("node", args, { cwd: dir, encoding: "utf8", env: { ...process.env, GITHUB_ACTIONS: "" } });
  rmSync(dir, { recursive: true, force: true });
  return { code: r.status, out: r.stdout + r.stderr };
}

test("a data repair with its test passes the strict lane", () => {
  const r = guard(repo({ [NEW]: REPAIR, [TEST]: REPAIR_TEST }));
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /Data repair migration/);
});

test("a data repair without a test is cut", () => {
  const r = guard(repo({ [NEW]: REPAIR }));
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /no test in the diff/);
});

test("a schema operation is cut", () => {
  const src = REPAIR.replace("operations = [", 'operations = [migrations.AddField("page", "x", None), ');
  const r = guard(repo({ [NEW]: src, [TEST]: REPAIR_TEST }));
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /AddField/);
});

test("deleting rows is cut", () => {
  const src = REPAIR.replace(".update(access=1)", ".delete()");
  const r = guard(repo({ [NEW]: src, [TEST]: REPAIR_TEST }));
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /deletes rows/);
});

test("raw SQL is cut", () => {
  const src = REPAIR.replace("Page = apps", 'Page = migrations.RunSQL("DROP TABLE x")\n    Page = apps');
  const r = guard(repo({ [NEW]: src, [TEST]: REPAIR_TEST }));
  assert.equal(r.code, 1, r.out);
});

test("a RunPython that skips data_repair is cut", () => {
  const src = REPAIR.replace('data_repair("repair_folder_access", repair)', "lambda a, s: repair(a)");
  const r = guard(repo({ [NEW]: src, [TEST]: REPAIR_TEST }));
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /must wrap data_repair/);
});

test("any other import is cut", () => {
  const src = "from django.db import connection\n" + REPAIR;
  const r = guard(repo({ [NEW]: src, [TEST]: REPAIR_TEST }));
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /import not allowed/);
});

test("editing an existing migration is cut", () => {
  const r = guard(
    repo({ [EXISTING]: REPAIR, [TEST]: REPAIR_TEST.replace("0134_repair_folder_access", "0133_existing") })
  );
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /edits an existing migration/);
});

test("two migrations in one diff are cut", () => {
  const second = `${MIG_DIR}/0135_repair_other.py`;
  const tests = REPAIR_TEST + "# 0135_repair_other\n";
  const r = guard(repo({ [NEW]: REPAIR, [second]: REPAIR, [TEST]: tests }));
  assert.equal(r.code, 1, r.out);
  assert.match(r.out, /2 migrations in one diff/);
});

test("the review lane (not strict) still only annotates schema migrations", () => {
  const src = REPAIR.replace("operations = [", 'operations = [migrations.AddField("page", "x", None), ');
  const r = guard(repo({ [NEW]: src }), false);
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /Migration \(runs on deploy\)/);
});

test("the rest of the denylist is untouched", () => {
  const r = guard(repo({ "apps/api/plane/settings/common.py": "X = 1\n" }));
  assert.equal(r.code, 1, r.out);
});
