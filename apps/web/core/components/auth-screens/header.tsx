/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { useTranslation } from "@plane/i18n";
import { PlaneLockup } from "@plane/propel/icons";
import { PageHead } from "@/components/core/page-title";
import { EAuthModes } from "@/helpers/authentication.helper";

const authContentMap = {
  [EAuthModes.SIGN_IN]: {
    pageTitle: "Sign up",
  },
  [EAuthModes.SIGN_UP]: {
    pageTitle: "Sign in",
  },
};

type AuthHeaderProps = {
  type: EAuthModes;
};

export const AuthHeader = observer(function AuthHeader({ type }: AuthHeaderProps) {
  const { t } = useTranslation();

  return <AuthHeaderBase pageTitle={t(authContentMap[type].pageTitle)} />;
});

type TAuthHeaderBase = {
  pageTitle: string;
  additionalAction?: React.ReactNode;
};

export function AuthHeaderBase(props: TAuthHeaderBase) {
  const { pageTitle, additionalAction } = props;
  return (
    <>
      <PageHead title={pageTitle + " - Zil"} />
      <div className="sticky top-0 flex w-full flex-shrink-0 items-center justify-between gap-6 lg:justify-end">
        <Link href="/" className="lg:hidden">
          <PlaneLockup height={20} width={95} className="text-primary" />
        </Link>
        {additionalAction}
      </div>
    </>
  );
}
