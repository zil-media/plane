# Zil Ops Rebrand Playbook

This repo is an **upstream fork of Plane**, rebranded to **Zil Ops** for internal use.
When you pull/merge upstream Plane updates, upstream code will reintroduce Plane branding.
**Read this file and re-apply the rules below** so the rebrand stays consistent.

> TL;DR for an AI merging upstream: replace user-facing **"Plane" → "Zil Ops"**, keep the
> logo/palette/favicon overrides listed here, strip Plane marketing CTAs, and **never** touch
> copyright headers, `@plane/*` imports, or the `Plane*` component identifiers.

---

## 1. Brand identity

| Thing | Value |
|---|---|
| Product name (user-facing) | **Zil Ops** |
| Short name (PWA `short_name`, `application-name`) | **Zil** |
| Logo wordmark | **ZIL** (blocky wordmark, from leads `public/logo.svg`) |
| Isotype | Zil chevron mark (from leads `public/logotipo.svg`) |
| Brand blue | **`#6D86FF`** — OKLCH `oklch(0.6601 0.1804 272)` (leads `--color-primary-blue`) |
| Brand red (error/destructive accent) | `#FF8682` |
| Favicon | black tile + white **zil** wordmark (matches leads `public/favicon.png`) |
| Palette source of truth | leads `docs/guide/TOKEN_REFERENCE.md` + `src/index.css` (dark-first) |

Zil's palette is **dark-mode first**. Only the accent + Plane's **dark** neutrals were remapped;
Plane's **light** neutrals stay (Zil has no light variant).

---

## 2. Naming rules for text replacement

**Replace** (user-facing copy only): any literal `Plane` used as the product name in JSX/TSX
strings, headings, descriptions, tooltips, aria-labels, placeholders, button text, page
`<title>`/meta, and **every locale JSON value** → `Zil Ops`.

**Never touch:**
- Copyright / license headers: `Copyright (c) 2023-present Plane Software, Inc.` + SPDX lines.
- Code identifiers & imports: `@plane/*` packages, component names `PlaneLogo` / `PlaneLockup` /
  `PlaneWordmark` (already point to Zil artwork), file paths, CSS classes, var/function names,
  `data-*`, analytics/event names, GraphQL fields.
- `package.json` names, docker/deploy config, `og:url`/`twitter` handles that are just URLs.

### Locale JSON sweep (`packages/i18n/src/locales/**/*.json`)
No JSON **key** contains `Plane`, so replace in values with a word boundary:

```bash
find packages/i18n/src/locales -name "*.json" -print0 | xargs -0 perl -i -pe 's/\bPlane\b/Zil Ops/g'
```

**Language gotchas — do NOT blanket-replace these (they are real words, not the brand):**
- `es`: `Planes` = "plans", keep. | `pt-BR`: `Planejado`/`Planeje` = "planned"/"plan", keep.
- `de`: `Planen Sie …` = verb "to plan", **keep**. BUT `Planes <noun>` / `Planes KI` is the
  **genitive of the brand** ("Plane's") → replace with `Zil Ops` (e.g. `Planes KI → Zil Ops KI`).

Always validate JSON parses afterwards, and confirm `\bPlane\b` count is 0 (minus the real words above).

---

## 3. Files owned by the rebrand (re-apply if upstream overwrites them)

### Logo / brand components (`packages/propel/src/icons/brand/`)
- `plane-logo.tsx` → Zil isotype (viewBox `0 0 60 37`).
- `plane-wordmark.tsx` → ZIL wordmark (viewBox `0 0 57 32`).
- `plane-lockup.tsx` → ZIL wordmark, `preserveAspectRatio="xMinYMid meet"` (left-aligned).
  All keep `fill={color}` / `currentColor` so they follow theme (`text-primary`).

