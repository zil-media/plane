/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useState } from "react";
import { BugReporter } from "./bug-reporter";
import { OPEN_BUG_REPORTER_EVENT, OPEN_FEATURE_SUGGEST_EVENT } from "./events";
import { FeatureSuggestModal } from "./feature-suggest-modal";

type Props = { workspaceSlug: string };

/** Mounted once per workspace; the help menu and error screens open it through window events. */
export function SupportRoot({ workspaceSlug }: Props) {
  const [reporterOpen, setReporterOpen] = useState(false);
  const [suggestOpen, setSuggestOpen] = useState(false);

  useEffect(() => {
    const openReporter = () => setReporterOpen(true);
    const openSuggest = () => setSuggestOpen(true);
    window.addEventListener(OPEN_BUG_REPORTER_EVENT, openReporter);
    window.addEventListener(OPEN_FEATURE_SUGGEST_EVENT, openSuggest);
    return () => {
      window.removeEventListener(OPEN_BUG_REPORTER_EVENT, openReporter);
      window.removeEventListener(OPEN_FEATURE_SUGGEST_EVENT, openSuggest);
    };
  }, []);

  const closeReporter = useCallback(() => setReporterOpen(false), []);
  const closeSuggest = useCallback(() => setSuggestOpen(false), []);

  return (
    <>
      <BugReporter isOpen={reporterOpen} onClose={closeReporter} workspaceSlug={workspaceSlug} />
      <FeatureSuggestModal isOpen={suggestOpen} onClose={closeSuggest} workspaceSlug={workspaceSlug} />
    </>
  );
}
