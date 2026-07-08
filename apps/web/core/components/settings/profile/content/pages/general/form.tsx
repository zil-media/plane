/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { CircleUserRound } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import type { IUser, TUserProfile } from "@plane/types";
import { Input } from "@plane/ui";
import { getFileURL } from "@plane/utils";
// components
import { DeactivateAccountModal } from "@/components/account/deactivate-account-modal";
import { CoverImage } from "@/components/common/cover-image";
import { SettingsBoxedControlItem } from "@/components/settings/boxed-control-item";

type Props = {
  user: IUser;
  profile: TUserProfile;
};

// Identity (name, avatar, cover, email) is owned by Zil Workspace and pushed
// into Ops via SSO — this panel is a read-only mirror, not an editor. Only
// account deactivation (an Ops-local action) stays interactive.
export const GeneralProfileSettingsForm = observer(function GeneralProfileSettingsForm(props: Props) {
  const { user } = props;
  // language support
  const { t } = useTranslation();
  // states
  const [deactivateAccountModal, setDeactivateAccountModal] = useState(false);

  return (
    <>
      <DeactivateAccountModal isOpen={deactivateAccountModal} onClose={() => setDeactivateAccountModal(false)} />
      <div className="flex w-full flex-col gap-7">
        <div className="relative h-44 w-full">
          <CoverImage
            src={user.cover_image_url || ""}
            className="h-44 w-full rounded-lg"
            alt={user.first_name || "Cover image"}
          />
          <div className="absolute -bottom-6 left-6 flex items-end justify-between">
            <div className="flex gap-3">
              <div className="flex h-16 w-16 items-center justify-center rounded-lg bg-surface-2">
                {!user.avatar_url || user.avatar_url === "" ? (
                  <div className="h-16 w-16 rounded-md bg-layer-1 p-2">
                    <CircleUserRound className="h-full w-full text-secondary" />
                  </div>
                ) : (
                  <div className="relative h-16 w-16 overflow-hidden">
                    <img
                      src={getFileURL(user.avatar_url)}
                      className="absolute top-0 left-0 h-full w-full rounded-lg object-cover"
                      alt={user.display_name}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
        <div className="item-center mt-6 flex justify-between">
          <div className="flex flex-col">
            <div className="item-center flex text-16 font-medium text-secondary">
              <span>{`${user.first_name} ${user.last_name}`}</span>
            </div>
            <span className="text-13 tracking-tight text-tertiary">{user.email}</span>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <p className="text-13 text-tertiary">{t("account_settings.profile.identity_managed_by_zil_workspace")}</p>
          <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-3">
            <div className="flex flex-col gap-1">
              <h4 className="text-13 font-medium text-secondary">{t("first_name")}</h4>
              <Input
                id="first_name"
                name="first_name"
                type="text"
                value={user.first_name}
                className="w-full cursor-not-allowed rounded-md !bg-surface-2"
                disabled
              />
            </div>
            <div className="flex flex-col gap-1">
              <h4 className="text-13 font-medium text-secondary">{t("last_name")}</h4>
              <Input
                id="last_name"
                name="last_name"
                type="text"
                value={user.last_name}
                className="w-full cursor-not-allowed rounded-md !bg-surface-2"
                disabled
              />
            </div>
            <div className="flex flex-col gap-1">
              <h4 className="text-13 font-medium text-secondary">{t("display_name")}</h4>
              <Input
                id="display_name"
                name="display_name"
                type="text"
                value={user.display_name}
                className="w-full cursor-not-allowed rounded-md !bg-surface-2"
                disabled
              />
            </div>
            <div className="flex flex-col gap-1">
              <h4 className="text-13 font-medium text-secondary">{t("auth.common.email.label")}</h4>
              <Input
                id="email"
                name="email"
                type="email"
                value={user.email}
                className="w-full cursor-not-allowed rounded-md !bg-surface-2"
                disabled
              />
            </div>
          </div>
        </div>
      </div>
      <div className="mt-10">
        <SettingsBoxedControlItem
          title={t("deactivate_account")}
          description={t("deactivate_account_description")}
          control={
            <Button variant="error-outline" onClick={() => setDeactivateAccountModal(true)}>
              {t("deactivate_account")}
            </Button>
          }
        />
      </div>
    </>
  );
});