### Loader
- `apps/web/core/components/common/logo-spinner.tsx` → faithful port of leads `ZilLogoLoader`
  (two isotype halves slide in + join, outline→fill crossfade, pulse + blue ripple). Mark is
  `currentColor` (mono, theme-aware); ripple accent is `#6D86FF`. **Not** the old gif spinner.

### Metadata / titles
- `packages/constants/src/metadata.ts` — `SITE_NAME`, `SITE_TITLE`, `SITE_DESCRIPTION`, etc.
- `apps/web/app/root.tsx` and `apps/web/app/layout.tsx` — `APP_TITLE`, `application-name`,
  og/twitter tags. (Removed the `@planepowers` twitter:site handle.)

### Manifests → name/short_name/description/theme_color(`#000000`)/icons
- `apps/web/manifest.json`, `apps/web/public/manifest.json`,
  `apps/web/public/site.webmanifest.json`, `apps/web/public/favicon/site.webmanifest`.

### Palette (`packages/tailwind-config/variables.css`)
- **Accent `--brand-*` ramp** (both `:root` light and `@variant dark`): re-hued to Zil `272°`.
  `--brand-default` = `oklch(0.6601 0.1804 272)` (= `#6D86FF`) in **both** themes.
  Light hover/active (`--brand-900/1000`) lifted so buttons start from the bright blue.
- **Dark neutrals** (`@variant dark` `--neutral-*`) remapped to Zil near-black ramp:
  `#0A0A0A` base → `#111113` card → `#161618` elevated → `#1A1A1E` border → `#2A2C32` strong border
  → greys → `#F2F3F4` text. Lightness order preserved (contrast safe).
- Light-theme neutrals and semantic states (green/amber/red) left as Plane's on purpose.

### Favicons / icons / og-image (regenerate, don't hand-edit)
Script: `docs/zil-branding/gen-icons.mjs` (needs `sharp`; run from a dir that has it, e.g. leads).
Overwrites: `apps/web/app/assets/favicon/{favicon-16x16,favicon-32x32,apple-touch-icon}.png`,
`favicon.ico`, `apps/web/app/assets/icons/icon-{180x180,512x512}.png`, `apps/web/app/assets/og-image.png`,
`apps/web/public/icons/icon-{192,348,512}*.png`, `apps/web/public/favicon/android-chrome-{192,512}*.png`.

---

## 4. Marketing / promo to strip on every upstream merge

