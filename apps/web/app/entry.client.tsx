/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { startTransition, StrictMode } from "react";
import { hydrateRoot } from "react-dom/client";
import { HydratedRouter } from "react-router/dom";

import polyfills from "@/lib/polyfills";
import { installConsoleCapture } from "@/lib/support/console-capture";
import { installGlobalErrorReporting } from "@/lib/support/report-client-error";
import { retireLegacyServiceWorker } from "@/lib/support/retire-service-worker";

void polyfills;

installConsoleCapture();
installGlobalErrorReporting();
void retireLegacyServiceWorker();

startTransition(() => {
  hydrateRoot(
    document,
    <StrictMode>
      <HydratedRouter />
    </StrictMode>
  );
});
