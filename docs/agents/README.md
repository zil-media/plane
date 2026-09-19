# Bug fixer and feature agent — setup

Ops users report problems and suggest improvements from the help menu (**Reportar un problema**,
**Sugerir una mejora**) and follow them in **Soporte** (`/<workspace>/support`). Browser crashes and
server 5xx are filed automatically. Two Claude Code Routines work the queues; GitHub Actions gates
and merges their branches. Same design as Zil Workspace (leads), ported to Django + Plane.

```
report ─► BugReport ─► fire_bug_routine ─► routine "Bug fixer Zil Ops" ─► /api/agent/bugs/*
       ─► push claude/** ─► agent-auto-merge.yml ─► urgent: preview + deploy │ batch: agent-batch
       ─► agent-batch-window.yml (15/21/02 UTC) ─► preview + deploy ─► resolved + email

suggestion ─► FeatureRequest ─► SPEC ─► spec ─► admin approves (or low impact auto-approves)
           ─► BUILD ─► feat/agent/<id> ─► feature-agent-pr.yml ─► PR │ agent-batch ─► merged (dark)
           ─► admin turns the flag on in Soporte
```

## 1. Routines (claude.ai/code/routines)

Create two routines on the `zil-media/plane` repository:

| Routine               | Instructions                                 |
| --------------------- | -------------------------------------------- |
| Bug fixer Zil Ops     | block in `OPS_BUG_AGENT_INSTRUCTIONS.md`     |
| Feature agent Zil Ops | block in `OPS_FEATURE_AGENT_INSTRUCTIONS.md` |

Enable an API trigger on each and keep its fire URL and token. The session must be able to push
branches but **not** workflow files (no `workflows` permission): that is what stops an agent branch
from rewriting the lanes that gate it.

## 2. Ops environment (api + worker + beat)

| Variable                                       | Value                                               |
| ---------------------------------------------- | --------------------------------------------------- |
| `OPS_BUG_AGENT_API_KEY`                        | `openssl rand -hex 32` — **not** an Anthropic token |
| `OPS_FEATURE_AGENT_API_KEY`                    | another `openssl rand -hex 32`                      |
| `AGENT_ADMIN_EMAIL`                            | an existing, active Ops user the agents act as      |
| `AGENT_API_BASE_URL`                           | `https://ops.zil.global`                            |
| `ANTHROPIC_OPS_BUG_ROUTINE_URL` / `_TOKEN`     | fire URL + token of the bug routine                 |
| `ANTHROPIC_OPS_FEATURE_ROUTINE_URL` / `_TOKEN` | fire URL + token of the feature routine             |
| `AGENT_CAPTURE_SERVER_ERRORS`                  | `1` (default) files 5xx as auto bug reports         |

Firing aborts if an agent key starts with `sk-ant-`: the key travels inside the routine transcript.

## 3. GitHub Actions secrets

| Secret                  | Value                               |
| ----------------------- | ----------------------------------- |
| `AGENT_API_KEY`         | same as `OPS_BUG_AGENT_API_KEY`     |
| `FEATURE_AGENT_API_KEY` | same as `OPS_FEATURE_AGENT_API_KEY` |
| `AGENT_API_URL`         | `https://ops.zil.global`            |

The lanes push to `preview` and `agent-batch` with `GITHUB_TOKEN`; if `preview` gets branch
protection, allow GitHub Actions to push. Pushes by `GITHUB_TOKEN` don't trigger workflows, so the
lanes start `build-and-push.yml` themselves (`.github/ci/agent-lane/trigger-deploy.sh`).

## 4. Switches (Soporte → Ajustes, instance admins)

- **Arreglo automático de problemas**: on by default once the env is set.
- **Agente de sugerencias**: ships **off**. Nothing is specced or built until an admin turns it on.
- **Construcciones por semana**: cap for BUILD sessions (default 3).

## 5. Where things live

| Piece                                                           | Path                                                                                |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Models + migration                                              | `apps/api/plane/db/models/agent.py`, `db/migrations/0124_agent_pipeline.py`         |
| Agent API (bearer keys)                                         | `apps/api/plane/agent_api/` → `/api/agent/bugs/*`, `/api/agent/features/*`          |
| In-app API (session)                                            | `apps/api/plane/app/views/support/` → `/api/support/*`                              |
| Routine triggers, queue rules, emails, 5xx capture              | `apps/api/plane/utils/agent_pipeline/`                                              |
| Celery (fire, 10-min claim sweep, 15-min feature sweep, emails) | `apps/api/plane/bgtasks/agent_pipeline_task.py`                                     |
| Widget, suggestion modal, Soporte board                         | `apps/web/core/components/support/`                                                 |
| Browser crash capture                                           | `apps/web/core/lib/support/`, hooked in `app/entry.client.tsx` and `app/root.tsx`   |
| Flag gate                                                       | backend `plane.utils.agent_pipeline.flags.is_feature_enabled`, web `useFeatureFlag` |
| CI lanes                                                        | `.github/workflows/agent-*.yml`, `feature-agent-pr.yml`, logic in `.github/ci/`     |
| Blast-radius guard                                              | `.github/ci/check-agent-diff.mjs`                                                   |

## 6. First run

1. Deploy, set the env and secrets, create an instance admin for triage.
2. Report a trivial bug from the widget; check the routine fired (worker logs: `bug routine: {'fired': True}`).
3. Watch the session claim it, the `Agent Auto-Merge` run gate it and the bug end `fixed` or `resolved`.
4. Run `Agent Batch Window` by hand (workflow_dispatch) to ship a batch without waiting.
