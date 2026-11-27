/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { observer } from "mobx-react";
import { useRouter, useSearchParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
import { API_BASE_URL, WEB_URL } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { AuthService } from "@plane/services";
import { Input } from "@plane/ui";
import { isValidNextPath } from "@plane/utils";
// components
import { AuthBanner } from "@/components/account/auth-forms/auth-banner";
import { PortalAuthLayout } from "@/components/portal/auth-layout";
import { EErrorAlertType } from "@/helpers/authentication.helper";
import type { EAuthenticationErrorCodes } from "@/helpers/authentication.helper";
// hooks
import { useUser } from "@/hooks/store/use-user";

const authService = new AuthService();

/** The portal's sign-in: email and password, nothing else. */
const PortalLoginPage = observer(function PortalLoginPage() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { data: currentUser, isAuthenticated } = useUser();
  const formRef = useRef<HTMLFormElement>(null);
  const requested = searchParams.get("next_path") ?? "";
  // back into the portal, never to this page again (a loop once signed in)
  const nextPath =
    requested.startsWith("/portal") && !requested.startsWith("/portal/login") && isValidNextPath(requested)
      ? requested
      : "/portal";
  const failed = !!searchParams.get("error_code");
  const [email, setEmail] = useState(searchParams.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [unreachable, setUnreachable] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (currentUser && isAuthenticated) router.replace(nextPath);
  }, [currentUser, isAuthenticated, nextPath, router]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!formRef.current || submitting) return;
    setSubmitting(true);
    const token = await authService.requestCSRFToken().catch(() => undefined);
    if (!token?.csrf_token) {
      setUnreachable(true);
      setSubmitting(false);
      return;
    }
    formRef.current.querySelector("input[name=csrfmiddlewaretoken]")?.setAttribute("value", token.csrf_token);
    formRef.current.submit();
  };

  const banner = unreachable
    ? t("zil_portal.login.unreachable")
    : failed && !dismissed
      ? t("zil_portal.login.wrong_credentials")
      : undefined;

  return (
    <PortalAuthLayout unit="zil">
      <div className="flex flex-col gap-6">
        {/* Ops' sign-in copy: centered title and subtitle */}
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-primary">{t("zil_portal.login.title")}</h1>
          <p className="text-sm mt-1 text-secondary">{t("zil_portal.login.subtitle")}</p>
        </div>
        {banner && (
          <AuthBanner
            bannerData={{
              type: EErrorAlertType.BANNER_ALERT,
              code: (searchParams.get("error_code") ?? "") as EAuthenticationErrorCodes,
              title: "",
              message: banner,
            }}
            handleBannerData={() => {
              setUnreachable(false);
              setDismissed(true);
            }}
          />
        )}
        <form
          ref={formRef}
          method="POST"
          action={`${API_BASE_URL}/auth/spaces/sign-in/`}
          onSubmit={submit}
          className="space-y-4"
        >
          <input type="hidden" name="csrfmiddlewaretoken" />
          <input type="hidden" name="next_path" value={nextPath} />
          <div className="space-y-1">
            <label className="text-13 font-medium text-tertiary" htmlFor="email">
              {t("email")}
            </label>
            <Input
              id="email"
              name="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              className="h-10 w-full"
              required
            />
          </div>
          <div className="space-y-1">
            <label className="text-13 font-medium text-tertiary" htmlFor="password">
              {t("password")}
            </label>
            <Input
              id="password"
              name="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              className="h-10 w-full"
              required
            />
          </div>
          <Button
            type="submit"
            variant="primary"
            size="xl"
            className="w-full"
            disabled={!email || !password || submitting}
          >
            {submitting ? t("zil_portal.login.submitting") : t("zil_portal.login.submit")}
          </Button>
        </form>
        <a
          href={`${WEB_URL}/accounts/forgot-password`}
          className="block text-center text-13 text-secondary hover:text-primary"
        >
          {t("zil_portal.login.forgot")}
        </a>
      </div>
    </PortalAuthLayout>
  );
});

export default PortalLoginPage;
