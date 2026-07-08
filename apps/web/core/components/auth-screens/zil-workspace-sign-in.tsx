/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@plane/propel/button";
import { AuthBanner } from "@/components/account/auth-forms/auth-banner";
import { LogoSpinner } from "@/components/common/logo-spinner";
import { authErrorHandler, type EAuthenticationErrorCodes } from "@/helpers/authentication.helper";

// Base URL of Zil Workspace (owns identity + the SSO endpoints). Prefer an
// explicit VITE_ZIL_URL; otherwise derive it from the host so it works both in
// local dev (Workspace on :3000) and prod (workspace.zil.global) with no build
// config. The Workspace origin owns the session cookie, so the /api/sso/* calls
// must target it (its dev server proxies /api to the Express backend).
function resolveZilUrl(): string {
  const envUrl = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_ZIL_URL;
  if (envUrl) return envUrl.replace(/\/+$/, "");
  if (typeof window !== "undefined") {
    const { protocol, hostname, port } = window.location;
    if (hostname === "localhost" || hostname === "127.0.0.1") return "http://localhost:3000";
    // Derive the Workspace host from the Ops host by swapping the leading
    // "ops." label for "workspace." — keeps environments isolated
    // (ops.zil.global → workspace.zil.global, ops.staging.zil.global →
    // workspace.staging.zil.global) instead of hardcoding production.
    if (hostname.startsWith("ops.")) return `${protocol}//workspace.${hostname.slice(4)}`;
    // Unrecognized host with no VITE_ZIL_URL: do NOT silently assume prod
    // (that would cross a misconfigured staging into the prod Workspace).
    // Fail loudly and stay same-origin.
    // eslint-disable-next-line no-console
    console.error("[Ops SSO] VITE_ZIL_URL is not set and host is not recognized:", hostname);
    return `${protocol}//${hostname}${port ? `:${port}` : ""}`;
  }
  return "";
}

const ZIL_URL: string = resolveZilUrl();

// Where the SSO bounce sends the user after logging into Workspace: the Ops
// launcher, which mints the token and drops them back into Plane.
const WORKSPACE_LOGIN_URL = `${ZIL_URL}/login?redirect=/dashboard/ops`;
const SSO_MINT_URL = `${ZIL_URL}/api/sso/plane`;

type State = { status: "checking" } | { status: "session"; name: string; email: string } | { status: "none" };

/**
 * Sign-in for Ops. Identity lives in Zil Workspace, so we never collect
 * credentials here. On mount we ask Workspace (with the browser's cookies)
 * whether this device already has a session:
 *   - yes  → offer one-click "continue as <user>"
 *   - no   → send them to the Workspace login, which returns them here
 */
export function ZilWorkspaceSignIn() {
  const [state, setState] = useState<State>({ status: "checking" });
  // The SSO bounce (ZilSSOEndpoint) redirects failures back here with
  // ?error_code=<code> (invalid/reused/expired token, missing shared secret,
  // etc). Surface it — otherwise the user just lands back on the button with
  // no explanation of why the round-trip through Zil Workspace failed.
  const searchParams = useSearchParams();
  const errorCode = searchParams.get("error_code");
  const [dismissedError, setDismissedError] = useState(false);
  const errorInfo = !dismissedError && errorCode ? authErrorHandler(errorCode as EAuthenticationErrorCodes) : undefined;

  useEffect(() => {
    let active = true;
    const check = async () => {
      if (!ZIL_URL) {
        if (active) setState({ status: "none" });
        return;
      }
      try {
        const res = await fetch(`${ZIL_URL}/api/sso/check`, {
          credentials: "include",
          headers: { Accept: "application/json" },
        });
        if (!active) return;
        if (res.ok) {
          const data = await res.json();
          setState({
            status: "session",
            name: data?.user?.name || "",
            email: data?.user?.email || "",
          });
        } else {
          setState({ status: "none" });
        }
      } catch {
        if (active) setState({ status: "none" });
      }
    };
    check();
    return () => {
      active = false;
    };
  }, []);

  const goContinue = () => {
    window.location.href = SSO_MINT_URL;
  };
  const goLogin = () => {
    window.location.href = WORKSPACE_LOGIN_URL;
  };

  return (
    <div className="flex flex-1 flex-col items-center justify-center py-10">
      <div className="w-full max-w-sm text-center">
        {errorInfo && (
          <div className="mb-6 text-left">
            <AuthBanner message={errorInfo.message} handleBannerData={() => setDismissedError(true)} />
          </div>
        )}

        {state.status === "checking" && (
          <div className="flex flex-col items-center gap-4 text-secondary">
            <LogoSpinner />
            <p className="text-sm">Verificando tu sesión de Zil Workspace…</p>
          </div>
        )}

        {state.status === "session" && (
          <div className="flex flex-col items-center gap-6">
            <div>
              <h1 className="text-2xl font-semibold text-primary">Acceder a Ops</h1>
              <p className="text-sm mt-1 text-secondary">Continuá con tu cuenta de Zil Workspace.</p>
            </div>
            <div className="w-full rounded-lg border border-subtle bg-surface-2 px-4 py-3 text-left">
              <p className="text-sm font-medium text-primary">{state.name || state.email}</p>
              {state.name && <p className="text-xs text-secondary">{state.email}</p>}
            </div>
            <div className="flex w-full flex-col gap-2">
              <Button variant="primary" size="lg" className="w-full" onClick={goContinue}>
                Continuar como {state.name || state.email}
              </Button>
              <button type="button" onClick={goLogin} className="text-xs text-secondary hover:text-primary">
                Usar otra cuenta
              </button>
            </div>
          </div>
        )}

        {state.status === "none" && (
          <div className="flex flex-col items-center gap-6">
            <div>
              <h1 className="text-2xl font-semibold text-primary">Acceder a Ops</h1>
              <p className="text-sm mt-1 text-secondary">
                Iniciá sesión con tu cuenta de Zil Workspace para continuar.
              </p>
            </div>
            <Button variant="primary" size="lg" className="w-full" onClick={goLogin}>
              Continuar con Zil Workspace
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
