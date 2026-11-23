/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { Rocket } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { nextDeployWindow } from "./phase";

/** The next real deploy window with a countdown; ticks on its own every 30s. */
export function DeployCountdown() {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const window = nextDeployWindow(now);
  const minutesLeft = Math.max(0, Math.round((window.getTime() - now.getTime()) / 60_000));
  const time = window.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const today = window.toDateString() === now.toDateString();
  const left = t("helpdesk.deploy.left", {
    hours: String(Math.floor(minutesLeft / 60)),
    minutes: String(minutesLeft % 60),
  });

  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-success-strong bg-success-subtle px-2 py-0.5 text-caption-sm-regular whitespace-nowrap text-success-primary">
      <Rocket className="size-3 shrink-0" />
      {t(today ? "helpdesk.deploy.today" : "helpdesk.deploy.tomorrow", { time, left })}
    </span>
  );
}
