/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
// services
import type { TZilBrandOps } from "@/services/zil-brand.service";
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
  const updateOps = async (changes: Partial<TZilBrandOps>) => {
    if (!workspaceSlug || !projectId || !data) return;
    const previous = data.ops;
    await mutate((current) => (current ? { ...current, ops: { ...current.ops, ...changes } } : current), {
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
