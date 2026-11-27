/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ArrowLeft, FileText } from "lucide-react";
import useSWR from "swr";
// plane imports
import { SitesPortalService } from "@plane/services";
import { Loader } from "@plane/ui";
// local imports
import { shortDate } from "./helpers";
import { PortalContent } from "./portal-content";

const portalService = new SitesPortalService();

type Props = {
  projectId: string;
  documentId: string | null;
  onOpen: (documentId: string | null) => void;
};

/** The documents the team shares (the brand's "Cliente" folder): a flat list, read full screen. */
export function PortalDocuments({ projectId, documentId, onOpen }: Props) {
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
            <h2 className="text-20 font-semibold text-primary">{document.name}</h2>
            <PortalContent id={document.id} projectId={projectId} html={document.description_html ?? ""} />
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
      {data.documents.map((doc) => (
        <li key={doc.id}>
          <button
            type="button"
            onClick={() => onOpen(doc.id)}
            className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-layer-1"
          >
            <FileText className="size-4 flex-shrink-0 text-tertiary" />
            <span className="min-w-0 flex-1 truncate text-14 text-primary">{doc.name}</span>
            <span className="text-11 text-tertiary">{shortDate(doc.updated_at)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
