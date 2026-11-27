/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams, useRouter } from "next/navigation";
import { Link } from "react-router";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { SitesPortalService } from "@plane/services";
import { Input } from "@plane/ui";
// components
import { AuthBanner } from "@/components/account/auth-forms/auth-banner";
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PortalAuthLayout } from "@/components/portal/auth-layout";
import { portalUnit } from "@/components/portal/brand-theme";
// hooks
import { EErrorAlertType } from "@/helpers/authentication.helper";
import type { EAuthenticationErrorCodes } from "@/helpers/authentication.helper";
import { useUser } from "@/hooks/store/use-user";

const portalService = new SitesPortalService();

/** The invitation link: choose a password once, then straight to the calendar. */
const PortalInvitePage = observer(function PortalInvitePage() {
  const { t } = useTranslation();
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const { fetchCurrentUser } = useUser();
  const { data: invite, error } = useSWR(`PORTAL_INVITE_${token}`, () => portalService.invite(token), {
    shouldRetryOnError: false,
    revalidateOnFocus: false,
  });
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const accept = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    if (invite?.needs_password && password !== confirm) {
      setFailure(t("zil_portal.invite.mismatch"));
      return;
    }
    setSubmitting(true);
    setFailure(null);
    try {
      const { project_id, sign_in } = await portalService.acceptInvite(token, password);
      if (sign_in && invite) {
        const next = encodeURIComponent(`/portal/${project_id}`);
        setSubmitting(false);
        router.replace(`/portal/login?email=${encodeURIComponent(invite.email)}&next_path=${next}`);
        return;
      }
      await fetchCurrentUser();
      router.replace(`/portal/${project_id}`);
    } catch (err) {
      const status = (err as { status?: number } | undefined)?.status;
      setFailure(status === 400 ? t("zil_portal.invite.weak") : t("zil_portal.invite.invalid"));
      setSubmitting(false);
    }
  };

  if (!invite && !error)
    return (
      <div className="flex h-screen w-full items-center justify-center bg-surface-1">
        <LogoSpinner />
      </div>
    );

  return (
    <PortalAuthLayout unit={portalUnit(invite?.unit)}>
      <div className="flex flex-col gap-6">
        {error || !invite ? (
          <div className="text-center">
            <h1 className="text-2xl font-semibold text-primary">{t("zil_portal.invite.expired_title")}</h1>
            <p className="text-sm mt-1 text-secondary">
              {t("zil_portal.invite.expired_text")}{" "}
              <Link to="/portal/login" className="text-accent-primary hover:underline">
                {t("zil_portal.invite.sign_in_link")}
              </Link>
              .
            </p>
          </div>
        ) : (
          <form onSubmit={accept} className="space-y-4">
            {/* Ops' sign-in copy: centered title and subtitle */}
            <div className="mb-2 text-center">
              <h1 className="text-2xl font-semibold text-primary">
                {t("zil_portal.invite.title", { brand: invite.brand })}
              </h1>
              <p className="text-sm mt-1 text-secondary">
                {invite.needs_password
                  ? t("zil_portal.invite.choose_password", { email: invite.email })
                  : t("zil_portal.invite.enter_as", { email: invite.email })}
              </p>
            </div>
            {invite.needs_password && (
              <>
                <div className="space-y-1">
                  <label className="text-13 font-medium text-tertiary" htmlFor="password">
                    {t("password")}
                  </label>
                  <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="new-password"
                    className="h-10 w-full"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-13 font-medium text-tertiary" htmlFor="confirm">
                    {t("zil_portal.invite.repeat_password")}
                  </label>
                  <Input
                    id="confirm"
                    type="password"
                    value={confirm}
                    onChange={(event) => setConfirm(event.target.value)}
                    autoComplete="new-password"
                    className="h-10 w-full"
                    required
                  />
                </div>
              </>
            )}
            {failure && (
              <AuthBanner
                bannerData={{
                  type: EErrorAlertType.BANNER_ALERT,
                  code: "" as EAuthenticationErrorCodes,
                  title: "",
                  message: failure,
                }}
                handleBannerData={() => setFailure(null)}
              />
            )}
            <Button
              type="submit"
              variant="primary"
              size="xl"
              className="w-full"
              disabled={submitting || (invite.needs_password && (!password || !confirm))}
            >
              {submitting ? t("zil_portal.invite.submitting") : t("zil_portal.invite.submit")}
            </Button>
          </form>
        )}
      </div>
    </PortalAuthLayout>
  );
});

export default PortalInvitePage;
