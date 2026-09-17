/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { unset, set } from "lodash-es";
import { makeObservable, observable, runInAction, action, reaction, computed } from "mobx";
import { computedFn } from "mobx-utils";
// types
import { EUserPermissions } from "@plane/constants";
import type { TPage, TPageFilters, TPageNavigationTabs } from "@plane/types";
import { EUserProjectRoles } from "@plane/types";
// helpers
import { filterPagesByPageType, getPageName, orderPages, shouldFilterPage } from "@plane/utils";
// plane web constants
// plane web store
import type { RootStore } from "@/plane-web/store/root.store";
// services
import { ProjectPageService } from "@/services/page";
// store
import type { CoreRootStore } from "../root.store";
import type { TProjectPage } from "./project-page";
import { ProjectPage } from "./project-page";

type TLoader = "init-loader" | "mutation-loader" | undefined;

const TREE_ROOT_KEY = "__root__";
const EXPANDED_STORAGE_KEY_PREFIX = "zil_ops_pages_tree_expanded:";
export const MAX_PAGE_TREE_DEPTH = 8;

const readExpandedFromStorage = (projectId: string): Record<string, boolean> => {
  try {
    const raw = window.localStorage.getItem(`${EXPANDED_STORAGE_KEY_PREFIX}${projectId}`);
    const ids = raw ? (JSON.parse(raw) as string[]) : [];
    return Object.fromEntries(ids.map((id) => [id, true]));
  } catch {
    return {};
  }
};

const writeExpandedToStorage = (projectId: string, expanded: Record<string, boolean>) => {
  try {
    const ids = Object.keys(expanded).filter((id) => expanded[id]);
    window.localStorage.setItem(`${EXPANDED_STORAGE_KEY_PREFIX}${projectId}`, JSON.stringify(ids));
  } catch {
    // storage unavailable: expanded state just won't persist
  }
};

type TError = { title: string; description: string };

export const ROLE_PERMISSIONS_TO_CREATE_PAGE = [
  EUserPermissions.ADMIN,
  EUserPermissions.MEMBER,
  EUserProjectRoles.ADMIN,
  EUserProjectRoles.MEMBER,
];

export interface IProjectPageStore {
  // observables
  loader: TLoader;
  data: Record<string, TProjectPage>; // pageId => Page
  error: TError | undefined;
  filters: TPageFilters;
  // computed
  isAnyPageAvailable: boolean;
  canCurrentUserCreatePage: boolean;
  // helper actions
  getCurrentProjectPageIdsByTab: (pageType: TPageNavigationTabs) => string[] | undefined;
  getCurrentProjectPageIds: (projectId: string) => string[];
  getCurrentProjectFilteredPageIdsByTab: (pageType: TPageNavigationTabs) => string[] | undefined;
  getPageById: (pageId: string) => TProjectPage | undefined;
  // page tree
  hasActiveSearchOrFilters: boolean;
  getTreeChildIds: (parentId: string | null, pageType: TPageNavigationTabs) => string[];
  getAncestorIds: (pageId: string) => string[];
  getDescendantIds: (pageId: string) => string[];
  getSubtreeHeight: (pageId: string) => number;
  isPageMatchingSearch: (pageId: string) => boolean;
  isPageExpanded: (pageId: string) => boolean;
  toggleExpanded: (pageId: string) => void;
  setExpanded: (pageId: string, expanded: boolean) => void;
  expandAncestors: (pageId: string) => void;
  movePageInTree: (pageId: string, parentId: string | null, sortOrder?: number) => Promise<void>;
  updateFilters: <T extends keyof TPageFilters>(filterKey: T, filterValue: TPageFilters[T]) => void;
  clearAllFilters: () => void;
  // actions
  fetchPagesList: (
    workspaceSlug: string,
    projectId: string,
    pageType?: TPageNavigationTabs
  ) => Promise<TPage[] | undefined>;
  fetchPageDetails: (
    workspaceSlug: string,
    projectId: string,
    pageId: string,
    options?: { trackVisit?: boolean }
  ) => Promise<TPage | undefined>;
  createPage: (pageData: Partial<TPage>) => Promise<TPage | undefined>;
  removePage: (params: { pageId: string; shouldSync?: boolean }) => Promise<void>;
  movePage: (workspaceSlug: string, projectId: string, pageId: string, newProjectId: string) => Promise<void>;
}

