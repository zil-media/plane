/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { RichTextEditorWithRef } from "@plane/editor";
import type { TFileHandler } from "@plane/editor";
import { MAX_FILE_SIZE } from "@plane/constants";
import { getFileURL } from "@plane/utils";

type Props = {
  id: string;
  projectId: string;
  html: string;
};

/** The portal's own file handler: images open through the portal's guarded asset endpoint. */
function portalFileHandler(projectId: string): TFileHandler {
  const getAssetSrc = async (path: string) => {
    if (!path) return "";
    if (path.startsWith("http")) return path;
    return getFileURL(`/api/public/portal/${projectId}/assets/${path}/`) ?? "";
  };
  return {
    checkIfAssetExists: async () => true,
    assetsUploadStatus: {},
    getAssetDownloadSrc: getAssetSrc,
    getAssetSrc,
    upload: async () => "",
    delete: async () => {},
    cancel: () => {},
    restore: async () => {},
    duplicate: async (assetId: string) => assetId,
    validation: { maxFileSize: MAX_FILE_SIZE },
  };
}

/** A post's copy or a document, read-only, as the team wrote it in Ops. */
export function PortalContent(props: Props) {
  const { id, projectId, html } = props;
  if (!html || html === "<p></p>") return null;
  return (
    <RichTextEditorWithRef
      id={id}
      editable={false}
      initialValue={html}
      fileHandler={portalFileHandler(projectId)}
      mentionHandler={{
        renderComponent: () => null,
        getMentionedEntityDetails: () => ({ display_name: "" }),
      }}
      disabledExtensions={[]}
      flaggedExtensions={[]}
      getEditorMetaData={() => ({ file_assets: [], user_mentions: [] })}
      extendedEditorProps={{}}
      containerClassName="p-0 border-none"
      editorClassName="overflow-hidden"
    />
  );
}
