/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
// services
import type { TZilPortalSettings } from "@plane/types";
import type { TZilBrandOps, TZilBrandOpsChanges } from "@/services/zil-brand.service";
import { ZilBrandService } from "@/services/zil-brand.service";

const zilBrandService = new ZilBrandService();

/** The Zil projects (brands and "Migración") of the workspace the person is a member of. */
export function useZilMyBrands(workspaceSlug: string | undefined) {
  const { data, isLoading, error, mutate } = useSWR(
    workspaceSlug ? `ZIL_MY_BRANDS_${workspaceSlug}` : null,
    workspaceSlug ? () => zilBrandService.listMyBrands(workspaceSlug) : null,
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );
  return { brands: data ?? [], isLoading, error, mutate };
}

/** The brand of a project, when it is a brand's (undefined otherwise or while loading). */
export function useZilProjectBrandProject(workspaceSlug: string | undefined, projectId: string | undefined) {
  const { brands } = useZilMyBrands(workspaceSlug);
  return brands.find((brand) => brand.project_id === projectId && brand.kind === "brand");
}

export function useZilProjectBrand(workspaceSlug: string | undefined, projectId: string | undefined) {
  const { data, isLoading, error, mutate } = useSWR(
    workspaceSlug && projectId ? `ZIL_PROJECT_BRAND_${projectId}` : null,
    workspaceSlug && projectId ? () => zilBrandService.getProjectBrand(workspaceSlug, projectId) : null,
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );
  /** Saves what Ops keeps on the brand, shown at once and without asking Zil again; undone if it fails. */
  const updateOps = async (changes: TZilBrandOpsChanges) => {
    if (!workspaceSlug || !projectId || !data) return;
    const previous = data.ops;
    // a change to some units' Responsable leaves the other units as they are
    const merge = (ops: TZilBrandOps): TZilBrandOps => {
      const { responsibles, ...rest } = changes;
      if (!responsibles) return { ...ops, ...rest };
      const changed = new Map(responsibles.map((unit) => [unit.workspace_id, unit]));
      return {
        ...ops,
        ...rest,
        responsibles: ops.responsibles.map((unit) => changed.get(unit.workspace_id) ?? unit),
      };
    };
    await mutate((current) => (current ? { ...current, ops: merge(current.ops) } : current), {
      revalidate: false,
    });
    try {
      const { ops } = await zilBrandService.updateProjectBrandOps(workspaceSlug, projectId, changes);
      await mutate((current) => (current ? { ...current, ops } : current), { revalidate: false });
    } catch (failure) {
      await mutate((current) => (current ? { ...current, ops: previous } : current), { revalidate: false });
      throw failure;
    }
  };
  return { data, isLoading, error, updateOps };
}

/** The work items whose Drive video the brand's clients can't open; nothing for other projects. */
export function useZilVideoAlerts(workspaceSlug: string | undefined, projectId: string | undefined) {
  const brand = useZilProjectBrandProject(workspaceSlug, projectId);
  const { data } = useSWR(
    workspaceSlug && projectId && brand ? `ZIL_VIDEO_ALERTS_${projectId}` : null,
    workspaceSlug && projectId ? () => zilBrandService.getVideoAlerts(workspaceSlug, projectId) : null,
    { revalidateOnFocus: true, shouldRetryOnError: false }
  );
  return data?.issues ?? {};
}

/** The brand's client portal, from the Marca tab: turning it on invites the clients; resend one's link. */
export function useZilProjectPortal(workspaceSlug: string | undefined, projectId: string | undefined) {
  const { data, isLoading, mutate } = useSWR(
    workspaceSlug && projectId ? `ZIL_PROJECT_PORTAL_${projectId}` : null,
    workspaceSlug && projectId ? () => zilBrandService.getProjectPortal(workspaceSlug, projectId) : null,
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );
  const save = async (request: Promise<TZilPortalSettings>) => {
    const portal = await request;
    await mutate(portal, { revalidate: false });
    return portal;
  };
  const setEnabled = (enabled: boolean) =>
    workspaceSlug && projectId ? save(zilBrandService.setProjectPortal(workspaceSlug, projectId, enabled)) : undefined;
  const resendInvite = (clientId: string) =>
    workspaceSlug && projectId
      ? save(zilBrandService.resendPortalInvite(workspaceSlug, projectId, clientId))
      : undefined;
  const setLimits = (limits: Partial<Pick<TZilPortalSettings, "change_rounds" | "change_hours">>) =>
    workspaceSlug && projectId ? save(zilBrandService.setPortalLimits(workspaceSlug, projectId, limits)) : undefined;
  return { portal: data, isLoading, setEnabled, resendInvite, setLimits };
}
