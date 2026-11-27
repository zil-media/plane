/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { startOfMonth } from "date-fns";
import { observer } from "mobx-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { SitesPortalService } from "@plane/services";
import { cn } from "@plane/utils";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PortalCalendar, monthRange } from "@/components/portal/calendar/calendar";
import { PortalDocuments } from "@/components/portal/documents";
import { PortalMessage, PortalShell } from "@/components/portal/portal-shell";
import { PortalPostDetail } from "@/components/portal/post-detail";
import { PortalReviewStrip } from "@/components/portal/review-strip";
import { usePortalGuard } from "@/components/portal/use-portal-guard";

const portalService = new SitesPortalService();

type TTab = "calendar" | "documents";

/** The brand's one screen: Calendario and Documentos. */
const PortalBrandPage = observer(function PortalBrandPage() {
  const { t } = useTranslation();
  const ready = usePortalGuard();
  const { projectId } = useParams<{ projectId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const postId = searchParams.get("post");
  const documentId = searchParams.get("doc");
  const tab: TTab = searchParams.get("tab") === "documents" || documentId ? "documents" : "calendar";
  const [month, setMonth] = useState(() => startOfMonth(new Date()));
  const range = monthRange(month);

  const { data: brand, error: brandError } = useSWR(ready ? `PORTAL_BRAND_${projectId}` : null, () =>
    portalService.brand(projectId)
  );
  const { data: brands } = useSWR(ready ? "PORTAL_BRANDS" : null, () => portalService.brands());
  const {
    data: posts,
    isLoading,
    error: postsError,
  } = useSWR(brand ? `PORTAL_POSTS_${projectId}_${range.start}` : null, () => portalService.posts(projectId, range), {
    keepPreviousData: true,
  });

  const go = (params: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(params)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    const query = next.toString();
    router.push(`/portal/${projectId}${query ? `?${query}` : ""}`);
  };

  const showMyBrands = (brands?.brands.length ?? 0) > 1;

  if (brandError)
    return (
      <PortalShell showMyBrands={showMyBrands}>
        {brandError?.status === 403 ? (
          <PortalMessage assetKey="no-access" title={t("zil_portal.paused_title")} text={t("zil_portal.paused_text")} />
        ) : (
          <PortalMessage
            assetKey="invalid-link"
            title={t("zil_portal.not_found_title")}
            text={t("zil_portal.not_found_text")}
          />
        )}
      </PortalShell>
    );

  if (!ready || !brand)
    return (
      <div className="flex h-screen w-full items-center justify-center bg-surface-1">
        <LogoSpinner />
      </div>
    );

  return (
    <PortalShell brand={brand} showMyBrands={showMyBrands}>
      {brand.preview && (
        <p className="rounded-md bg-layer-1 px-3 py-2 text-13 text-secondary">{t("zil_portal.preview_notice")}</p>
      )}
      <nav className="flex gap-1 border-b border-subtle">
        {(
          [
            ["calendar", t("zil_portal.calendar")],
            ["documents", t("zil_portal.documents")],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => go({ tab: key === "documents" ? "documents" : null, doc: null })}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-14",
              tab === key ? "border-accent-strong font-medium text-primary" : "border-transparent text-secondary"
            )}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "calendar" ? (
        <>
          {postsError && (
            <p className="rounded-md bg-layer-1 px-3 py-2 text-13 text-danger-primary">
              {t("zil_portal.calendar_load_error")}
            </p>
          )}
          <PortalReviewStrip posts={posts?.to_review ?? []} onOpen={(id) => go({ post: id })} />
          <PortalCalendar
            month={month}
            posts={posts?.posts ?? []}
            loading={isLoading}
            onMonthChange={setMonth}
            onOpen={(id) => go({ post: id })}
            openPostId={postId}
          />
        </>
      ) : (
        <PortalDocuments
          projectId={projectId}
          documentId={documentId}
          preview={!!brand.preview}
          onOpen={(id) => go({ doc: id, tab: "documents" })}
        />
      )}

      <PortalPostDetail
        projectId={projectId}
        postId={postId}
        preview={!!brand.preview}
        onClose={() => go({ post: null })}
      />
    </PortalShell>
  );
});

export default PortalBrandPage;
