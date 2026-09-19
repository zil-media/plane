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
import { Bug, Lightbulb } from "lucide-react";
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
import { SupportItemRow, itemPhase } from "./item-row";
import type { TSection } from "./phase";
import { SECTION_ORDER } from "./phase";

type TTab = "tracking" | "suggestions" | "reports" | "settings";
type TSelection = { kind: "bug" | "feature"; id: string } | null;

const REFRESH_MS = 20_000;
const ADMIN_BUG_FILTERS = ["open", "in_progress", "fixed", "blocked", "all"] as const;
type TAdminBugFilter = (typeof ADMIN_BUG_FILTERS)[number];

function newestFirst(items: TBoardItem[]) {
  return orderBy(items, [(entry) => entry.item.created_at], ["desc"]);
}

export const SupportBoard = observer(function SupportBoard() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const { data: currentUser } = useUser();
  const [tab, setTab] = useState<TTab>("tracking");
  const [adminFilter, setAdminFilter] = useState<TAdminBugFilter>("open");
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

  const trackingSections = useMemo(() => {
    const mine: TBoardItem[] = newestFirst([
      ...(myBugs ?? []).map((item) => ({ kind: "bug" as const, item })),
      ...(features ?? [])
        .filter((item) => item.requested_by?.id === currentUser?.id)
        .map((item) => ({ kind: "feature" as const, item })),
    ]);
    const groups = new Map<TSection, TBoardItem[]>();
    for (const entry of mine) {
      const section = itemPhase(entry).section;
      groups.set(section, [...(groups.get(section) ?? []), entry]);
    }
    return SECTION_ORDER.flatMap((section) => {
      const items = groups.get(section);
      return items ? [[section, items] as const] : [];
    });
  }, [myBugs, features, currentUser?.id]);

  const suggestionItems = useMemo<TBoardItem[]>(
    () => (features ?? []).map((item) => ({ kind: "feature" as const, item })),
    [features]
  );
  const reportItems = useMemo<TBoardItem[]>(
    () => newestFirst((adminBugs ?? []).map((item) => ({ kind: "bug" as const, item }))),
    [adminBugs]
  );

  const renderRows = (items: TBoardItem[], showAuthor = false) =>
    items.map((entry) => (
      <SupportItemRow
        key={`${entry.kind}-${entry.item.id}`}
        entry={entry}
        showAuthor={showAuthor}
        selected={selection?.id === entry.item.id}
        onSelect={() => setSelection({ kind: entry.kind, id: entry.item.id })}
      />
    ));

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
            <Tabs.Trigger value="suggestions">{t("helpdesk.board.tab_suggestions")}</Tabs.Trigger>
            {isAdmin && <Tabs.Trigger value="reports">{t("helpdesk.board.tab_reports")}</Tabs.Trigger>}
            {isAdmin && <Tabs.Trigger value="settings">{t("helpdesk.board.tab_settings")}</Tabs.Trigger>}
            <Tabs.Indicator />
          </Tabs.List>
        </Tabs>

        <div className="flex flex-col gap-4 p-4">
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
              trackingSections.map(([section, items]) => (
                <section key={section} className="flex flex-col gap-1">
                  <h4 className="px-3 text-caption-sm-medium text-tertiary">{t(`helpdesk.section.${section}`)}</h4>
                  {renderRows(items)}
                </section>
              ))
            )
          ) : tab === "suggestions" ? (
            <div className="flex flex-col gap-1">{renderRows(suggestionItems, true)}</div>
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
              <div className="flex flex-col gap-1">{renderRows(reportItems, true)}</div>
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
