/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TDescriptionChecklistCount = {
  checklist_total: number;
  checklist_completed: number;
};

/**
 * Counts the to-do list items of a description, the same way the API does on save
 * (plane/utils/description_checklist.py): every `li[data-type="taskItem"]`, nested ones included,
 * and the ones with `data-checked="true"`. Lets the work item card update without a refetch.
 */
export const countDescriptionChecklist = (html: string | null | undefined): TDescriptionChecklistCount => {
  if (!html || !html.includes("taskItem") || typeof DOMParser === "undefined")
    return { checklist_total: 0, checklist_completed: 0 };
  const doc = new DOMParser().parseFromString(html, "text/html");
  const items = Array.from(doc.querySelectorAll("li[data-type]")).filter(
    (item) => item.getAttribute("data-type")?.trim() === "taskItem"
  );
  const completed = items.filter((item) => item.getAttribute("data-checked")?.trim().toLowerCase() === "true");
  return { checklist_total: items.length, checklist_completed: completed.length };
};
