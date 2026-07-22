/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Database,
  FileText,
  FileUp,
  Loader2,
  Plus,
  RotateCcw,
} from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Badge } from "@plane/propel/badge";
import { Button } from "@plane/propel/button";
import { cn } from "@plane/utils";
import { CustomSelect } from "@plane/ui";
// components
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { ProjectDropdown } from "@/components/dropdowns/project/dropdown";
import { CreateProjectModal } from "@/components/project/create-project-modal";
import { SettingsBoxedControlItem } from "@/components/settings/boxed-control-item";
// hooks
import { useMember } from "@/hooks/store/use-member";
// services
import {
  NotionImporterService,
  type TNotionDatabaseMode,
  type TNotionImportJob,
  type TNotionManifest,
} from "@/services/importers/notion.service";

const notionImporterService = new NotionImporterService();

type TWizardStep = "upload" | "review" | "configure" | "result";

// CSV columns that hint a database is a tracker rather than reference content
const TRACKER_COLUMN_HINTS = [
  "status",
  "estado",
  "assignee",
  "asignado",
  "due",
  "fecha",
  "date",
  "priority",
  "prioridad",
];

export const NotionImportWizard = observer(function NotionImportWizard() {
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  // state
  const [job, setJob] = useState<TNotionImportJob | null>(null);
  const [step, setStep] = useState<TWizardStep>("upload");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [databaseModes, setDatabaseModes] = useState<Record<string, TNotionDatabaseMode>>({});
  const [authorMapping, setAuthorMapping] = useState<Record<string, string>>({});
  // store hooks
  const {
    getUserDetails,
    workspace: { workspaceMemberIds },
  } = useMember();

  const slug = workspaceSlug?.toString() ?? "";

  // poll while the import is running
  useSWR(
    job && job.status === "processing" ? `NOTION_IMPORT_JOB_${job.id}` : null,
    () => notionImporterService.retrieve(slug, job!.id),
    {
      refreshInterval: 3000,
      onSuccess: (data) => {
        setError(null);
        setJob(data);
        if (data.status !== "processing") setStep("result");
      },
      // a transient failure self-heals on the next tick, but surface a
      // persistent one instead of spinning silently forever
      onError: (err: any) => {
        setError(err?.error ?? t("workspace_settings.settings.imports.notion.run_failed"));
      },
    }
  );

  const suggestedModes = useMemo(() => {
    if (!job) return {};
    const suggestions: Record<string, TNotionDatabaseMode> = {};
    Object.entries(job.manifest.databases).forEach(([uuid, database]) => {
      const looksLikeTracker = database.columns.some((column) =>
        TRACKER_COLUMN_HINTS.some((hint) => column.toLowerCase().includes(hint))
      );
      suggestions[uuid] = looksLikeTracker ? "work_items" : "pages";
    });
    return suggestions;
  }, [job]);

  // auto-suggest a workspace member for each Notion comment author by name
  const suggestedAuthors = useMemo(() => {
    const authors = job?.manifest.comment_authors ?? [];
    if (authors.length === 0 || !workspaceMemberIds) return {};
    const suggestions: Record<string, string> = {};
    authors.forEach((author) => {
      const normalized = author.trim().toLowerCase();
      const match = workspaceMemberIds.find((memberId) => {
        const member = getUserDetails(memberId);
        if (!member) return false;
        const fullName = `${member.first_name ?? ""} ${member.last_name ?? ""}`.trim().toLowerCase();
        return member.display_name?.trim().toLowerCase() === normalized || fullName === normalized;
      });
      if (match) suggestions[author] = match;
    });
    return suggestions;
  }, [job, workspaceMemberIds, getUserDetails]);

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      setUploading(true);
      setUploadProgress(0);
      try {
        const created = await notionImporterService.upload(slug, file, (event) => {
          if (event.total) setUploadProgress(Math.round((event.loaded / event.total) * 100));
        });
        setJob(created);
        setDatabaseModes({});
        setAuthorMapping({});
        setStep("review");
      } catch (err: any) {
        setError(err?.error ?? t("workspace_settings.settings.imports.notion.upload_failed"));
      } finally {
        setUploading(false);
      }
    },
    [slug, t]
  );

  const handleRun = useCallback(async () => {
    if (!job || !projectId || running) return;
    setError(null);
    setRunning(true);
    try {
      const modes = { ...suggestedModes, ...databaseModes };
      const users = { ...suggestedAuthors, ...authorMapping };
      const updated = await notionImporterService.run(slug, job.id, {
        project_id: projectId,
        databases: modes,
        users,
      });
      setJob(updated);
    } catch (err: any) {
      setError(err?.error ?? t("workspace_settings.settings.imports.notion.run_failed"));
    } finally {
      setRunning(false);
    }
  }, [job, projectId, running, databaseModes, suggestedModes, authorMapping, suggestedAuthors, slug, t]);

  const reset = useCallback(() => {
    setJob(null);
    setStep("upload");
    setError(null);
    setProjectId(null);
    setDatabaseModes({});
    setAuthorMapping({});
  }, []);

  return (
    <div className="flex flex-col gap-y-6">
      <WizardStepIndicator step={step} processing={job?.status === "processing"} />

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-subtle bg-danger-subtle p-3 text-body-sm-regular text-danger-primary">
          <AlertTriangle className="size-4 shrink-0" />
          {error}
        </div>
      )}

      {step === "upload" && <UploadStep uploading={uploading} uploadProgress={uploadProgress} onFile={handleFile} />}

      {step === "review" && job && (
        <ReviewStep manifest={job.manifest} onBack={reset} onNext={() => setStep("configure")} />
      )}

      {step === "configure" && job && job.status !== "processing" && (
        <ConfigureStep
          manifest={job.manifest}
          workspaceSlug={slug}
          projectId={projectId}
          setProjectId={setProjectId}
          databaseModes={{ ...suggestedModes, ...databaseModes }}
          setDatabaseMode={(uuid, mode) => setDatabaseModes((prev) => ({ ...prev, [uuid]: mode }))}
          authorMapping={{ ...suggestedAuthors, ...authorMapping }}
          setAuthorMapping={(author, userId) => setAuthorMapping((prev) => ({ ...prev, [author]: userId }))}
          onBack={() => setStep("review")}
          onRun={handleRun}
          running={running}
        />
      )}

      {job && job.status === "processing" && <ProcessingStep manifest={job.manifest} />}

      {step === "result" && job && (job.status === "completed" || job.status === "failed") && (
        <ResultStep job={job} onRestart={reset} />
      )}
    </div>
  );
});

