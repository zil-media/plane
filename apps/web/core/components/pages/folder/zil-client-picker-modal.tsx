/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Building2, Search } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TZilClientSearchResult } from "@plane/types";
import { EModalPosition, EModalWidth, ModalCore, Spinner } from "@plane/ui";
import { cn } from "@plane/utils";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
import useDebounce from "@/hooks/use-debounce";
// services
import { ProjectPageService } from "@/services/page";
// store
import type { TPageInstance } from "@/store/pages/base-page";

const projectPageService = new ProjectPageService();

type Props = {
  isOpen: boolean;
  onClose: () => void;
  page: TPageInstance;
};

type TSearchState =
  | { status: "loading" }
  | { status: "ready"; results: TZilClientSearchResult[] }
  | { status: "unavailable" };

export const ZilClientPickerModal = observer(function ZilClientPickerModal(props: Props) {
  const { isOpen, onClose, page } = props;
  // states
  const [query, setQuery] = useState("");
  const [searchState, setSearchState] = useState<TSearchState>({ status: "loading" });
  const [submittingId, setSubmittingId] = useState<string | null>(null);
  // hooks
  const { t } = useTranslation();
  const router = useAppRouter();
  const debouncedQuery = useDebounce(query, 300);
  // derived values
  const { workspaceSlug: workspaceSlugParam } = useParams();
  const workspaceSlug = workspaceSlugParam?.toString();
  const projectId = page.project_ids?.[0];
  const linkedClientId = page.zil_client?.id;

  useEffect(() => {
    if (!isOpen || !workspaceSlug || !projectId) return;
    let cancelled = false;
    setSearchState({ status: "loading" });
    projectPageService
      .searchZilClients(workspaceSlug, projectId, debouncedQuery)
      .then((response) => {
        if (cancelled) return undefined;
        return setSearchState(
          response.enabled ? { status: "ready", results: response.results } : { status: "unavailable" }
        );
      })
      .catch(() => {
        if (!cancelled) setSearchState({ status: "unavailable" });
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, debouncedQuery, workspaceSlug, projectId]);

  const handleClose = () => {
    setQuery("");
    setSubmittingId(null);
    onClose();
  };

  const handleLink = async (client: TZilClientSearchResult) => {
    if (!workspaceSlug || !projectId || !page.id) return;
    setSubmittingId(client.id);
    try {
      const zilClient = await projectPageService.linkZilClient(workspaceSlug, projectId, page.id, client.id);
      page.mutateProperties({ zil_client: zilClient }, false);
      setToast({ type: TOAST_TYPE.SUCCESS, title: t("page_tree.zil_client.linked") });
      handleClose();
    } catch (error) {
      const data = error as { status?: number; page_id?: string } | undefined;
      const linkedFolderId = data?.status === 409 ? data.page_id : undefined;
      if (linkedFolderId) {
        setToast({
          type: TOAST_TYPE.ERROR,
          title: t("page_tree.zil_client.already_linked"),
          actionItems: (
            <button
              type="button"
              className="text-link-primary hover:underline"
              // the other folder lives in the same project: swap the page id
              onClick={() => router.push(page.getRedirectionLink().replace(/[^/]+$/, linkedFolderId))}
            >
              {t("page_tree.zil_client.open_linked_folder")}
            </button>
          ),
        });
      } else {
        setToast({
          type: TOAST_TYPE.ERROR,
          title: data?.status === 502 ? t("page_tree.zil_client.unavailable") : t("page_tree.zil_client.error"),
        });
      }
    } finally {
      setSubmittingId(null);
    }
  };

  const handleUnlink = async () => {
    if (!workspaceSlug || !projectId || !page.id) return;
    setSubmittingId("unlink");
    try {
      await projectPageService.unlinkZilClient(workspaceSlug, projectId, page.id);
      page.mutateProperties({ zil_client: null }, false);
      setToast({ type: TOAST_TYPE.SUCCESS, title: t("page_tree.zil_client.unlinked") });
      handleClose();
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("page_tree.zil_client.error") });
    } finally {
      setSubmittingId(null);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={handleClose} position={EModalPosition.TOP} width={EModalWidth.XL}>
      <div className="flex flex-col gap-3 p-4">
        <h3 className="text-16 font-medium text-primary">{t("page_tree.zil_client.title")}</h3>
        <label className="flex items-center gap-2 rounded-md border border-subtle px-2 py-1.5">
          <Search className="size-3.5 flex-shrink-0 text-tertiary" />
          <input
            className="w-full bg-transparent text-13 outline-none placeholder:text-placeholder"
            placeholder={t("page_tree.zil_client.search_placeholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="max-h-80 min-h-24 overflow-y-auto">
          {searchState.status === "loading" && (
            <div className="grid h-24 place-items-center">
              <Spinner height="20px" width="20px" />
            </div>
          )}
          {searchState.status === "unavailable" && (
            <p className="py-6 text-center text-13 text-secondary">{t("page_tree.zil_client.unavailable")}</p>
          )}
          {searchState.status === "ready" && searchState.results.length === 0 && (
            <p className="py-6 text-center text-13 text-secondary">{t("page_tree.zil_client.no_results")}</p>
          )}
          {searchState.status === "ready" &&
            searchState.results.map((client) => {
              const isCurrent = client.id === linkedClientId;
              return (
                <button
                  key={client.id}
                  type="button"
                  disabled={!!submittingId || isCurrent}
                  onClick={() => handleLink(client)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left hover:bg-layer-transparent-hover disabled:cursor-default",
                    { "bg-layer-transparent-active": isCurrent }
                  )}
                >
                  <Building2 className="size-4 flex-shrink-0 text-tertiary" />
                  <span className="flex min-w-0 flex-grow flex-col">
                    <span className="truncate text-13 text-primary">{client.alias || client.companyName}</span>
                    {client.alias && <span className="truncate text-11 text-tertiary">{client.companyName}</span>}
                  </span>
                  {client.lifecycleStatus && (
                    <span className="flex-shrink-0 rounded-sm bg-layer-3 px-1.5 py-0.5 text-11 text-secondary">
                      {client.lifecycleStatus}
                    </span>
                  )}
                  {client.businessUnitSlug && (
                    <span className="flex-shrink-0 text-11 text-tertiary">{client.businessUnitSlug}</span>
                  )}
                  {submittingId === client.id && <Spinner height="14px" width="14px" />}
                </button>
              );
            })}
        </div>
        {linkedClientId && (
          <div className="flex justify-end border-t border-subtle pt-3">
            <Button variant="error-outline" size="lg" onClick={handleUnlink} loading={submittingId === "unlink"}>
              {t("page_tree.zil_client.unlink")}
            </Button>
          </div>
        )}
      </div>
    </ModalCore>
  );
});