Upstream re-adds Plane promo. Remove/neutralize (don't point users at Plane properties):
- **"Star us on GitHub"** CTA — removed from `apps/web/ce/components/navigations/top-navigation-root.tsx`
  (component `star-us-link.tsx`; also referenced in `power-k/config/help-commands.ts`,
  `app/(all)/workspace-invitations/page.tsx`).
- Product-updates / changelog panels pulling Plane release notes.
- Links to `plane.so`, `github.com/makeplane/plane`, `@planepowers`, `support@plane.so`.
- "Powered by Plane" / "Plane Pro" / "Plane Cloud" upgrade promos.

---

## 5. Running locally (port 3005)

Workspace packages compile to `dist/` on demand — running only `apps/web` fails with
`Failed to resolve entry for package "@plane/constants"`. Run web **with its deps** via turbo:

```bash
# apps/web/.env must exist (copy from .env.example)
pnpm exec turbo run dev --filter=web... --concurrency=16
```

`apps/web/package.json` `dev` script port is set to **3005**. `setup.sh` only copies `.env` files
and installs — it does **not** build packages; turbo's watch does.

The frontend renders login/loaders/favicon without the backend, but real navigation needs the
API (`:8000`) + Postgres/Redis via `docker-compose-local.yml`. With the backend down you'll see the
maintenance screen (already themed).

---

## 6. Post-merge checklist

1. `grep -rn '\bPlane\b' apps/web --include=*.tsx --include=*.ts | grep -v Copyright | grep -v '@plane' | grep -vE 'Plane(Logo|Lockup|Wordmark)'` → fix user-facing hits.
2. Run the locale sweep (§2) + validate JSON, mind the language gotchas.
3. Diff the §3 files against this list; re-apply any that upstream reverted.
4. Strip §4 marketing.
5. Regenerate favicons if the brand assets changed (§3).
6. Boot on 3005 (§5), confirm title = "Zil Ops …", favicon = black/white ZIL, accent = `#6D86FF`.

---

## 7. Applied-changes inventory (initial rebrand)

Record of the first full pass, so you can diff against it after an upstream merge.

### Product-name copy → "Zil Ops"
- `ce/components/onboarding/tour/root.tsx` (welcome + "concepts in Plane"), `tour/sidebar.tsx`
- `core/components/onboarding/invite-members.tsx`, `core/components/auth-screens/footer.tsx`
- `core/components/integration/single-integration-card.tsx` (GitHub/Slack "your Plane workspace")
- `core/components/license/modal/card/base-paid-plan-card.tsx`
- `core/components/workspace/billing/comparison/plans.tsx` (~16 feature blurbs; "Plane Query Language" → "Zil Ops Query Language"; kept `TPlanePlans`/`PLANE_PLANS` identifiers)
- System-actor labels (product shown as actor): `common/activity/helper.tsx`, `common/activity/user.tsx`,
  `issues/issue-detail/**/archived-at.tsx`, `issues/peek-overview/properties.tsx`,
  `ce/components/issues/issue-details/issue-creator.tsx`, `profile/activity/activity-list.tsx`,
  `inbox/sidebar/inbox-list-item.tsx`, `intake/page.tsx` (title fallback)
- alt text: `core/layouts/auth-layout/workspace-wrapper.tsx`, `core/components/common/latest-feature-block.tsx`
- `ce/components/pages/editor/embed/issue-embed-upgrade-card.tsx` ("Plane Pro" → "Zil Ops Pro")
- Titles/meta upgraded from short "Zil" → "Zil Ops": `app/root.tsx`, `app/layout.tsx`
  (short-form `application-name`/`apple-mobile-web-app-title` kept as "Zil")

### Marketing/promo removed or neutralized
- `app/(all)/workspace-invitations/page.tsx` — removed "Star us on GitHub" + "Join our community"
- `ce/components/navigations/top-navigation-root.tsx` — removed `<StarUsOnGitHubLink/>`
- `core/components/global/product-updates/footer.tsx` — removed "Powered by Plane Pages"
- `core/components/common/latest-feature-block.tsx` — removed plane.so/changelog "Learn more"
- `app/(all)/[workspaceSlug]/(settings)/settings/projects/page.tsx` — removed plane.so "Learn more"
- `app/error/prod.tsx` — removed "@planepowers" (x.com) link
- `plans.tsx` + `issue-embed-upgrade-card.tsx` — plane.so hrefs neutralized to `#`
- (unused imports pruned in all of the above)

### i18n — all 19 locales
`packages/i18n/src/locales/*/*.json`: `\bPlane\b` → `Zil Ops` (100+ per locale), plus de genitive fix.

### Infra links to plane.so — REMOVED (menu items hidden)
Per decision, functional links pointing at Plane properties (docs / support / forum / discord /
changelog / report-bug / talk-to-sales) were **removed** from the UI:
- `core/components/workspace/sidebar/help-section/root.tsx` — help menu items
- `core/components/power-k/config/help-commands.ts` — help commands
- `core/components/global/product-updates/footer.tsx` — **file deleted** (was "Powered by Plane Pages");
  export dropped from `product-updates/index.ts`, usage removed from `product-updates/modal.tsx`
- `core/components/global/product-updates/fallback.tsx` — changelog link
- `core/components/estimates/root.tsx` — docs "learn more"

**Kept:** legal Terms & Conditions / Privacy URLs (`account/terms-and-conditions.tsx`). Backend
match keys like `.includes("intake@plane.so")` are logic, not display — left. When internal Zil
docs/support URLs exist, re-add these menu items pointing at them.
