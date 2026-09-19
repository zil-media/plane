/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useState } from "react";
import { observer } from "mobx-react";
import { Bug, HelpCircle, LifeBuoy, Lightbulb } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslation } from "@plane/i18n";
// ui
import { CustomMenu } from "@plane/ui";
// components
import { AppSidebarItem } from "@/components/sidebar/sidebar-item";
import { openBugReporter, openFeatureSuggest } from "@/components/support/events";
// hooks
import { usePowerK } from "@/hooks/store/use-power-k";
// plane web components
import { PlaneVersionNumber } from "@/plane-web/components/global";

export const HelpMenuRoot = observer(function HelpMenuRoot() {
  // store hooks
  const { t } = useTranslation();
  const { toggleShortcutsListModal } = usePowerK();
  const { workspaceSlug } = useParams();
  // states
  const [isNeedHelpOpen, setIsNeedHelpOpen] = useState(false);

  return (
    <>
      <CustomMenu
        customButton={
          <AppSidebarItem
            variant="button"
            item={{
              icon: <HelpCircle className="size-5" />,
              isActive: isNeedHelpOpen,
            }}
          />
        }
        // customButtonClassName="relative grid place-items-center rounded-md p-1.5 outline-none"
        menuButtonOnClick={() => !isNeedHelpOpen && setIsNeedHelpOpen(true)}
        onMenuClose={() => setIsNeedHelpOpen(false)}
        placement="bottom-end"
        maxHeight="lg"
        closeOnSelect
      >
        <CustomMenu.MenuItem>
          <button type="button" onClick={openBugReporter} className="flex w-full items-center gap-2 hover:bg-layer-1">
            <Bug className="size-3.5" />
            <span className="text-11">{t("helpdesk.menu.report_problem")}</span>
          </button>
        </CustomMenu.MenuItem>
        <CustomMenu.MenuItem>
          <button
            type="button"
            onClick={openFeatureSuggest}
            className="flex w-full items-center gap-2 hover:bg-layer-1"
          >
            <Lightbulb className="size-3.5" />
            <span className="text-11">{t("helpdesk.menu.suggest_improvement")}</span>
          </button>
        </CustomMenu.MenuItem>
        {workspaceSlug && (
          <CustomMenu.MenuItem>
            <Link href={`/${workspaceSlug.toString()}/support`} className="flex w-full items-center gap-2">
              <LifeBuoy className="size-3.5" />
              <span className="text-11">{t("helpdesk.menu.my_tracking")}</span>
            </Link>
          </CustomMenu.MenuItem>
        )}
        <CustomMenu.MenuItem>
          <button
            type="button"
            onClick={() => toggleShortcutsListModal(true)}
            className="justify-sbg-layer-211 flex w-full items-center hover:bg-layer-1"
          >
            <span className="text-11">{t("keyboard_shortcuts")}</span>
          </button>
        </CustomMenu.MenuItem>
        <div className="mt-1 border-t border-subtle px-1 pt-2 text-11 text-secondary">
          <PlaneVersionNumber />
        </div>
      </CustomMenu>
    </>
  );
});
