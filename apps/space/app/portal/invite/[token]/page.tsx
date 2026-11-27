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
import { Button } from "@plane/propel/button";
import { SitesPortalService } from "@plane/services";
import { Input } from "@plane/ui";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { ZilLogo } from "@/components/common/zil-logo";
// hooks
import { useUser } from "@/hooks/store/use-user";

const portalService = new SitesPortalService();

/** The invitation link: choose a password once, then straight to the calendar. */
const PortalInvitePage = observer(function PortalInvitePage() {
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
      setFailure("Las contraseñas no coinciden.");
      return;
    }
    setSubmitting(true);
    setFailure(null);
    try {
      const { project_id, sign_in } = await portalService.acceptInvite(token, password);
      if (sign_in && invite) {
        const next = encodeURIComponent(`/portal/${project_id}`);
        router.replace(`/portal/login?email=${encodeURIComponent(invite.email)}&next_path=${next}`);
        return;
      }
      await fetchCurrentUser();
      router.replace(`/portal/${project_id}`);
    } catch (err) {
      const status = (err as { status?: number } | undefined)?.status;
      setFailure(
        status === 400
          ? "Elegí una contraseña más segura: más larga, mezclando palabras, números o símbolos."
          : "Este link ya no funciona. Pedile a tu contacto en Zil que te lo reenvíe."
      );
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
    <div className="flex min-h-screen items-center justify-center bg-surface-1 px-4">
      <div className="w-full max-w-sm space-y-6">
        <ZilLogo className="h-6 w-auto text-primary" />
        {error || !invite ? (
          <div className="space-y-2">
            <h1 className="text-20 font-semibold text-primary">Este link ya no funciona</h1>
            <p className="text-14 text-secondary">
              Los links vencen a los 7 días y sirven una sola vez. Pedile a tu contacto en Zil que te lo reenvíe, o{" "}
              <Link to="/portal/login" className="text-accent-primary hover:underline">
                entrá con tu contraseña
              </Link>
              .
            </p>
          </div>
        ) : (
          <form onSubmit={accept} className="space-y-4">
            <div className="space-y-1">
              <h1 className="text-20 font-semibold text-primary">Tu calendario de {invite.brand}</h1>
              <p className="text-14 text-secondary">
                {invite.needs_password
                  ? `Elegí una contraseña para ${invite.email}. La vas a usar para volver a entrar.`
                  : `Entrá como ${invite.email}.`}
              </p>
            </div>
            {invite.needs_password && (
              <>
                <div className="space-y-1">
                  <label className="text-13 font-medium text-tertiary" htmlFor="password">
                    Contraseña
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
                    Repetí la contraseña
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
            {failure && <p className="text-13 text-danger-primary">{failure}</p>}
            <Button
              type="submit"
              variant="primary"
              size="xl"
              className="w-full"
              disabled={submitting || (invite.needs_password && (!password || !confirm))}
            >
              {submitting ? "Entrando…" : "Ver mi calendario"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
});

export default PortalInvitePage;
