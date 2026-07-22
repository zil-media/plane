/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// assets
import { ZilLogo } from "@/components/common/zil-logo";

type TPoweredBy = {
  disabled?: boolean;
};

export function PoweredBy(props: TPoweredBy) {
  // props
  const { disabled = false } = props;

  if (disabled) return null;

  return (
    <div className="fixed right-5 bottom-2.5 !z-[999999] flex items-center gap-1 rounded-sm border border-subtle bg-layer-3 px-2 py-1 shadow-raised-100">
      <ZilLogo className="h-3 w-auto text-primary" />
      <div className="text-11">
        Powered by <span className="font-semibold">Zil</span>
      </div>
    </div>
  );
}
