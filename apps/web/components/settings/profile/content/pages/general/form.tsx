/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Avatar } from "@makeplane/propel/components/avatar";
import { InputField } from "@makeplane/propel/components/input-field";
import { useTranslation } from "@plane/i18n";
import { Button } from "@makeplane/propel/components/button";
import type { IUser, TUserProfile } from "@plane/types";

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
      <div className="flex w-full flex-col gap-6">
        <div className="relative h-[149px] w-full overflow-hidden rounded-lg bg-layer-2">
          <CoverImage
            src={user.cover_image_url || ""}
            className="absolute inset-0 size-full"
            alt={user.first_name || "Cover image"}
          />
          <div className="absolute inset-0 bg-gradient-to-b from-black/10 to-black/70" />
          <div className="absolute inset-x-4 bottom-4 z-5 flex h-10 items-end justify-between gap-2">
            <div className="flex min-w-0 items-center gap-3">
              <Avatar
                size="xl"
                src={user.avatar_url ? getFileURL(user.avatar_url) : undefined}
                alt={user.display_name}
              />
              <div className="flex min-w-0 flex-col text-on-color">
                <span className="truncate text-body-sm-medium">{`${user.first_name} ${user.last_name}`}</span>
                <span className="truncate text-body-xs-regular">{user.email}</span>
              </div>
            </div>
          </div>
        </div>
        <p className="text-body-xs-regular text-tertiary">
          {t("account_settings.profile.identity_managed_by_zil_workspace")}
        </p>
        <div className="grid grid-cols-1 gap-x-8 gap-y-6 sm:grid-cols-2">
          <InputField
            size="lg"
            orientation="vertical"
            id="first_name"
            name="first_name"
            type="text"
            label={t("first_name")}
            value={user.first_name}
            disabled
          />
          <InputField
            size="lg"
            orientation="vertical"
            id="last_name"
            name="last_name"
            type="text"
            label={t("last_name")}
            value={user.last_name}
            disabled
          />
          <InputField
            size="lg"
            orientation="vertical"
            id="display_name"
            name="display_name"
            type="text"
            label={t("display_name")}
            value={user.display_name}
            disabled
          />
          <InputField
            size="lg"
            orientation="vertical"
            id="email"
            name="email"
            type="email"
            label={t("auth.common.email.label")}
            value={user.email}
            disabled
          />
        </div>
      </div>
      <div className="mt-10">
        <SettingsBoxedControlItem
          title={t("deactivate_account")}
          description={t("deactivate_account_description")}
          control={
            <Button
              variant="danger-outline"
              size="sm"
              stretch="auto"
              label={t("deactivate_account")}
              onClick={() => setDeactivateAccountModal(true)}
            />
          }
        />
      </div>
    </>
  );
});
