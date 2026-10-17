/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { ExternalLink } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { Tabs } from "@plane/propel/tabs";
import type { TZilClientProfile } from "@plane/types";
import { Spinner } from "@plane/ui";
// services
import { ProjectPageService } from "@/services/page";
// store
import type { TPageInstance } from "@/store/pages/base-page";
// local imports
import { ZilClientAssets } from "./zil-client-assets";
import { ZilClientCalls } from "./zil-client-calls";
import { ZilClientInfo } from "./zil-client-info";

const projectPageService = new ProjectPageService();

type TTab = "info" | "assets" | "calls" | "pages";

type TProfileState =
  | { status: "loading" }
  | { status: "ready"; profile: TZilClientProfile }
  | { status: "forbidden" }
  | { status: "missing" }
  | { status: "unavailable" };

const PROFILE_ERROR_KEYS = {
  forbidden: "page_tree.zil_client.profile.forbidden",
  // the client was removed or moved to another unit in Zil: the link stays, flagged "missing"
  missing: "page_tree.zil_client.missing",
  unavailable: "page_tree.zil_client.profile.unavailable",
} as const;

type Props = {
  page: TPageInstance;
  pagesCount: number;
  pages: ReactNode;
};

/** A client folder: the client's profile, assets and calls (live from Zil) next to its pages. */
export const ZilClientPanel = observer(function ZilClientPanel(props: Props) {
  const { page, pagesCount, pages } = props;
  // states
  const [tab, setTab] = useState<TTab>("info");
  const [state, setState] = useState<TProfileState>({ status: "loading" });
  // hooks
  const { t } = useTranslation();
  const { workspaceSlug: workspaceSlugParam } = useParams();
  // derived values
  const workspaceSlug = workspaceSlugParam?.toString();
  const projectId = page.project_ids?.[0];
  const pageId = page.id;
  const clientId = page.zil_client?.id;

  const load = useCallback(
    (signal?: { cancelled: boolean }) => {
      if (!workspaceSlug || !projectId || !pageId) return;
      setState({ status: "loading" });
      projectPageService
        .getZilClientProfile(workspaceSlug, projectId, pageId)
        .then((profile) => {
          if (!signal?.cancelled) setState({ status: "ready", profile });
          return undefined;
        })
        .catch((error: { status?: number } | undefined) => {
          if (signal?.cancelled) return;
          if (error?.status === 403) setState({ status: "forbidden" });
          else if (error?.status === 404) setState({ status: "missing" });
          else setState({ status: "unavailable" });
        });
    },
    [workspaceSlug, projectId, pageId]
  );

  useEffect(() => {
    const signal = { cancelled: false };
    load(signal);
    return () => {
      signal.cancelled = true;
    };
  }, [load, clientId]);

  const updateProfile = useCallback(
    (update: (profile: TZilClientProfile) => TZilClientProfile) =>
      setState((current) =>
        current.status === "ready" ? { status: "ready", profile: update(current.profile) } : current
      ),
    []
  );

  const renderProfileTab = (render: (profile: TZilClientProfile) => ReactNode) => {
    if (state.status === "loading")
      return (
        <div className="grid h-32 place-items-center">
          <Spinner height="20px" width="20px" />
        </div>
      );
    if (state.status !== "ready")
      return (
        <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-subtle py-12 text-center">
          <p className="text-13 text-secondary">{t(PROFILE_ERROR_KEYS[state.status])}</p>
          {state.status === "unavailable" && (
            <Button variant="secondary" size="lg" onClick={() => load()}>
              {t("page_tree.zil_client.profile.retry")}
            </Button>
          )}
        </div>
      );
    return render(state.profile);
  };

  return (
    <Tabs value={tab} onValueChange={(value) => setTab(value as TTab)} className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Tabs.List className="w-fit">
          <Tabs.Trigger value="info">{t("page_tree.zil_client.profile.tab_info")}</Tabs.Trigger>
          <Tabs.Trigger value="assets">{t("page_tree.zil_client.profile.tab_assets")}</Tabs.Trigger>
          <Tabs.Trigger value="calls">{t("page_tree.zil_client.profile.tab_calls")}</Tabs.Trigger>
          <Tabs.Trigger value="pages">
            {t("page_tree.zil_client.profile.tab_pages")} · {pagesCount}
          </Tabs.Trigger>
          <Tabs.Indicator />
        </Tabs.List>
        {state.status === "ready" && (
          <a
            href={state.profile.zilUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto flex items-center gap-1 text-13 text-secondary hover:text-primary"
          >
            {t("page_tree.zil_client.profile.open_in_zil")}
            <ExternalLink className="size-3.5" />
          </a>
        )}
      </div>
      <Tabs.Content value="info">
        {renderProfileTab((profile) => (
          <ZilClientInfo profile={profile} />
        ))}
      </Tabs.Content>
      <Tabs.Content value="assets">
        {renderProfileTab((profile) =>
          workspaceSlug && projectId && pageId ? (
            <ZilClientAssets
              profile={profile}
              workspaceSlug={workspaceSlug}
              projectId={projectId}
              pageId={pageId}
              canEdit={!page.archived_at}
              onChange={updateProfile}
            />
          ) : null
        )}
      </Tabs.Content>
      <Tabs.Content value="calls">
        {renderProfileTab((profile) => (
          <ZilClientCalls calls={profile.calls} />
        ))}
      </Tabs.Content>
      <Tabs.Content value="pages">{pages}</Tabs.Content>
    </Tabs>
  );
});