function WizardStepIndicator({ step, processing }: { step: TWizardStep; processing?: boolean }) {
  const { t } = useTranslation();
  const steps: { key: TWizardStep; label: string }[] = [
    { key: "upload", label: t("workspace_settings.settings.imports.notion.step_upload") },
    { key: "review", label: t("workspace_settings.settings.imports.notion.step_review") },
    { key: "configure", label: t("workspace_settings.settings.imports.notion.step_configure") },
    { key: "result", label: t("workspace_settings.settings.imports.notion.step_result") },
  ];
  const activeIndex = processing ? 3 : steps.findIndex((s) => s.key === step);
  return (
    <div className="flex items-center gap-2 text-body-sm-regular">
      {steps.map((s, index) => (
        <div key={s.key} className="flex items-center gap-2">
          {index > 0 && <ChevronRight className="size-3.5 text-tertiary" />}
          <span className={cn("text-tertiary", { "text-body-sm-medium text-primary": index === activeIndex })}>
            {index + 1}. {s.label}
          </span>
        </div>
      ))}
    </div>
  );
}

function UploadStep({
  uploading,
  uploadProgress,
  onFile,
}: {
  uploading: boolean;
  uploadProgress: number;
  onFile: (file: File) => void;
}) {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const instructions: string[] = [
    t("workspace_settings.settings.imports.notion.instruction_menu"),
    t("workspace_settings.settings.imports.notion.instruction_format"),
    t("workspace_settings.settings.imports.notion.instruction_content"),
    t("workspace_settings.settings.imports.notion.instruction_subpages"),
    t("workspace_settings.settings.imports.notion.instruction_folders"),
    t("workspace_settings.settings.imports.notion.instruction_comments"),
  ];
  return (
    <div className="flex flex-col gap-y-4">
      <div className="rounded-lg border border-subtle bg-layer-2 p-4">
        <h4 className="mb-3 text-body-sm-medium text-primary">
          {t("workspace_settings.settings.imports.notion.instructions_title")}
        </h4>
        <ol className="flex list-inside list-decimal flex-col gap-y-1.5 text-body-sm-regular text-tertiary">
          {instructions.map((instruction) => (
            <li key={instruction}>{instruction}</li>
          ))}
        </ol>
      </div>
      <button
        type="button"
        disabled={uploading}
        onClick={() => fileInputRef.current?.click()}
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-subtle bg-layer-2 p-10 text-tertiary transition-colors hover:bg-layer-2-hover hover:text-primary",
          { "pointer-events-none opacity-60": uploading }
        )}
      >
        {uploading ? (
          <>
            <Loader2 className="size-6 animate-spin" />
            <span className="text-body-sm-regular">{uploadProgress}%</span>
          </>
        ) : (
          <>
            <FileUp className="size-6" />
            <span className="text-body-sm-regular">
              {t("workspace_settings.settings.imports.notion.dropzone_label")}
            </span>
          </>
        )}
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".zip"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
          event.target.value = "";
        }}
      />
    </div>
  );
}

