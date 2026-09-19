/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import { PageHead } from "@/components/core/page-title";
import { SupportBoard } from "@/components/support/board/root";

export default function WorkspaceSupportPage() {
  const { t } = useTranslation();
  return (
    <>
      <PageHead title={t("helpdesk.board.title")} />
      <div className="relative h-full w-full overflow-hidden">
        <SupportBoard />
      </div>
    </>
  );
}
