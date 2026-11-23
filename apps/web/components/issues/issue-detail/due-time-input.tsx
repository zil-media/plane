/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import { cn } from "@plane/utils";
import { useFeatureFlag } from "@/hooks/use-feature-flag";

type Props = {
  targetDate: string | null;
  targetTime: string | null | undefined;
  disabled?: boolean;
  onChange: (time: string | null) => void;
};

// Optional hour for a work item's due date. Hidden until the issueDueTime flag is on and a due date exists.
export function IssueDueTimeInput({ targetDate, targetTime, disabled, onChange }: Props) {
  const { t } = useTranslation();
  const enabled = useFeatureFlag("issueDueTime");

  if (!enabled || !targetDate) return null;

  return (
    <input
      type="time"
      aria-label={t("issue.add.due_time")}
      title={t("issue.add.due_time")}
      value={targetTime ? targetTime.slice(0, 5) : ""}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value ? e.target.value : null)}
      className={cn(
        "h-7 shrink-0 rounded-sm border-none bg-transparent px-1 text-body-xs-regular outline-none hover:bg-layer-transparent-hover",
        { "text-placeholder": !targetTime }
      )}
    />
  );
}