function ManifestTree({ manifest, uuid, depth }: { manifest: TNotionManifest; uuid: string; depth: number }) {
  const page = manifest.pages[uuid];
  if (!page) return null;
  const databases = Object.entries(manifest.databases).filter(([, database]) => database.parent === uuid);
  return (
    <div style={{ paddingLeft: depth === 0 ? 0 : 16 }}>
      <div className="flex items-center gap-1.5 py-0.5 text-body-sm-regular">
        <FileText className="size-3.5 shrink-0 text-tertiary" />
        <span className="truncate">
          {page.icon && !page.icon.startsWith("/") && !page.icon.startsWith("http") ? `${page.icon} ` : ""}
          {page.title}
        </span>
      </div>
      {page.children.map((child) => (
        <ManifestTree key={child} manifest={manifest} uuid={child} depth={depth + 1} />
      ))}
      {databases.map(([databaseUuid, database]) => (
        <div key={databaseUuid} style={{ paddingLeft: 16 }}>
          <div className="flex items-center gap-1.5 py-0.5 text-body-sm-regular text-primary">
            <Database className="size-3.5 shrink-0" />
            <span className="truncate">
              {database.title} · {database.rows.length}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function ReviewStep({
  manifest,
  onBack,
  onNext,
}: {
  manifest: TNotionManifest;
  onBack: () => void;
  onNext: () => void;
}) {
  const { t } = useTranslation();
  const databaseCount = manifest.stats.databases;
  return (
    <div className="flex flex-col gap-y-4">
      <div className="flex flex-wrap gap-2">
        <SummaryChip
          label={t("workspace_settings.settings.imports.notion.summary_pages")}
          value={manifest.stats.pages}
        />
        <SummaryChip
          label={t("workspace_settings.settings.imports.notion.summary_databases")}
          value={manifest.stats.databases}
        />
        <SummaryChip
          label={t("workspace_settings.settings.imports.notion.summary_rows")}
          value={manifest.stats.database_rows}
        />
        <SummaryChip
          label={t("workspace_settings.settings.imports.notion.summary_assets")}
          value={manifest.stats.assets}
        />
      </div>
      <p className="text-body-sm-regular text-tertiary">
        {t("workspace_settings.settings.imports.notion.review_pages_hint")}
        {databaseCount > 0 ? ` ${t("workspace_settings.settings.imports.notion.review_databases_hint")}` : ""}
      </p>
      <div className="max-h-80 overflow-y-auto rounded-lg border border-subtle bg-layer-2 p-4">
        {manifest.root_pages.map((uuid) => (
          <ManifestTree key={uuid} manifest={manifest} uuid={uuid} depth={0} />
        ))}
      </div>
      <div className="flex justify-between">
        <Button variant="secondary" onClick={onBack}>
          {t("common.cancel")}
        </Button>
        <Button variant="primary" onClick={onNext}>
          {t("common.continue")}
        </Button>
      </div>
    </div>
  );
}

function SummaryChip({ label, value }: { label: string; value: number }) {
  return (
    <Badge variant="neutral" size="lg">
      <span className="font-semibold">{value}</span>
      <span className="text-tertiary">{label}</span>
    </Badge>
  );
}

function ConfigureStep({
  manifest,
  workspaceSlug,
  projectId,
  setProjectId,
  databaseModes,
  setDatabaseMode,
  authorMapping,
  setAuthorMapping,
  onBack,
  onRun,
  running,
}: {
  manifest: TNotionManifest;
  workspaceSlug: string;
  projectId: string | null;
  setProjectId: (id: string) => void;
  databaseModes: Record<string, TNotionDatabaseMode>;
  setDatabaseMode: (uuid: string, mode: TNotionDatabaseMode) => void;
  authorMapping: Record<string, string>;
  setAuthorMapping: (author: string, userId: string) => void;
  onBack: () => void;
  onRun: () => void;
  running: boolean;
}) {
  const { t } = useTranslation();
  const [isCreateProjectOpen, setCreateProjectOpen] = useState(false);
  const databases = Object.entries(manifest.databases);
  const commentAuthors = manifest.comment_authors ?? [];
  const modeLabel = (mode: TNotionDatabaseMode) =>
    mode === "work_items"
      ? t("workspace_settings.settings.imports.notion.mode_work_items_title")
      : t("workspace_settings.settings.imports.notion.mode_pages_title");
  const modeDescription = (mode: TNotionDatabaseMode) =>
    mode === "work_items"
      ? t("workspace_settings.settings.imports.notion.mode_work_items_description")
      : t("workspace_settings.settings.imports.notion.mode_pages_description");

  return (
    <div className="flex flex-col gap-y-5">
      {/* Destination + database modes */}
      <div className="rounded-lg border border-subtle bg-layer-2">
        <SettingsBoxedControlItem
          className="rounded-none border-0 border-b"
          title={
            <>
              {t("workspace_settings.settings.imports.notion.destination_title")}
              <span className="text-danger-primary"> *</span>
            </>
          }
          description={t("workspace_settings.settings.imports.notion.destination_description")}
          control={
            <div className="flex items-center gap-2">
              <ProjectDropdown
                value={projectId}
                onChange={(value) => {
                  if (!Array.isArray(value) && value) setProjectId(value);
                }}
                multiple={false}
                buttonVariant="border-with-text"
              />
              <Button
                variant="secondary"
                size="sm"
                prependIcon={<Plus className="size-3.5" />}
                onClick={() => setCreateProjectOpen(true)}
              >
                {t("common.create_project")}
              </Button>
              <CreateProjectModal
                isOpen={isCreateProjectOpen}
                onClose={() => setCreateProjectOpen(false)}
                workspaceSlug={workspaceSlug}
                onProjectCreated={(newProjectId) => setProjectId(newProjectId)}
              />
            </div>
          }
        />

        {databases.map(([uuid, database], index) => {
          const mode = databaseModes[uuid] ?? "pages";
          return (
            <SettingsBoxedControlItem
              key={uuid}
              className={cn("rounded-none border-0", { "border-b": index < databases.length - 1 })}
              title={
                <span className="flex items-center gap-2">
                  <Database className="size-4 text-primary" />
                  {database.title}
                  <span className="text-caption-md-regular text-tertiary">
                    · {database.rows.length} {t("workspace_settings.settings.imports.notion.rows")}
                  </span>
                </span>
              }
              description={modeDescription(mode)}
              control={
                <CustomSelect
                  value={mode}
                  onChange={(value: TNotionDatabaseMode) => setDatabaseMode(uuid, value)}
                  label={modeLabel(mode)}
                  buttonClassName="py-2 text-13"
                  optionsClassName="w-48"
                  placement="bottom-end"
                >
                  <CustomSelect.Option value="pages">
                    {t("workspace_settings.settings.imports.notion.mode_pages_title")}
                  </CustomSelect.Option>
                  <CustomSelect.Option value="work_items">
                    {t("workspace_settings.settings.imports.notion.mode_work_items_title")}
                  </CustomSelect.Option>
                </CustomSelect>
              }
            />
          );
        })}
      </div>

      {/* Comment author mapping */}
      {commentAuthors.length > 0 && (
        <div className="flex flex-col gap-y-2">
          <div>
            <h4 className="text-body-sm-medium text-primary">
              {t("workspace_settings.settings.imports.notion.authors_title")}
            </h4>
            <p className="text-caption-md-regular text-tertiary">
              {t("workspace_settings.settings.imports.notion.authors_description")}
            </p>
            {manifest.comment_authors_truncated && (
              <p className="text-caption-md-regular text-warning-primary">
                {t("workspace_settings.settings.imports.notion.authors_truncated")}
              </p>
            )}
          </div>
          <div className="rounded-lg border border-subtle bg-layer-2">
            {commentAuthors.map((author, index) => (
              <SettingsBoxedControlItem
                key={author}
                className={cn("rounded-none border-0", { "border-b": index < commentAuthors.length - 1 })}
                title={author}
                control={
                  <MemberDropdown
                    value={authorMapping[author] ?? null}
                    onChange={(value) => {
                      if (!Array.isArray(value) && value) setAuthorMapping(author, value);
                    }}
                    multiple={false}
                    buttonVariant="border-with-text"
                    showUserDetails
                    placeholder={t("workspace_settings.settings.imports.notion.author_unmapped")}
                  />
                }
              />
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <Button variant="secondary" onClick={onBack} disabled={running}>
          {t("common.back")}
        </Button>
        <Button variant="primary" size="lg" disabled={!projectId || running} loading={running} onClick={onRun}>
          {t("workspace_settings.settings.imports.notion.start_import")}
        </Button>
      </div>
    </div>
  );
}

function ProcessingStep({ manifest }: { manifest: TNotionManifest }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-subtle bg-layer-2 p-10">
      <Loader2 className="size-8 animate-spin text-primary" />
      <p className="text-body-sm-medium text-primary">
        {t("workspace_settings.settings.imports.notion.processing_title")}
      </p>
      <p className="text-body-sm-regular text-tertiary">
        {manifest.stats.pages + manifest.stats.database_rows}{" "}
        {t("workspace_settings.settings.imports.notion.summary_pages").toLowerCase()} · {manifest.stats.assets}{" "}
        {t("workspace_settings.settings.imports.notion.summary_assets").toLowerCase()}
      </p>
    </div>
  );
}

function ResultStep({ job, onRestart }: { job: TNotionImportJob; onRestart: () => void }) {
  const { t } = useTranslation();
  const { workspaceSlug } = useParams();
  const success = job.status === "completed";
  const report = job.report ?? {};
  return (
    <div className="flex flex-col gap-y-4">
      <div
        className={cn(
          "flex items-center gap-2 rounded-lg border border-subtle p-4 text-body-sm-medium",
          success ? "bg-success-subtle text-success-primary" : "bg-danger-subtle text-danger-primary"
        )}
      >
        {success ? <CheckCircle2 className="size-5" /> : <AlertTriangle className="size-5" />}
        {success
          ? t("workspace_settings.settings.imports.notion.completed_title")
          : t("workspace_settings.settings.imports.notion.failed_title")}
      </div>
      {success ? (
        <div className="flex flex-wrap gap-2">
          <SummaryChip
            label={t("workspace_settings.settings.imports.notion.report_pages_created")}
            value={(report.pages_created ?? 0) + (report.pages_updated ?? 0)}
          />
          <SummaryChip
            label={t("workspace_settings.settings.imports.notion.report_work_items_created")}
            value={(report.work_items_created ?? 0) + (report.work_items_updated ?? 0)}
          />
          <SummaryChip
            label={t("workspace_settings.settings.imports.notion.report_assets")}
            value={report.assets_uploaded ?? 0}
          />
          {(report.comments_created ?? 0) > 0 && (
            <SummaryChip
              label={t("workspace_settings.settings.imports.notion.report_comments")}
              value={report.comments_created ?? 0}
            />
          )}
        </div>
      ) : (
        <p className="text-body-sm-regular text-tertiary">{job.reason}</p>
      )}
      {success && (report.warnings?.length ?? 0) > 0 && (
        <div className="rounded-lg border border-subtle bg-layer-2 p-4">
          <h5 className="mb-2 text-body-sm-medium text-primary">
            {t("workspace_settings.settings.imports.notion.warnings_title")}
          </h5>
          <ul className="flex list-inside list-disc flex-col gap-y-1 text-caption-md-regular text-tertiary">
            {Array.from(new Set(report.warnings))
              .slice(0, 20)
              .map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
          </ul>
        </div>
      )}
      <div className="flex items-center gap-3">
        {success && job.project && (
          <a href={`/${workspaceSlug}/projects/${job.project}/pages/`}>
            <Button variant="primary">{t("workspace_settings.settings.imports.notion.open_pages")}</Button>
          </a>
        )}
        <Button variant="secondary" prependIcon={<RotateCcw className="size-3.5" />} onClick={onRestart}>
          {t("workspace_settings.settings.imports.notion.import_another")}
        </Button>
      </div>
    </div>
  );
}
