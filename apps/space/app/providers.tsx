/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ThemeProvider } from "next-themes";
import { useLocation } from "react-router";
// components
import { TranslationProvider } from "@plane/i18n";
import { AppProgressBar } from "@/lib/b-progress";
import { InstanceProvider } from "@/lib/instance-provider";
import { StoreProvider } from "@/lib/store-provider";
import { ToastProvider } from "@/lib/toast-provider";

export function AppProviders({ children }: { children: React.ReactNode }) {
  // the brand client portal is always light (Zil brand)
  const { pathname } = useLocation();
  const forcedTheme = pathname.startsWith("/portal") ? "light" : undefined;
  return (
    <ThemeProvider themes={["light", "dark"]} defaultTheme="system" enableSystem forcedTheme={forcedTheme}>
      <StoreProvider>
        <AppProgressBar />
        <TranslationProvider>
          <ToastProvider>
            <InstanceProvider>{children}</InstanceProvider>
          </ToastProvider>
        </TranslationProvider>
      </StoreProvider>
    </ThemeProvider>
  );
}
