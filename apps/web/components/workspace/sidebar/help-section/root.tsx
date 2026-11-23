/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Bug, LifeBuoy, Lightbulb } from "lucide-react";
import { HelpOutline } from "@makeplane/propel/icons";
import { useTranslation } from "@plane/i18n";
// ui
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { IconButton } from "@makeplane/propel/elements/icon-button";
// components
import { ATTENTION_KEYS, AttentionDot, useAttention } from "@/components/common/attention-highlight";
import { openBugReporter, openFeatureSuggest } from "@/components/support/events";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
import { usePowerK } from "@/hooks/store/use-power-k";

export const HelpMenuRoot = observer(function HelpMenuRoot() {
  // store hooks
  const { t } = useTranslation();
  const { toggleShortcutsListModal } = usePowerK();
  const { workspaceSlug } = useParams();
  const router = useAppRouter();
  // Support is new: the icon and the entry stay highlighted until the person opens it once.
  const supportBoard = useAttention(ATTENTION_KEYS.supportBoard);

  return (
    <Menu>
      <Tooltip label={t("power_k.group_titles.help")} side="bottom">
        <MenuTrigger
          render={
            <IconButton
              variant="ghost"
              size="md"
              aria-label={t("power_k.group_titles.help")}
              render={<button type="button" className="data-popup-open:bg-layer-transparent-active" />}
            >
              <AttentionDot active={supportBoard.isNew}>
                <HelpOutline className="size-4.5" />
              </AttentionDot>
            </IconButton>
          }
        />
      </Tooltip>
      <MenuContent side="bottom" align="end">
        <MenuItem
          icon={<Bug className="size-3.5" />}
          label={t("helpdesk.menu.report_problem")}
          onClick={openBugReporter}
        />
        <MenuItem
          icon={<Lightbulb className="size-3.5" />}
          label={t("helpdesk.menu.suggest_improvement")}
          onClick={openFeatureSuggest}
        />
        {workspaceSlug && (
          <MenuItem
            icon={<LifeBuoy className="size-3.5" />}
            label={t("helpdesk.menu.my_tracking")}
            trailing={
              supportBoard.isNew ? (
                <AttentionDot active>
                  <span className="inline-block size-2.5" />
                </AttentionDot>
              ) : undefined
            }
            onClick={() => {
              supportBoard.dismiss();
              router.push(`/${workspaceSlug.toString()}/support`);
            }}
          />
        )}
        <MenuItem label={t("keyboard_shortcuts")} onClick={() => toggleShortcutsListModal(true)} />
      </MenuContent>
    </Menu>
  );
});
