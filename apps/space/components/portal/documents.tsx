/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { ArrowLeft, ChevronRight, Folder, FolderOpen } from "lucide-react";
import useSWR from "swr";
// plane imports
import { PageIcon } from "@plane/propel/icons";
import { SitesPortalService } from "@plane/services";
import type { TZilPortalDocument, TZilPortalFolder } from "@plane/types";
import { Loader } from "@plane/ui";
import { cn } from "@plane/utils";
// local imports
import { PortalComments } from "./comments";
import { shortDate } from "./helpers";
import { PortalContent } from "./portal-content";

const portalService = new SitesPortalService();
const INDENT_PER_LEVEL_PX = 20;

type Props = {
  projectId: string;
  documentId: string | null;
  preview: boolean;
  onOpen: (documentId: string | null) => void;
};

type TTreeProps = {
  parentId: string | null;
  depth: number;
  folders: TZilPortalFolder[];
  documents: TZilPortalDocument[];
  onOpen: (documentId: string) => void;
};

/**
 * The "Cliente" folder as a tree, row by row like Ops' page list (pages/list/block.tsx): indentation,
 * chevron and folder icon for a sub-folder, page icon for a document. Folders open in place.
 */
function DocumentTree({ parentId, depth, folders, documents, onOpen }: TTreeProps) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const childFolders = folders.filter((f) => (f.parent_id ?? null) === parentId);
  const childDocs = documents.filter((d) => (d.parent_id ?? null) === parentId);
  return (
    <>
      {childFolders.map((folder) => {
        const isOpen = !!open[folder.id];
        const Icon = isOpen ? FolderOpen : Folder;
        return (
          <li key={folder.id}>
            <button
              type="button"
              onClick={() => setOpen((prev) => ({ ...prev, [folder.id]: !isOpen }))}
              aria-expanded={isOpen}
              className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-layer-1"
            >
              <span className="flex items-center gap-1.5" style={{ paddingLeft: depth * INDENT_PER_LEVEL_PX }}>
                <ChevronRight className={cn("size-3.5 text-tertiary transition-transform", { "rotate-90": isOpen })} />
                <Icon className="h-4 w-4 text-tertiary" />
              </span>
              <span className="min-w-0 flex-1 truncate text-13 text-primary">{folder.name}</span>
            </button>
            {isOpen && (
              <ul className="divide-y divide-subtle-1 border-t border-subtle">
                <DocumentTree
                  parentId={folder.id}
                  depth={depth + 1}
                  folders={folders}
                  documents={documents}
                  onOpen={onOpen}
                />
              </ul>
            )}
          </li>
        );
      })}
      {childDocs.map((doc) => (
        <li key={doc.id}>
          <button
            type="button"
            onClick={() => onOpen(doc.id)}
            className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-layer-1"
          >
            <span className="flex items-center gap-1.5" style={{ paddingLeft: depth * INDENT_PER_LEVEL_PX }}>
              <span className="size-3.5" aria-hidden />
              <PageIcon className="h-4 w-4 text-tertiary" />
            </span>
            <span className="min-w-0 flex-1 truncate text-13 text-primary">{doc.name}</span>
            <span className="text-11 text-tertiary">{shortDate(doc.updated_at)}</span>
          </button>
        </li>
      ))}
    </>
  );
}

/** The documents the team shares (the brand's "Cliente" folder): its tree, a reader and the conversation. */
export function PortalDocuments({ projectId, documentId, preview, onOpen }: Props) {
  const { data, error: listError } = useSWR(`PORTAL_DOCUMENTS_${projectId}`, () => portalService.documents(projectId));
  const { data: document, error } = useSWR(documentId ? `PORTAL_DOCUMENT_${projectId}_${documentId}` : null, () =>
    portalService.document(projectId, documentId as string)
  );

  if (documentId)
    return (
      <article className="mx-auto max-w-3xl space-y-4">
        <button
          type="button"
          onClick={() => onOpen(null)}
          className="inline-flex items-center gap-1 text-13 text-secondary hover:text-primary"
        >
          <ArrowLeft className="size-4" />
          Documentos
        </button>
        {error ? (
          <p className="text-13 text-tertiary">Este documento ya no está disponible.</p>
        ) : !document ? (
          <Loader className="space-y-3">
            <Loader.Item height="28px" width="50%" />
            <Loader.Item height="200px" />
          </Loader>
        ) : (
          <>
            <h1 className="text-[2rem] leading-[2.375rem] font-bold text-primary">{document.name}</h1>
            <PortalContent id={document.id} projectId={projectId} html={document.description_html ?? ""} />
            {/* divider and conversation, as in a post */}
            <div className="my-5 h-[1] w-full border-t border-subtle" />
            <PortalComments key={document.id} projectId={projectId} documentId={document.id} preview={preview} />
          </>
        )}
      </article>
    );

  if (listError)
    return (
      <p className="rounded-md border border-subtle p-6 text-center text-13 text-tertiary">
        No pudimos cargar los documentos. Probá de nuevo en un momento.
      </p>
    );

  if (!data)
    return (
      <Loader className="space-y-2">
        <Loader.Item height="48px" />
        <Loader.Item height="48px" />
      </Loader>
    );

  if (data.documents.length === 0)
    return (
      <p className="rounded-md border border-subtle p-6 text-center text-13 text-tertiary">
        Todavía no hay documentos compartidos.
      </p>
    );

  return (
    <ul className="divide-y divide-subtle-1 overflow-hidden rounded-md border border-subtle">
      <DocumentTree parentId={null} depth={0} folders={data.folders} documents={data.documents} onOpen={onOpen} />
    </ul>
  );
}
