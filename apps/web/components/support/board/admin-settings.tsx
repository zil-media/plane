/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import { setToast } from "@plane/blocks/toast";
import { Input } from "@makeplane/propel/components/input";
import { Switch } from "@makeplane/propel/components/switch";
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
      setToast({ type: "error", title: t("helpdesk.error_title"), message: t("helpdesk.try_again") });
    }
  };

  return (
    <div className="flex max-w-xl flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-3 rounded-md border border-subtle px-3 py-2.5">
        <span className="flex flex-col">
          <span className="text-body-xs-medium text-primary">{t("helpdesk.settings.bug_agent")}</span>
          <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.settings.bug_agent_hint")}</span>
        </span>
        <Switch
          size="md"
          checked={me.bug_agent_enabled}
          aria-label={t("helpdesk.settings.bug_agent")}
          onCheckedChange={() => void update({ bug_agent_enabled: !me.bug_agent_enabled })}
        />
      </div>
      <div className="flex items-center justify-between gap-3 rounded-md border border-subtle px-3 py-2.5">
        <span className="flex flex-col">
          <span className="text-body-xs-medium text-primary">{t("helpdesk.settings.feature_agent")}</span>
          <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.settings.feature_agent_hint")}</span>
        </span>
        <Switch
          size="md"
          checked={me.feature_agent_enabled}
          aria-label={t("helpdesk.settings.feature_agent")}
          onCheckedChange={() => void update({ feature_agent_enabled: !me.feature_agent_enabled })}
        />
      </div>
      <div className="flex items-center justify-between gap-3 rounded-md border border-subtle px-3 py-2.5">
        <span className="flex flex-col">
          <span className="text-body-xs-medium text-primary">{t("helpdesk.settings.max_builds")}</span>
          <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.settings.max_builds_hint")}</span>
        </span>
        <div className="w-20">
          <Input
            size="md"
            type="number"
            min={0}
            max={50}
            defaultValue={me.max_builds_per_week}
            onBlur={(event) => {
              const raw = event.target.value.trim();
              const value = Number(raw);
              // An emptied or out-of-range field is not a value: saving it as 0 stopped every build.
              if (raw === "" || !Number.isInteger(value) || value < 0 || value > 50) {
                event.target.value = String(me.max_builds_per_week);
                return;
              }
              if (value !== me.max_builds_per_week) void update({ max_builds_per_week: value });
            }}
          />
        </div>
      </div>
    </div>
  );
}
