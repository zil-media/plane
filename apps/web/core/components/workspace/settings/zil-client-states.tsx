/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { AlertModalCore, CustomSelect } from "@plane/ui";
import { renderFormattedDate } from "@plane/utils";
// services
import { zilClientStatesService } from "@/services/zil-client-states.service";

type Props = { workspaceSlug: string };

/**
 * Lets a workspace admin give every client (brand) project the states of a team project:
 * work items move to the equivalent state and new clients are born with them.
 */
export const ZilClientStatesSettings = observer(function ZilClientStatesSettings(props: Props) {
  const { workspaceSlug } = props;
  const { t } = useTranslation();
  // states
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  // data
  const { data: settings, mutate: mutateSettings } = useSWR(["ZIL_CLIENT_STATES", workspaceSlug], () =>
    zilClientStatesService.fetchSettings(workspaceSlug)
  );
  const projectId = selectedId ?? settings?.template_project_id ?? null;
  const { data: previewData } = useSWR(projectId ? ["ZIL_CLIENT_STATES_PREVIEW", workspaceSlug, projectId] : null, () =>
    projectId ? zilClientStatesService.fetchSettings(workspaceSlug, projectId) : null
  );

  if (!settings) return null;

  const project = settings.projects.find((item) => item.id === projectId);
  const preview = previewData?.preview ?? null;

  const handleApply = async () => {
    if (!projectId) return;
    setIsApplying(true);
    try {
      const response = await zilClientStatesService.apply(workspaceSlug, projectId);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: t("workspace_settings.settings.client_states.success_title"),
        message: t("workspace_settings.settings.client_states.success_message", {
          updated: response.result?.updated ?? 0,
          moved: response.result?.work_items_moved ?? 0,
        }),
      });
      setIsConfirmOpen(false);
      setSelectedId(null);
      await mutateSettings();
    } catch (error) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("toast.error"),
        message:
          (error as { error?: string } | undefined)?.error ?? t("workspace_settings.settings.client_states.error"),
      });
    } finally {
      setIsApplying(false);
    }
  };

  return (
    <div className="mt-10 flex flex-col gap-4 border-t border-subtle pt-8">
      <div className="flex flex-col gap-1">
        <h3 className="text-h5-semibold">{t("workspace_settings.settings.client_states.title")}</h3>
        <p className="text-body-sm-regular text-tertiary">
          {t("workspace_settings.settings.client_states.description")}
        </p>
      </div>
      {settings.projects.length === 0 ? (
        <p className="text-body-sm-regular text-tertiary">
          {t("workspace_settings.settings.client_states.no_projects")}
        </p>
      ) : (
        <>
          <div className="flex max-w-md flex-col gap-2">
            <h4 className="text-body-sm-medium text-tertiary">
              {t("workspace_settings.settings.client_states.model_label")}
            </h4>
            <CustomSelect
              value={projectId}
              onChange={(value: string) => setSelectedId(value)}
              label={project?.name ?? t("workspace_settings.settings.client_states.select_placeholder")}
              buttonClassName="border border-subtle bg-layer-2 !shadow-none !rounded-md"
              input
            >
              {settings.projects.map((item) => (
                <CustomSelect.Option key={item.id} value={item.id}>
                  {item.name}
                </CustomSelect.Option>
              ))}
            </CustomSelect>
          </div>
          {project && (
            <div className="flex flex-col gap-2">
              <h4 className="text-body-sm-medium text-tertiary">
                {t("workspace_settings.settings.client_states.states_label")}
              </h4>
              <div className="flex flex-wrap gap-2">
                {project.states.map((state) => (
                  <span
                    key={state.name}
                    className="flex items-center gap-1.5 rounded-md border border-subtle px-2 py-1 text-body-xs-regular"
                  >
                    <span className="size-2 rounded-full" style={{ backgroundColor: state.color }} />
                    {state.name}
                  </span>
                ))}
              </div>
            </div>
          )}
          {preview && (
            <p className="text-body-sm-regular text-secondary">
              {t("workspace_settings.settings.client_states.preview", {
                clients: preview.clients,
                items: preview.work_items_to_move,
              })}
            </p>
          )}
          {settings.applied_at && (
            <p className="text-body-xs-regular text-tertiary">
              {t("workspace_settings.settings.client_states.last_applied", {
                date: renderFormattedDate(settings.applied_at) ?? "",
              })}
            </p>
          )}
          <div>
            <Button variant="primary" size="lg" disabled={!project} onClick={() => setIsConfirmOpen(true)}>
              {t("workspace_settings.settings.client_states.apply")}
            </Button>
          </div>
        </>
      )}
      <AlertModalCore
        isOpen={isConfirmOpen}
        handleClose={() => setIsConfirmOpen(false)}
        handleSubmit={() => {
          void handleApply();
        }}
        isSubmitting={isApplying}
        variant="primary"
        title={t("workspace_settings.settings.client_states.confirm_title")}
        content={t("workspace_settings.settings.client_states.confirm_content", { project: project?.name ?? "" })}
        primaryButtonText={{
          loading: t("workspace_settings.settings.client_states.applying"),
          default: t("workspace_settings.settings.client_states.apply"),
        }}
        secondaryButtonText={t("cancel")}
      />
    </div>
  );
});