export class ProjectPageStore implements IProjectPageStore {
  // observables
  loader: TLoader = "init-loader";
  data: Record<string, TProjectPage> = {}; // pageId => Page
  error: TError | undefined = undefined;
  filters: TPageFilters = {
    searchQuery: "",
    sortKey: "updated_at",
    sortBy: "desc",
  };
  // projectId => pageId => expanded
  expandedPageIds: Record<string, Record<string, boolean>> = {};
  // service
  service: ProjectPageService;
  rootStore: CoreRootStore;

  constructor(private store: RootStore) {
    makeObservable(this, {
      // observables
      loader: observable.ref,
      data: observable,
      error: observable,
      filters: observable,
      expandedPageIds: observable,
      // computed
      isAnyPageAvailable: computed,
      canCurrentUserCreatePage: computed,
      hasActiveSearchOrFilters: computed,
      toggleExpanded: action,
      setExpanded: action,
      expandAncestors: action,
      movePageInTree: action,
      // helper actions
      updateFilters: action,
      clearAllFilters: action,
      // actions
      fetchPagesList: action,
      fetchPageDetails: action,
      createPage: action,
      removePage: action,
      movePage: action,
    });
    this.rootStore = store;
    // service
    this.service = new ProjectPageService();
    // initialize display filters of the current project
    reaction(
      () => this.store.router.projectId,
      (projectId) => {
        if (!projectId) return;
        this.filters.searchQuery = "";
      }
    );
  }

  /**
   * @description check if any page is available
   */
  get isAnyPageAvailable() {
    if (this.loader) return true;
    return Object.keys(this.data).length > 0;
  }

  /**
   * @description returns true if the current logged in user can create a page
   */
  get canCurrentUserCreatePage() {
    const { workspaceSlug, projectId } = this.store.router;
    const currentUserProjectRole = this.store.user.permission.getProjectRoleByWorkspaceSlugAndProjectId(
      workspaceSlug?.toString() || "",
      projectId?.toString() || ""
    );
    return !!currentUserProjectRole && ROLE_PERMISSIONS_TO_CREATE_PAGE.includes(currentUserProjectRole);
  }

  /**
   * @description get the current project page ids based on the pageType
   * @param {TPageNavigationTabs} pageType
   */
  getCurrentProjectPageIdsByTab = computedFn((pageType: TPageNavigationTabs) => {
    const { projectId } = this.store.router;
    if (!projectId) return undefined;
    // helps to filter pages based on the pageType
    let pagesByType = filterPagesByPageType(pageType, Object.values(this?.data || {}));
    pagesByType = pagesByType.filter((p) => p.project_ids?.includes(projectId));

    const pages = (pagesByType.map((page) => page.id) as string[]) || undefined;

    return pages ?? undefined;
  });

  /**
   * @description get the current project page ids
   * @param {string} projectId
   */
  getCurrentProjectPageIds = computedFn((projectId: string) => {
    if (!projectId) return [];
    const pages = Object.values(this?.data || {}).filter((page) => page.project_ids?.includes(projectId));
    return pages.map((page) => page.id) as string[];
  });

  /**
   * @description get the current project filtered page ids based on the pageType
   * @param {TPageNavigationTabs} pageType
   */
  getCurrentProjectFilteredPageIdsByTab = computedFn((pageType: TPageNavigationTabs) => {
    const { projectId } = this.store.router;
    if (!projectId) return undefined;

    // helps to filter pages based on the pageType
    const pagesByType = filterPagesByPageType(pageType, Object.values(this?.data || {}));
    let filteredPages = pagesByType.filter(
      (p) =>
        p.project_ids?.includes(projectId) &&
        getPageName(p.name).toLowerCase().includes(this.filters.searchQuery.toLowerCase()) &&
        shouldFilterPage(p, this.filters.filters)
    );
    filteredPages = orderPages(filteredPages, this.filters.sortKey, this.filters.sortBy);

    const pages = (filteredPages.map((page) => page.id) as string[]) || undefined;

    return pages ?? undefined;
  });

