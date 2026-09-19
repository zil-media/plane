/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Input, ToggleSwitch } from "@plane/ui";
import type { TSupportMe } from "@/services/support.service";
import { supportService } from "@/services/support.service";

type Props = { me: TSupportMe; onChanged: () => void };

export function SupportAdminSettings({ me, onChanged }: Props) {
  const { t } = useTranslation();

  const update = async (data: Parameters<typeof supportService.updateConfig>[0]) => {
    try {
      await supportService.updateConfig(data);
      onChanged();
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("helpdesk.error_title"), message: t("helpdesk.try_again") });
    }
  };

  return (
    <div className="flex max-w-xl flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-3 rounded-md border border-subtle px-3 py-2.5">
        <span className="flex flex-col">
          <span className="text-body-xs-medium text-primary">{t("helpdesk.settings.bug_agent")}</span>
          <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.settings.bug_agent_hint")}</span>
        </span>
        <ToggleSwitch
          value={me.bug_agent_enabled}
          label={t("helpdesk.settings.bug_agent")}
          onChange={() => void update({ bug_agent_enabled: !me.bug_agent_enabled })}
        />
      </div>
      <div className="flex items-center justify-between gap-3 rounded-md border border-subtle px-3 py-2.5">
        <span className="flex flex-col">
          <span className="text-body-xs-medium text-primary">{t("helpdesk.settings.feature_agent")}</span>
          <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.settings.feature_agent_hint")}</span>
        </span>
        <ToggleSwitch
          value={me.feature_agent_enabled}
          label={t("helpdesk.settings.feature_agent")}
          onChange={() => void update({ feature_agent_enabled: !me.feature_agent_enabled })}
        />
      </div>
      <div className="flex items-center justify-between gap-3 rounded-md border border-subtle px-3 py-2.5">
        <span className="flex flex-col">
          <span className="text-body-xs-medium text-primary">{t("helpdesk.settings.max_builds")}</span>
          <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.settings.max_builds_hint")}</span>
        </span>
        <Input
          type="number"
          min={0}
          max={50}
          className="w-20"
          defaultValue={me.max_builds_per_week}
          onBlur={(event) => {
            const value = Number(event.target.value);
            if (Number.isInteger(value) && value !== me.max_builds_per_week)
              void update({ max_builds_per_week: value });
          }}
        />
      </div>
    </div>
  );
}
