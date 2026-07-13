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
  RotateCcw,
} from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { cn } from "@plane/utils";
// components
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { ProjectDropdown } from "@/components/dropdowns/project/dropdown";
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
  }, []);

  return (
    <div className="flex flex-col gap-y-6">
      <WizardStepIndicator step={step} processing={job?.status === "processing"} />

      {error && (
        <div className="border-red-500/30 bg-red-500/10 text-sm text-red-500 flex items-center gap-2 rounded-md border p-3">
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
    <div className="text-sm flex items-center gap-2">
      {steps.map((s, index) => (
        <div key={s.key} className="flex items-center gap-2">
          {index > 0 && <ChevronRight className="text-custom-text-400 size-3.5" />}
          <span
            className={cn("rounded-full px-2.5 py-0.5", {
              "bg-custom-primary-100/10 text-custom-primary-100 font-medium": index === activeIndex,
              "text-custom-text-400": index !== activeIndex,
            })}
          >
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
      <div className="border-custom-border-200 rounded-lg border p-4">
        <h4 className="text-sm mb-3 font-medium">
          {t("workspace_settings.settings.imports.notion.instructions_title")}
        </h4>
        <ol className="text-sm text-custom-text-300 flex list-inside list-decimal flex-col gap-y-1.5">
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
          "border-custom-border-300 text-custom-text-300 hover:border-custom-primary-100 hover:text-custom-primary-100 flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-10 transition-colors",
          { "pointer-events-none opacity-60": uploading }
        )}
      >
        {uploading ? (
          <>
            <Loader2 className="size-6 animate-spin" />
            <span className="text-sm">{uploadProgress}%</span>
          </>
        ) : (
          <>
            <FileUp className="size-6" />
            <span className="text-sm">{t("workspace_settings.settings.imports.notion.dropzone_label")}</span>
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
      <div className="text-sm flex items-center gap-1.5 py-0.5">
        <FileText className="text-custom-text-400 size-3.5 shrink-0" />
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
          <div className="text-sm text-custom-primary-100 flex items-center gap-1.5 py-0.5">
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
      <div className="text-sm flex flex-wrap gap-3">
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
      <p className="text-sm text-custom-text-300">
        {t("workspace_settings.settings.imports.notion.review_pages_hint")}
        {databaseCount > 0 ? ` ${t("workspace_settings.settings.imports.notion.review_databases_hint")}` : ""}
      </p>
      <div className="border-custom-border-200 max-h-80 overflow-y-auto rounded-lg border p-4">
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
    <div className="border-custom-border-200 flex items-center gap-1.5 rounded-md border px-2.5 py-1">
      <span className="font-semibold">{value}</span>
      <span className="text-custom-text-300">{label}</span>
    </div>
  );
}

function ConfigureStep({
  manifest,
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
  const databases = Object.entries(manifest.databases);
  const commentAuthors = manifest.comment_authors ?? [];
  return (
    <div className="flex flex-col gap-y-5">
      <div className="flex flex-col gap-y-1.5">
        <h4 className="text-sm font-medium">{t("workspace_settings.settings.imports.notion.destination_title")}</h4>
        <p className="text-sm text-custom-text-300">
          {t("workspace_settings.settings.imports.notion.destination_description")}
        </p>
        <div className="w-60">
          <ProjectDropdown
            value={projectId}
            onChange={(value) => {
              if (!Array.isArray(value) && value) setProjectId(value);
            }}
            multiple={false}
            buttonVariant="border-with-text"
          />
        </div>
      </div>

      {databases.length > 0 && (
        <div className="flex flex-col gap-y-3">
          <h4 className="text-sm font-medium">{t("workspace_settings.settings.imports.notion.databases_title")}</h4>
          {databases.map(([uuid, database]) => (
            <div key={uuid} className="border-custom-border-200 rounded-lg border p-4">
              <div className="text-sm mb-2 flex items-center gap-2 font-medium">
                <Database className="text-custom-primary-100 size-4" />
                {database.title}
                <span className="font-normal text-custom-text-400">
                  · {database.rows.length} {t("workspace_settings.settings.imports.notion.rows")}
                </span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <ModeCard
                  active={databaseModes[uuid] !== "work_items"}
                  title={t("workspace_settings.settings.imports.notion.mode_pages_title")}
                  description={t("workspace_settings.settings.imports.notion.mode_pages_description")}
                  onClick={() => setDatabaseMode(uuid, "pages")}
                />
                <ModeCard
                  active={databaseModes[uuid] === "work_items"}
                  title={t("workspace_settings.settings.imports.notion.mode_work_items_title")}
                  description={t("workspace_settings.settings.imports.notion.mode_work_items_description")}
                  onClick={() => setDatabaseMode(uuid, "work_items")}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {commentAuthors.length > 0 && (
        <div className="flex flex-col gap-y-3">
          <div>
            <h4 className="text-sm font-medium">{t("workspace_settings.settings.imports.notion.authors_title")}</h4>
            <p className="text-sm text-custom-text-300">
              {t("workspace_settings.settings.imports.notion.authors_description")}
            </p>
          </div>
          {commentAuthors.map((author) => (
            <div
              key={author}
              className="border-custom-border-200 flex items-center justify-between rounded-lg border px-4 py-2.5"
            >
              <span className="text-sm">{author}</span>
              <MemberDropdown
                value={authorMapping[author] ?? null}
                onChange={(value) => {
                  if (!Array.isArray(value) && value) setAuthorMapping(author, value);
                }}
                multiple={false}
                buttonVariant="border-with-text"
                placeholder={t("workspace_settings.settings.imports.notion.author_unmapped")}
              />
            </div>
          ))}
        </div>
      )}

      <div className="flex justify-between">
        <Button variant="secondary" onClick={onBack} disabled={running}>
          {t("common.back")}
        </Button>
        <Button variant="primary" disabled={!projectId || running} loading={running} onClick={onRun}>
          {t("workspace_settings.settings.imports.notion.start_import")}
        </Button>
      </div>
    </div>
  );
}

function ModeCard({
  active,
  title,
  description,
  onClick,
}: {
  active: boolean;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-col gap-1 rounded-md border p-3 text-left transition-colors",
        active
          ? "border-custom-primary-100 bg-custom-primary-100/5"
          : "border-custom-border-200 hover:border-custom-border-400"
      )}
    >
      <span className="text-sm font-medium">{title}</span>
      <span className="text-xs text-custom-text-300">{description}</span>
    </button>
  );
}

function ProcessingStep({ manifest }: { manifest: TNotionManifest }) {
  const { t } = useTranslation();
  return (
    <div className="border-custom-border-200 flex flex-col items-center gap-3 rounded-lg border p-10">
      <Loader2 className="text-custom-primary-100 size-8 animate-spin" />
      <p className="text-sm font-medium">{t("workspace_settings.settings.imports.notion.processing_title")}</p>
      <p className="text-sm text-custom-text-300">
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
          "text-sm flex items-center gap-2 rounded-lg border p-4 font-medium",
          success
            ? "border-green-500/30 bg-green-500/10 text-green-600"
            : "border-red-500/30 bg-red-500/10 text-red-500"
        )}
      >
        {success ? <CheckCircle2 className="size-5" /> : <AlertTriangle className="size-5" />}
        {success
          ? t("workspace_settings.settings.imports.notion.completed_title")
          : t("workspace_settings.settings.imports.notion.failed_title")}
      </div>
      {success ? (
        <div className="text-sm flex flex-wrap gap-3">
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
        <p className="text-sm text-custom-text-300">{job.reason}</p>
      )}
      {success && (report.warnings?.length ?? 0) > 0 && (
        <div className="border-custom-border-200 rounded-lg border p-4">
          <h5 className="text-sm mb-2 font-medium">{t("workspace_settings.settings.imports.notion.warnings_title")}</h5>
          <ul className="text-xs text-custom-text-300 flex list-inside list-disc flex-col gap-y-1">
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