  /**
   * @description get the page store by id
   * @param {string} pageId
   */
  getPageById = computedFn((pageId: string) => this.data?.[pageId] || undefined);

  // ---------------------------------------------------------------------------
  // page tree
  // ---------------------------------------------------------------------------

  get hasActiveSearchOrFilters() {
    const hasFilters = Object.values(this.filters.filters ?? {}).some((value) =>
      Array.isArray(value) ? value.length > 0 : !!value
    );
    return this.filters.searchQuery.trim().length > 0 || hasFilters;
  }

  /**
   * @description true when the page matches the current search query and filters
   */
  isPageMatchingSearch = computedFn((pageId: string) => {
    const page = this.getPageById(pageId);
    if (!page) return false;
    return (
      getPageName(page.name).toLowerCase().includes(this.filters.searchQuery.toLowerCase()) &&
      shouldFilterPage(page, this.filters.filters)
    );
  });

  /**
   * @description parentId (or root) => ordered child ids for the current project and tab.
   * A page whose parent is not visible in this tab (e.g. a public page under a private
   * one, or an archived subtree whose parent is still active) is shown at the root.
   * While searching, only matches and their ancestors are part of the tree.
   */
  private getTreeChildrenMap = computedFn((pageType: TPageNavigationTabs) => {
    const { projectId } = this.store.router;
    const childrenMap = new Map<string, string[]>();
    if (!projectId) return childrenMap;

    const tabPages = filterPagesByPageType(pageType, Object.values(this?.data || {})).filter((p) =>
      p.project_ids?.includes(projectId)
    ) as TProjectPage[];
    const tabPageIds = new Set(tabPages.map((p) => p.id as string));

    let visiblePages = tabPages;
    if (this.hasActiveSearchOrFilters) {
      const visibleIds = new Set<string>();
      tabPages.forEach((page) => {
        if (!page.id || !this.isPageMatchingSearch(page.id)) return;
        visibleIds.add(page.id);
        this.getAncestorIds(page.id).forEach((ancestorId) => {
          if (tabPageIds.has(ancestorId)) visibleIds.add(ancestorId);
        });
      });
      visiblePages = tabPages.filter((p) => visibleIds.has(p.id as string));
    }

    const ordered = orderPages(visiblePages, this.filters.sortKey, this.filters.sortBy) as TProjectPage[];
    // folders first, keeping the chosen order inside each group
    const sorted = [...ordered.filter((p) => p.kind === "folder"), ...ordered.filter((p) => p.kind !== "folder")];
    sorted.forEach((page) => {
      if (!page.id) return;
      const key = page.parent && tabPageIds.has(page.parent) ? page.parent : TREE_ROOT_KEY;
      const siblings = childrenMap.get(key) ?? [];
      siblings.push(page.id);
      childrenMap.set(key, siblings);
    });
    return childrenMap;
  });

  getTreeChildIds = computedFn(
    (parentId: string | null, pageType: TPageNavigationTabs) =>
      this.getTreeChildrenMap(pageType).get(parentId ?? TREE_ROOT_KEY) ?? []
  );

  /**
   * @description ancestors of a page ordered root -> direct parent
   */
  getAncestorIds = computedFn((pageId: string) => {
    const ancestors: string[] = [];
    const seen = new Set<string>([pageId]);
    let parentId = this.getPageById(pageId)?.parent;
    while (parentId && !seen.has(parentId)) {
      const parent = this.getPageById(parentId);
      if (!parent) break;
      ancestors.unshift(parentId);
      seen.add(parentId);
      parentId = parent.parent;
    }
    return ancestors;
  });

  /**
   * @description all descendants of a page loaded in the store
   */
  getDescendantIds = computedFn((pageId: string) => {
    const childrenByParent = new Map<string, string[]>();
    Object.values(this.data).forEach((page) => {
      if (!page.id || !page.parent) return;
      childrenByParent.set(page.parent, [...(childrenByParent.get(page.parent) ?? []), page.id]);
    });
    const descendants: string[] = [];
    const queue = [...(childrenByParent.get(pageId) ?? [])];
    const seen = new Set<string>([pageId]);
    while (queue.length) {
      const id = queue.shift() as string;
      if (seen.has(id)) continue;
      seen.add(id);
      descendants.push(id);
      queue.push(...(childrenByParent.get(id) ?? []));
    }
    return descendants;
  });

