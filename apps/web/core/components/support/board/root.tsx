/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import { useSearchParams } from "next/navigation";
import { orderBy } from "lodash-es";
import useSWR from "swr";
import { AlertTriangle, Bug, ChevronRight, Lightbulb } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { Tabs } from "@plane/propel/tabs";
import { Loader } from "@plane/ui";
import { cn } from "@plane/utils";
import { SUPPORT_FEATURE_FLAGS_KEY } from "@/hooks/use-feature-flag";
import { useUser } from "@/hooks/store/user";
import { supportService } from "@/services/support.service";
import { openBugReporter, openFeatureSuggest } from "../events";
import { SupportAdminSettings } from "./admin-settings";
import { SupportBugDetail } from "./bug-detail";
import { SupportFeatureDetail } from "./feature-detail";
import type { TBoardItem } from "./item-row";
import { SupportItemRow } from "./item-row";
import type { TFeatureTab, TSection, TViewer } from "./phase";
import {
  COLLAPSIBLE_SECTIONS,
  FEATURE_TABS,
  SECTION_ORDER,
  bugSection,
  featureInTab,
  featureSection,
  isMyFeature,
  onMyBoard,
} from "./phase";

type TTab = "tracking" | TFeatureTab | "reports" | "settings";
type TSelection = { kind: "bug" | "feature"; id: string } | null;

const REFRESH_MS = 20_000;
const ADMIN_BUG_FILTERS = ["open", "in_progress", "fixed", "blocked", "all"] as const;
type TAdminBugFilter = (typeof ADMIN_BUG_FILTERS)[number];

/** A grouped row: `count > 1` is the same request loaded again. */
type TGroup = { entry: TBoardItem; count: number };

function newestFirst(items: TBoardItem[]) {
  return orderBy(items, [(entry) => entry.item.created_at], ["desc"]);
}

/**
 * Dedupe key: the SAME request loaded twice. It compares what the person wrote, never the title the
 * classifier generated — two different reports titled alike are two reports. Status is part of the
 * key: two copies in different states don't tell the same story. Fails cheap: reworded duplicates
 * stay as two rows (noise) instead of hiding a request that exists (lost data).
 */
const norm = (text: string) => text.trim().toLowerCase().replace(/\s+/g, " ");

function dedupeKey(entry: TBoardItem): string {
  return entry.kind === "bug"
    ? `bug:${entry.item.status}:${norm(entry.item.description)}`
    : `feature:${entry.item.requested_by?.id ?? ""}:${entry.item.status}:${norm(entry.item.title)}`;
}

