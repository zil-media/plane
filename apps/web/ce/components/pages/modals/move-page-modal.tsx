/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { sortBy } from "lodash-es";
import { observer } from "mobx-react";
import { Folder, Home, Search } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { PageIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
import { cn, getPageName } from "@plane/utils";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
// store types
import type { TPageInstance } from "@/store/pages/base-page";
import { MAX_PAGE_TREE_DEPTH } from "@/store/pages/project-page.store";

export type TMovePageModalProps = {
  isOpen: boolean;
  onClose: () => void;
  page: TPageInstance;
};

const ROOT_TARGET = "__root__";
const INDENT_PER_LEVEL_PX = 16;

type TTarget = { id: string; depth: number };

export const MovePageModal = observer(function MovePageModal(props: TMovePageModalProps) {
  const { isOpen, onClose, page } = props;
  // states
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // hooks
  const { t } = useTranslation();
  const { data, getAncestorIds, getDescendantIds, getSubtreeHeight, movePageInTree } = usePageStore(
    EPageStoreType.PROJECT
  );
  // derived values
  const projectId = page.project_ids?.[0];
  const pageName = getPageName(page.name);

  // every active page of the project the user can see, flattened in tree order
  const targets = useMemo<TTarget[]>(() => {
    if (!isOpen || !page.id || !projectId) return [];
    const candidates = Object.values(data).filter(
      (candidate) => candidate.id && !candidate.archived_at && candidate.project_ids?.includes(projectId)
    );
    const candidateIds = new Set(candidates.map((candidate) => candidate.id as string));
    const childrenByParent = new Map<string, TPageInstance[]>();
    candidates.forEach((candidate) => {
      const key = candidate.parent && candidateIds.has(candidate.parent) ? candidate.parent : ROOT_TARGET;
      childrenByParent.set(key, [...(childrenByParent.get(key) ?? []), candidate]);
    });

    const flattened: TTarget[] = [];
    const visit = (parentKey: string, depth: number) => {
      // folders first, then by name
      sortBy(childrenByParent.get(parentKey) ?? [], [
        (candidate) => !candidate.isFolder,
        (candidate) => getPageName(candidate.name).toLowerCase(),
      ]).forEach((candidate) => {
        flattened.push({ id: candidate.id as string, depth });
        visit(candidate.id as string, depth + 1);
      });
    };
    visit(ROOT_TARGET, 0);
    return flattened;
  }, [data, isOpen, page.id, projectId]);

  const disabledIds = useMemo(() => {
    if (!isOpen || !page.id) return new Set<string>();
    const blocked = new Set<string>([page.id, ...getDescendantIds(page.id)]);
    const subtreeHeight = getSubtreeHeight(page.id);
    targets.forEach(({ id }) => {
      if (getAncestorIds(id).length + 1 + subtreeHeight > MAX_PAGE_TREE_DEPTH) blocked.add(id);
    });
    return blocked;
  }, [getAncestorIds, getDescendantIds, getSubtreeHeight, isOpen, page.id, targets]);

  const normalizedQuery = query.trim().toLowerCase();
  const visibleTargets = normalizedQuery
    ? targets.filter(({ id }) => getPageName(data[id]?.name).toLowerCase().includes(normalizedQuery))
    : targets;
  const currentParent = page.parent ?? ROOT_TARGET;

  const handleClose = () => {
    setQuery("");
    setSelected(null);
    onClose();
  };

  const handleMove = async () => {
    if (!page.id || !selected || selected === currentParent) return;
    setIsSubmitting(true);
    try {
      await movePageInTree(page.id, selected === ROOT_TARGET ? null : selected);
      setToast({ type: TOAST_TYPE.SUCCESS, title: t("page_tree.move.success") });
      handleClose();
    } catch (error) {
      const code = (error as { error_message?: string } | undefined)?.error_message;
      setToast({
        type: TOAST_TYPE.ERROR,
        title:
          code === "PAGE_TREE_CYCLE"
            ? t("page_tree.move.error_cycle")
            : code === "PAGE_TREE_DEPTH"
              ? t("page_tree.move.error_depth")
              : t("page_tree.move.error"),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const renderOption = (id: string, label: string, icon: React.ReactNode, depth: number, disabled: boolean) => (
    <button
      key={id}
      type="button"
      disabled={disabled}
      onClick={() => setSelected(id)}
      style={{ paddingLeft: 8 + depth * INDENT_PER_LEVEL_PX }}
      className={cn(
        "flex w-full items-center gap-2 rounded-md py-1.5 pr-2 text-left text-13 text-primary hover:bg-layer-transparent-hover disabled:cursor-not-allowed disabled:text-disabled disabled:hover:bg-transparent",
        { "bg-layer-transparent-active": selected === id }
      )}
    >
      {icon}
      <span className="truncate">{label}</span>
      {id === currentParent && <span className="ml-auto flex-shrink-0 text-11 text-tertiary">•</span>}
    </button>
  );

  return (
    <ModalCore isOpen={isOpen} handleClose={handleClose} position={EModalPosition.TOP} width={EModalWidth.XL}>
      <div className="flex flex-col gap-3 p-4">
        <h3 className="truncate text-16 font-medium text-primary">{t("page_tree.move.title", { name: pageName })}</h3>
        <label className="flex items-center gap-2 rounded-md border border-subtle px-2 py-1.5">
          <Search className="size-3.5 flex-shrink-0 text-tertiary" />
          <input
            className="w-full bg-transparent text-13 outline-none placeholder:text-placeholder"
            placeholder={t("page_tree.move.search_placeholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="max-h-80 overflow-y-auto">
          {!normalizedQuery &&
            renderOption(
              ROOT_TARGET,
              t("page_tree.move.root"),
              <Home className="size-3.5 flex-shrink-0 text-tertiary" />,
              0,
              false
            )}
          {visibleTargets.map(({ id, depth }) => {
            const target = data[id];
            if (!target) return null;
            return renderOption(
              id,
              getPageName(target.name),
              target.isFolder ? (
                <Folder className="size-3.5 flex-shrink-0 text-tertiary" />
              ) : (
                <PageIcon className="size-3.5 flex-shrink-0 text-tertiary" />
              ),
              normalizedQuery ? 0 : depth + 1,
              disabledIds.has(id)
            );
          })}
        </div>
        <div className="flex justify-end gap-2 border-t border-subtle pt-3">
          <Button variant="secondary" size="lg" onClick={handleClose}>
            {t("cancel")}
          </Button>
          <Button
            variant="primary"
            size="lg"
            onClick={handleMove}
            loading={isSubmitting}
            disabled={!selected || selected === currentParent}
          >
            {t("page_tree.move.confirm")}
          </Button>
        </div>
      </div>
    </ModalCore>
  );
});