  /**
   * @description levels in the subtree rooted at the page (a leaf is 1)
   */
  getSubtreeHeight = computedFn((pageId: string): number => {
    const descendants = this.getDescendantIds(pageId);
    if (!descendants.length) return 1;
    const baseDepth = this.getAncestorIds(pageId).length;
    return Math.max(...descendants.map((id) => this.getAncestorIds(id).length - baseDepth)) + 1;
  });

  isPageExpanded = (pageId: string) => {
    const { projectId } = this.store.router;
    if (!projectId) return false;
    const expanded = this.expandedPageIds[projectId];
    // until the project's state is hydrated, fall back to the persisted value
    if (!expanded) return !!readExpandedFromStorage(projectId)[pageId];
    return !!expanded[pageId];
  };

  setExpanded = (pageId: string, expanded: boolean) => {
    const { projectId } = this.store.router;
    if (!projectId) return;
    const current = this.expandedPageIds[projectId] ?? readExpandedFromStorage(projectId);
    const next = { ...current };
    if (expanded) next[pageId] = true;
    else delete next[pageId];
    set(this.expandedPageIds, [projectId], next);
    writeExpandedToStorage(projectId, next);
  };

  toggleExpanded = (pageId: string) => this.setExpanded(pageId, !this.isPageExpanded(pageId));

  expandAncestors = (pageId: string) => {
    this.getAncestorIds(pageId).forEach((ancestorId) => {
      if (!this.isPageExpanded(ancestorId)) this.setExpanded(ancestorId, true);
    });
  };

  /**
   * @description move a page under another page (or to the root) — optimistic
   */
  movePageInTree = async (pageId: string, parentId: string | null, sortOrder?: number) => {
    const { workspaceSlug, projectId } = this.store.router;
    const page = this.getPageById(pageId);
    if (!workspaceSlug || !projectId || !page) return;

    const previous = { parent: page.parent, sort_order: page.sort_order };
    runInAction(() => {
      page.mutateProperties({ parent: parentId, ...(sortOrder !== undefined ? { sort_order: sortOrder } : {}) }, false);
    });
    try {
      const response = await this.service.moveInTree(workspaceSlug, projectId, pageId, {
        parent_id: parentId,
        ...(sortOrder !== undefined ? { sort_order: sortOrder } : {}),
      });
      runInAction(() => {
        page.mutateProperties({ parent: response.parent, sort_order: response.sort_order }, false);
        if (parentId) this.setExpanded(parentId, true);
      });
    } catch (error) {
      runInAction(() => {
        page.mutateProperties(previous, false);
      });
      throw error;
    }
  };

  updateFilters = <T extends keyof TPageFilters>(filterKey: T, filterValue: TPageFilters[T]) => {
    runInAction(() => {
      set(this.filters, [filterKey], filterValue);
    });
  };

  /**
   * @description clear all the filters
   */
  clearAllFilters = () =>
    runInAction(() => {
      set(this.filters, ["filters"], {});
    });

  /**
   * @description fetch all the pages
   */
  fetchPagesList = async (workspaceSlug: string, projectId: string, pageType?: TPageNavigationTabs) => {
    try {
      if (!workspaceSlug || !projectId) return undefined;

      const currentPageIds = pageType ? this.getCurrentProjectPageIdsByTab(pageType) : undefined;
      runInAction(() => {
        this.loader = currentPageIds && currentPageIds.length > 0 ? `mutation-loader` : `init-loader`;
        this.error = undefined;
      });

      const pages = await this.service.fetchAll(workspaceSlug, projectId);
      runInAction(() => {
        for (const page of pages) {
          if (page?.id) {
            const existingPage = this.getPageById(page.id);
            if (existingPage) {
              // If page already exists, update all fields except name

              const { name, ...otherFields } = page;
              existingPage.mutateProperties(otherFields, false);
            } else {
              // If new page, create a new instance with all data
              set(this.data, [page.id], new ProjectPage(this.store, page));
            }
          }
        }
        this.loader = undefined;
      });

      return pages;
    } catch (error) {
      runInAction(() => {
        this.loader = undefined;
        this.error = {
          title: "Failed",
          description: "Failed to fetch the pages, Please try again later.",
        };
      });
      throw error;
    }
  };