export const SupportBoard = observer(function SupportBoard() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const { data: currentUser } = useUser();
  const [tab, setTab] = useState<TTab>("tracking");
  const [adminFilter, setAdminFilter] = useState<TAdminBugFilter>("open");
  // History sections ("done", "stalled") stay folded until opened.
  const [openSections, setOpenSections] = useState<Partial<Record<TSection, boolean>>>({});
  const [selection, setSelection] = useState<TSelection>(() => {
    const bugId = searchParams?.get("bug");
    const featureId = searchParams?.get("feature");
    if (bugId) return { kind: "bug", id: bugId };
    return featureId ? { kind: "feature", id: featureId } : null;
  });

  const { data: me, mutate: mutateMe } = useSWR("SUPPORT_ME", () => supportService.me());
  const { data: myBugs, mutate: mutateMyBugs } = useSWR("SUPPORT_MY_BUGS", () => supportService.myBugReports(), {
    refreshInterval: REFRESH_MS,
  });
  const { data: features, mutate: mutateFeatures } = useSWR(
    "SUPPORT_FEATURES",
    () => supportService.featureRequests({ scope: "all" }),
    { refreshInterval: REFRESH_MS }
  );
  const { data: flags } = useSWR(SUPPORT_FEATURE_FLAGS_KEY, () => supportService.enabledFlags());
  const isAdmin = !!me?.is_admin;
  const { data: adminBugs, mutate: mutateAdminBugs } = useSWR(
    isAdmin && tab === "reports" ? `SUPPORT_ADMIN_BUGS:${adminFilter}` : null,
    () =>
      supportService.allBugReports(
        adminFilter === "blocked" ? { blocked: true } : adminFilter === "all" ? {} : { status: adminFilter }
      ),
    { refreshInterval: REFRESH_MS }
  );

  const refreshAll = () => {
    void mutateMyBugs();
    void mutateFeatures();
    void mutateAdminBugs();
  };

  const viewer = useMemo<TViewer>(() => ({ isAdmin, userId: currentUser?.id }), [isAdmin, currentUser?.id]);

  const trackingSections = useMemo(() => {
    const rows: TBoardItem[] = orderBy(
      [
        ...(myBugs ?? []).map((item) => ({ kind: "bug" as const, item })),
        ...(features ?? [])
          .filter((item) => onMyBoard(item, viewer))
          .map((item) => ({ kind: "feature" as const, item })),
      ],
      [
        // Mine first: it is what the person came to look at.
        (entry) => entry.kind === "bug" || isMyFeature(entry.item, viewer),
        (entry) =>
          entry.kind === "feature" ? entry.item.updated_at : (entry.item.last_seen_at ?? entry.item.created_at),
      ],
      ["desc", "desc"]
    );
    const groups = new Map<TSection, TGroup[]>();
    const seen = new Map<string, TGroup>();
    for (const entry of rows) {
      const section = entry.kind === "bug" ? bugSection(entry.item) : featureSection(entry.item, viewer);
      const key = `${section}|${dedupeKey(entry)}`;
      const dupe = seen.get(key);
      if (dupe) {
        dupe.count += 1;
        continue;
      }
      const group = { entry, count: 1 };
      seen.set(key, group);
      groups.set(section, [...(groups.get(section) ?? []), group]);
    }
    return SECTION_ORDER.flatMap((section) => {
      const items = groups.get(section);
      return items ? [[section, items] as const] : [];
    });
  }, [myBugs, features, viewer]);

  const featureItems = useMemo<TBoardItem[]>(
    () =>
      tab === "tracking" || tab === "reports" || tab === "settings"
        ? []
        : (features ?? [])
            .filter((item) => featureInTab(item, tab))
            .map((item) => ({ kind: "feature" as const, item })),
    [features, tab]
  );
  const reportItems = useMemo<TBoardItem[]>(
    () => newestFirst((adminBugs ?? []).map((item) => ({ kind: "bug" as const, item }))),
    [adminBugs]
  );
  const awaitingAuthorization = isAdmin ? (features ?? []).filter((item) => item.status === "spec_ready").length : 0;

  const renderRows = (groups: TGroup[]) =>
    groups.map(({ entry, count }) => (
      <SupportItemRow
        key={`${entry.kind}-${entry.item.id}`}
        entry={entry}
        viewer={viewer}
        count={count}
        selected={selection?.id === entry.item.id}
        onSelect={() => setSelection({ kind: entry.kind, id: entry.item.id })}
      />
    ));
  const renderList = (items: TBoardItem[]) => (
    <div className="flex flex-col divide-y divide-subtle overflow-hidden rounded-md border border-subtle">
      {renderRows(items.map((entry) => ({ entry, count: 1 })))}
    </div>
  );

  const renderSection = (section: TSection, groups: TGroup[]) => {
    const total = groups.reduce((sum, group) => sum + group.count, 0);
    const collapsible = COLLAPSIBLE_SECTIONS.includes(section);
    const isOpen = !collapsible || !!openSections[section];
    const urgent = section === "needs_you";
    return (
      <section key={section} className="flex flex-col gap-2">
        {collapsible ? (
          <button
            type="button"
            aria-expanded={isOpen}
            onClick={() => setOpenSections((current) => ({ ...current, [section]: !current[section] }))}
            className="flex items-center gap-1.5 self-start text-caption-sm-regular text-tertiary hover:text-primary"
          >
            <ChevronRight className={cn("size-3 transition-transform", isOpen && "rotate-90")} />
            {t(`helpdesk.section.${section}`)} · {t("helpdesk.board.requests", { count: total })}
          </button>
        ) : (
          <h4 className={cn("text-caption-sm-medium", urgent ? "text-warning-primary" : "text-tertiary")}>
            {t(`helpdesk.section.${section}`)} · {total}
          </h4>
        )}
        {isOpen && (
          <div
            className={cn(
              "flex flex-col divide-y divide-subtle overflow-hidden rounded-md border",
              urgent ? "border-warning-strong" : "border-subtle"
            )}
          >
            {renderRows(groups)}
          </div>
        )}
      </section>
    );
  };

  const loading = !myBugs || !features;

  return (
    <div className="flex h-full w-full flex-col md:flex-row">
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-subtle px-4 py-3">
          <p className="text-body-xs-regular text-tertiary">{t("helpdesk.board.intro")}</p>
          <div className="flex gap-2">
            <Button variant="secondary" size="lg" prependIcon={<Bug />} onClick={openBugReporter}>
              {t("helpdesk.menu.report_problem")}
            </Button>
            <Button variant="secondary" size="lg" prependIcon={<Lightbulb />} onClick={openFeatureSuggest}>
              {t("helpdesk.menu.suggest_improvement")}
            </Button>
          </div>
        </div>

        <Tabs value={tab} onValueChange={(value) => setTab(value as TTab)} className="px-4 pt-3">
          <Tabs.List>
            <Tabs.Trigger value="tracking">{t("helpdesk.board.tab_tracking")}</Tabs.Trigger>
            {FEATURE_TABS.map((featureTab) => (
              <Tabs.Trigger key={featureTab} value={featureTab}>
                {t(`helpdesk.board.tab_${featureTab}`)}
              </Tabs.Trigger>
            ))}
            {isAdmin && <Tabs.Trigger value="reports">{t("helpdesk.board.tab_reports")}</Tabs.Trigger>}
            {isAdmin && <Tabs.Trigger value="settings">{t("helpdesk.board.tab_settings")}</Tabs.Trigger>}
            <Tabs.Indicator />
          </Tabs.List>
        </Tabs>

        <div className="flex flex-col gap-6 p-4">
          {awaitingAuthorization > 0 && tab !== "settings" && (
            <div className="flex items-center gap-3 rounded-md border border-warning-strong bg-warning-subtle px-4 py-3 text-body-xs-regular text-primary">
              <AlertTriangle className="size-4 shrink-0 text-warning-primary" />
              {t("helpdesk.board.awaiting_authorization", { count: awaitingAuthorization })}
            </div>
          )}
          {loading ? (
            <Loader className="space-y-2">
              <Loader.Item height="40px" />
              <Loader.Item height="40px" />
              <Loader.Item height="40px" />
            </Loader>
          ) : tab === "tracking" ? (
            trackingSections.length === 0 ? (
              <p className="py-10 text-center text-body-xs-regular text-tertiary">{t("helpdesk.board.empty")}</p>
            ) : (
              trackingSections.map(([section, groups]) => renderSection(section, groups))
            )
          ) : tab !== "reports" && tab !== "settings" ? (
            featureItems.length === 0 ? (
              <p className="py-10 text-center text-body-xs-regular text-tertiary">{t("helpdesk.board.empty_tab")}</p>
            ) : (
              renderList(featureItems)
            )
          ) : tab === "reports" ? (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-1.5">
                {ADMIN_BUG_FILTERS.map((filter) => (
                  <button
                    key={filter}
                    type="button"
                    onClick={() => setAdminFilter(filter)}
                    className={cn(
                      "rounded-full border px-2.5 py-0.5 text-caption-sm-regular",
                      adminFilter === filter
                        ? "border-accent-strong bg-accent-subtle text-accent-primary"
                        : "border-subtle text-secondary hover:bg-layer-1"
                    )}
                  >
                    {t(`helpdesk.filter.${filter}`)}
                  </button>
                ))}
              </div>
              {reportItems.length > 0 && renderList(reportItems)}
            </div>
          ) : (
            me && (
              <SupportAdminSettings
                me={me}
                onChanged={() => {
                  void mutateMe();
                }}
              />
            )
          )}
        </div>
      </div>

      {selection && tab !== "settings" && (
        <aside className="w-full shrink-0 overflow-y-auto border-t border-subtle md:w-[440px] md:border-t-0 md:border-l">
          {selection.kind === "bug" ? (
            <SupportBugDetail
              key={selection.id}
              bugId={selection.id}
              isAdmin={isAdmin}
              currentUserId={currentUser?.id}
              onChanged={refreshAll}
              onOpenFeature={(id) => setSelection({ kind: "feature", id })}
            />
          ) : (
            <SupportFeatureDetail
              key={selection.id}
              featureId={selection.id}
              isAdmin={isAdmin}
              currentUserId={currentUser?.id}
              enabledFlags={flags?.enabled ?? []}
              onChanged={refreshAll}
            />
          )}
        </aside>
      )}
    </div>
  );
});
