/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Controller, useForm } from "react-hook-form";
import useSWR from "swr";

// types
import { SPACE_BASE_PATH, SPACE_BASE_URL } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { IntakeService } from "@plane/services";
import { Button } from "@makeplane/propel/components/button";
import { GlobeOutline, IntakeOutline, NewTabOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
import type { TProjectPublishLayouts, TProjectPublishSettings } from "@plane/types";
// ui
import { Switch } from "@makeplane/propel/components/switch";
import { Select } from "@plane/blocks/select";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogInfo,
  DialogInfoIcon,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { Loader } from "@plane/blocks/skeleton";
// helpers
import { copyTextToClipboard } from "@plane/utils";
// hooks
import { useProjectPublish } from "@/hooks/store/use-project-publish";

const intakeService = new IntakeService();

type Props = {
  isOpen: boolean;
  projectId: string;
  onClose: () => void;
};

const defaultValues: Partial<TProjectPublishSettings> = {
  is_comments_enabled: false,
  is_reactions_enabled: false,
  is_votes_enabled: false,
  intake: null,
  view_props: {
    list: true,
    kanban: true,
  },
};

type TViewOption = {
  key: TProjectPublishLayouts;
  labelKey: string;
};

const VIEW_OPTIONS: TViewOption[] = [
  { key: "list", labelKey: "project_publish.view_options.list" },
  { key: "kanban", labelKey: "project_publish.view_options.kanban" },
];

export const PublishProjectModal = observer(function PublishProjectModal(props: Props) {
  const { isOpen, onClose, projectId } = props;
  // states
  const [isUnPublishing, setIsUnPublishing] = useState(false);
  // router
  const { workspaceSlug } = useParams();
  // i18n
  const { t } = useTranslation();
  // store hooks
  const {
    fetchPublishSettings,
    getPublishSettingsByProjectID,
    publishProject,
    updatePublishSettings,
    unPublishProject,
    fetchSettingsLoader,
  } = useProjectPublish();
  // derived values
  const projectPublishSettings = getPublishSettingsByProjectID(projectId);
  const isProjectPublished = !!projectPublishSettings?.anchor;
  // fetch the project's (default) intake so the intake toggle can wire it up to the public board
  const { data: projectIntake } = useSWR(
    workspaceSlug && isOpen ? `PROJECT_DEFAULT_INTAKE_${workspaceSlug}_${projectId}` : null,
    workspaceSlug && isOpen ? () => intakeService.retrieve(workspaceSlug.toString(), projectId) : null
  );
  // form info
  const {
    control,
    formState: { isDirty, isSubmitting },
    handleSubmit,
    reset,
    watch,
  } = useForm({
    defaultValues,
  });

  const handleClose = () => {
    onClose();
  };

  // fetch publish settings
  useEffect(() => {
    if (!workspaceSlug || !isOpen) return;

    if (!projectPublishSettings) {
      fetchPublishSettings(workspaceSlug.toString(), projectId);
    }
  }, [fetchPublishSettings, isOpen, projectId, projectPublishSettings, workspaceSlug]);

  const handlePublishProject = async (payload: Partial<TProjectPublishSettings>) => {
    if (!workspaceSlug) return;
    await publishProject(workspaceSlug.toString(), projectId, payload);
  };

  const handleUpdatePublishSettings = async (payload: Partial<TProjectPublishSettings>) => {
    if (!workspaceSlug || !payload.id) return;

    await updatePublishSettings(workspaceSlug.toString(), projectId, payload.id, payload).then((res) => {
      setToast({
        type: "success",
        title: t("toast.success"),
        message: t("project_publish.toasts.update_success"),
      });

      handleClose();
      return res;
    });
  };

  const handleUnPublishProject = async (publishId: string) => {
    if (!workspaceSlug || !publishId) return;

    setIsUnPublishing(true);

    await unPublishProject(workspaceSlug.toString(), projectId, publishId)
      .catch(() =>
        setToast({
          type: "error",
          title: t("toast.error"),
          message: t("project_publish.toasts.unpublish_error"),
        })
      )
      .finally(() => setIsUnPublishing(false));
  };

  const selectedLayouts = Object.entries(watch("view_props") ?? {})
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    .filter(([key, value]) => value)
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    .map(([key, value]) => key)
    .filter((l) => VIEW_OPTIONS.find((o) => o.key === l));

  const handleFormSubmit = async (formData: Partial<TProjectPublishSettings>) => {
    if (!selectedLayouts || selectedLayouts.length === 0) {
      setToast({
        type: "error",
        title: t("toast.error"),
        message: t("project_publish.errors.select_layout"),
      });
      return;
    }

    const payload: Partial<TProjectPublishSettings> = {
      id: formData.id,
      is_comments_enabled: formData.is_comments_enabled,
      is_reactions_enabled: formData.is_reactions_enabled,
      is_votes_enabled: formData.is_votes_enabled,
      intake: formData.intake ?? null,
      view_props: formData.view_props,
    };

    if (formData.id && isProjectPublished) await handleUpdatePublishSettings(payload);
    else await handlePublishProject(payload);
  };

  // prefill form values for already published projects
  useEffect(() => {
    if (!projectPublishSettings?.anchor) return;

    reset({
      ...defaultValues,
      ...projectPublishSettings,
    });
  }, [projectPublishSettings, reset]);

  const SPACE_APP_URL =
    (SPACE_BASE_URL.trim() === "" && typeof window !== "undefined" ? window.location.origin : SPACE_BASE_URL) +
    SPACE_BASE_PATH;
  const publishLink = `${SPACE_APP_URL}/issues/${projectPublishSettings?.anchor}`;

  const handleCopyLink = () =>
    copyTextToClipboard(publishLink).then(() =>
      setToast({
        type: "success",
        title: "",
        message: t("project_publish.toasts.link_copied"),
      })
    );

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <DialogContent size="md">
        <form onSubmit={handleSubmit(handleFormSubmit)} className="flex min-h-0 flex-1 flex-col">
          <DialogMain>
            <DialogHeader>
              <div className="flex items-center justify-between gap-2">
                <DialogHeading>
                  <DialogTitle>{t("project_publish.modal_title")}</DialogTitle>
                </DialogHeading>
                {isProjectPublished && (
                  <Button
                    variant="danger"
                    size="md"
                    stretch="auto"
                    label={isUnPublishing ? t("project_publish.unpublishing") : t("project_publish.unpublish")}
                    onClick={() => void handleUnPublishProject(watch("id") ?? "")}
                    loading={isUnPublishing}
                  />
                )}
              </div>
            </DialogHeader>

            {/* content */}
            <DialogBody>
              {fetchSettingsLoader ? (
                <Loader className="space-y-4">
                  <Loader.Item height="30px" />
                  <Loader.Item height="30px" />
                  <Loader.Item height="30px" />
                  <Loader.Item height="30px" />
                </Loader>
              ) : (
                <div className="space-y-4">
                  {isProjectPublished && projectPublishSettings && (
                    <>
                      <div className="flex items-center justify-between gap-2 rounded-md border border-strong py-1.5 pr-1 pl-4">
                        <a
                          href={publishLink}
                          className="truncate text-body-xs-regular text-secondary"
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {publishLink}
                        </a>
                        <div className="flex flex-shrink-0 items-center gap-1">
                          <a
                            href={publishLink}
                            aria-label="Open in new tab"
                            className="grid size-8 place-items-center rounded-sm bg-layer-3 hover:bg-layer-3-hover"
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            <NewTabOutline className="size-4" />
                          </a>
                          <button
                            type="button"
                            className="h-8 rounded-sm bg-layer-3 px-3 py-2 text-caption-sm-medium hover:bg-layer-3-hover"
                            onClick={() => void handleCopyLink()}
                          >
                            {t("project_publish.copy_link")}
                          </button>
                        </div>
                      </div>
                      <p className="mt-3 flex items-center gap-1 text-body-xs-medium text-accent-primary">
                        <span className="relative grid size-2.5 place-items-center">
                          <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent-primary opacity-75" />
                          <span className="relative inline-flex size-1.5 rounded-full bg-accent-primary" />
                        </span>
                        {t("project_publish.live_message")}
                      </p>
                    </>
                  )}
                  <div className="space-y-4">
                    <div className="relative flex items-center justify-between gap-2">
                      <div className="text-body-xs-regular">{t("project_publish.views")}</div>
                      <Controller
                        control={control}
                        name="view_props"
                        render={({ field: { onChange, value } }) => (
                          // `select-ghost-*` chrome is `w-full`; the shrink-0 wrapper keeps the
                          // trigger content-width inside the settings row, as the old button was.
                          <span className="flex shrink-0">
                            <Select<TViewOption>
                              multiple
                              getValues={() => VIEW_OPTIONS}
                              value={VIEW_OPTIONS.filter((o) => selectedLayouts.includes(o.key))}
                              onChange={(keys) => {
                                // The old dropdown refused to unset the last remaining layout; a
                                // publish needs at least one, so an empty selection is a no-op.
                                if (keys.length === 0) return;
                                onChange({
                                  ...value,
                                  ...Object.fromEntries(VIEW_OPTIONS.map((o) => [o.key, keys.includes(o.key)])),
                                });
                              }}
                              getOptionValue={(option) => option.key}
                              getOptionLabel={(option) => t(option.labelKey)}
                              showSearch={false}
                              pinSelected={false}
                            >
                              <Select.Trigger<TViewOption> variant="select-ghost-md">
                                {(options) => (
                                  <span className="min-w-0 grow truncate text-left">
                                    {options.map((o) => t(o.labelKey)).join(", ")}
                                  </span>
                                )}
                              </Select.Trigger>
                            </Select>
                          </span>
                        )}
                      />
                    </div>
                  </div>

                  {/* client access: comment / react / vote without a seat */}
                  <div className="space-y-3 rounded-md border border-subtle p-3">
                    <div className="text-body-xs-medium text-secondary">{t("project_publish.client_access.title")}</div>
                    <div className="relative flex items-center justify-between gap-4">
                      <div>
                        <div className="text-body-xs-regular">{t("project_publish.client_access.allow_comments")}</div>
                        <div className="text-caption-sm-regular text-tertiary">
                          {t("project_publish.client_access.allow_comments_description")}
                        </div>
                      </div>
                      <Controller
                        control={control}
                        name="is_comments_enabled"
                        render={({ field: { onChange, value } }) => (
                          <Switch
                            size="sm"
                            checked={!!value}
                            onCheckedChange={onChange}
                            aria-label={t("project_publish.client_access.allow_comments")}
                          />
                        )}
                      />
                    </div>
                    <div className="relative flex items-center justify-between gap-4">
                      <div>
                        <div className="text-body-xs-regular">{t("project_publish.client_access.allow_reactions")}</div>
                        <div className="text-caption-sm-regular text-tertiary">
                          {t("project_publish.client_access.allow_reactions_description")}
                        </div>
                      </div>
                      <Controller
                        control={control}
                        name="is_reactions_enabled"
                        render={({ field: { onChange, value } }) => (
                          <Switch
                            size="sm"
                            checked={!!value}
                            onCheckedChange={onChange}
                            aria-label={t("project_publish.client_access.allow_reactions")}
                          />
                        )}
                      />
                    </div>
                    <div className="relative flex items-center justify-between gap-4">
                      <div>
                        <div className="text-body-xs-regular">{t("project_publish.client_access.allow_voting")}</div>
                        <div className="text-caption-sm-regular text-tertiary">
                          {t("project_publish.client_access.allow_voting_description")}
                        </div>
                      </div>
                      <Controller
                        control={control}
                        name="is_votes_enabled"
                        render={({ field: { onChange, value } }) => (
                          <Switch
                            size="sm"
                            checked={!!value}
                            onCheckedChange={onChange}
                            aria-label={t("project_publish.client_access.allow_voting")}
                          />
                        )}
                      />
                    </div>
                  </div>

                  {/* client intake: accept new requests into Triage without a seat */}
                  <div className="space-y-3 rounded-md border border-subtle p-3">
                    <div className="relative flex items-center justify-between gap-4">
                      <div>
                        <div className="text-body-xs-medium text-secondary">
                          {t("project_publish.client_intake.toggle_title")}
                        </div>
                        <div className="text-caption-sm-regular text-tertiary">
                          {t("project_publish.client_intake.toggle_description")}
                        </div>
                      </div>
                      <Controller
                        control={control}
                        name="intake"
                        render={({ field: { onChange, value } }) => (
                          <Switch
                            size="sm"
                            checked={!!value}
                            onCheckedChange={(val) => onChange(val ? (projectIntake?.id ?? null) : null)}
                            disabled={!projectIntake?.id}
                            aria-label={t("project_publish.client_intake.toggle_title")}
                          />
                        )}
                      />
                    </div>
                    {watch("intake") && isProjectPublished && (
                      <div className="flex items-center gap-1.5 text-caption-sm-regular text-tertiary">
                        <IntakeOutline className="size-3 flex-shrink-0" />
                        {t("project_publish.client_intake.note")}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </DialogBody>
          </DialogMain>

          {/* modal handlers */}
          <DialogActions>
            <DialogInfo>
              <DialogInfoIcon>
                <GlobeOutline />
              </DialogInfoIcon>
              {t("project_publish.access_note")}
            </DialogInfo>
            {!fetchSettingsLoader && (
              <div className="relative flex items-center gap-2">
                <Button variant="secondary" size="md" stretch="auto" label={t("cancel")} onClick={handleClose} />
                {isProjectPublished ? (
                  isDirty && (
                    <Button
                      variant="primary"
                      size="md"
                      stretch="auto"
                      type="submit"
                      label={isSubmitting ? t("project_publish.updating") : t("project_publish.update_settings")}
                      loading={isSubmitting}
                    />
                  )
                ) : (
                  <Button
                    variant="primary"
                    size="md"
                    stretch="auto"
                    type="submit"
                    label={isSubmitting ? t("project_publish.publishing") : t("project_publish.publish")}
                    loading={isSubmitting}
                  />
                )}
              </div>
            )}
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
});
