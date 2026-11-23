/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { initPromise } from "@plane/i18n";
import { startTransition, StrictMode } from "react";
import { hydrateRoot } from "react-dom/client";
import { HydratedRouter } from "react-router/dom";

import polyfills from "@/lib/polyfills";
import { installConsoleCapture } from "@/lib/support/console-capture";
import { installGlobalErrorReporting } from "@/lib/support/report-client-error";
import { installStaleChunkReload } from "@/lib/support/reload-on-stale-chunk";
import { retireLegacyServiceWorker } from "@/lib/support/retire-service-worker";

void polyfills;

installConsoleCapture();
installGlobalErrorReporting();
installStaleChunkReload();
void retireLegacyServiceWorker();

// Initialize i18n before hydrating (the remix-i18next pattern for React
// Router: await init, then hydrateRoot). Hydrating before the instance is
// ready would make the first client render diverge from the prerendered
// shell, and React 19 leaves DOM it could not adopt in place instead of
// clearing it.
void initPromise
  .catch(() => {})
  .then(() => {
    startTransition(() => {
      hydrateRoot(
        document,
        <StrictMode>
          <HydratedRouter />
        </StrictMode>
      );
    });
  });
