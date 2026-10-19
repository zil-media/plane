/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
// components
import { PageHead } from "@/components/core/page-title";
import { ZilMyBrands } from "@/components/zil-brand/my-brands";

function WorkspaceMyBrandsPage() {
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  if (!workspaceSlug) return null;
  return (
    <>
      <PageHead title={t("sidebar.my_brands")} />
      <div className="relative h-full w-full overflow-hidden overflow-y-auto">
        <ZilMyBrands workspaceSlug={workspaceSlug.toString()} />
      </div>
    </>
  );
}

export default observer(WorkspaceMyBrandsPage);