  /**
   * @description fetch the details of a page
   * @param {string} pageId
   */
  fetchPageDetails = async (...args: Parameters<IProjectPageStore["fetchPageDetails"]>) => {
    const [workspaceSlug, projectId, pageId, options] = args;
    const { trackVisit } = options || {};
    try {
      if (!workspaceSlug || !projectId || !pageId) return undefined;

      const currentPageId = this.getPageById(pageId);
      runInAction(() => {
        this.loader = currentPageId ? `mutation-loader` : `init-loader`;
        this.error = undefined;
      });

      const page = await this.service.fetchById(workspaceSlug, projectId, pageId, trackVisit ?? true);

      runInAction(() => {
        if (page?.id) {
          const pageInstance = this.getPageById(page.id);
          if (pageInstance) {
            pageInstance.mutateProperties(page, false);
          } else {
            set(this.data, [page.id], new ProjectPage(this.store, page));
          }
        }
        this.loader = undefined;
      });

      return page;
    } catch (error) {
      runInAction(() => {
        this.loader = undefined;
        this.error = {
          title: "Failed",
          description: "Failed to fetch the page, Please try again later.",
        };
      });
      throw error;
    }
  };

  /**
   * @description create a page
   * @param {Partial<TPage>} pageData
   */
  createPage = async (pageData: Partial<TPage>) => {
    try {
      const { workspaceSlug, projectId } = this.store.router;
      if (!workspaceSlug || !projectId) return undefined;

      runInAction(() => {
        this.loader = "mutation-loader";
        this.error = undefined;
      });

      const page = await this.service.create(workspaceSlug, projectId, pageData);
      runInAction(() => {
        if (page?.id) set(this.data, [page.id], new ProjectPage(this.store, page));
        if (page?.parent) this.setExpanded(page.parent, true);
        this.loader = undefined;
      });

      return page;
    } catch (error) {
      runInAction(() => {
        this.loader = undefined;
        this.error = {
          title: "Failed",
          description: "Failed to create a page, Please try again later.",
        };
      });
      throw error;
    }
  };

  /**
   * @description delete a page
   * @param {string} pageId
   */
  removePage = async ({ pageId, shouldSync: _shouldSync = true }: { pageId: string; shouldSync?: boolean }) => {
    try {
      const { workspaceSlug, projectId } = this.store.router;
      if (!workspaceSlug || !projectId || !pageId) return undefined;

      await this.service.remove(workspaceSlug, projectId, pageId);
      runInAction(() => {
        // children move up one level, as on the server
        const removedPage = this.getPageById(pageId);
        Object.values(this.data).forEach((page) => {
          if (page.parent === pageId) page.mutateProperties({ parent: removedPage?.parent ?? null }, false);
        });
        unset(this.data, [pageId]);
        if (this.rootStore.favorite.entityMap[pageId]) this.rootStore.favorite.removeFavoriteFromStore(pageId);
      });
    } catch (error) {
      runInAction(() => {
        this.loader = undefined;
        this.error = {
          title: "Failed",
          description: "Failed to delete a page, Please try again later.",
        };
      });
      throw error;
    }
  };

  /**
   * @description move a page to a new project
   * @param {string} workspaceSlug
   * @param {string} projectId
   * @param {string} pageId
   * @param {string} newProjectId
   */
  movePage = async (workspaceSlug: string, projectId: string, pageId: string, newProjectId: string) => {
    try {
      await this.service.move(workspaceSlug, projectId, pageId, newProjectId);
      runInAction(() => {
        unset(this.data, [pageId]);
      });
    } catch (error) {
      console.error("Unable to move page", error);
      throw error;
    }
  };
}
