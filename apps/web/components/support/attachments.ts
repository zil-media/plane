/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { EFileAssetType } from "@plane/types";
import { FileService } from "@/services/file.service";

const fileService = new FileService();

const MAX_WIDTH = 1280;
const JPEG_QUALITY = 0.6;
export const MAX_ATTACHMENTS = 5;

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.addEventListener("load", () => resolve(image), { once: true });
    image.addEventListener("error", reject, { once: true });
    image.src = src;
  });
}

/** Screenshots go out at most 1280px wide as JPEG: enough to read the UI, small enough to upload fast. */
export async function compressImage(source: Blob | string, name = "captura.jpg"): Promise<File> {
  const url = typeof source === "string" ? source : URL.createObjectURL(source);
  try {
    const image = await loadImage(url);
    const scale = Math.min(1, MAX_WIDTH / image.width);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(image.width * scale);
    canvas.height = Math.round(image.height * scale);
    canvas.getContext("2d")?.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY));
    if (!blob) throw new Error("image encoding failed");
    return new File([blob], name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" });
  } finally {
    if (typeof source !== "string") URL.revokeObjectURL(url);
  }
}

export async function uploadSupportImage(
  workspaceSlug: string,
  file: File,
  entityType: EFileAssetType.BUG_REPORT_ATTACHMENT | EFileAssetType.FEATURE_REQUEST_ATTACHMENT
): Promise<string> {
  const response = await fileService.uploadWorkspaceAsset(
    workspaceSlug,
    { entity_identifier: "", entity_type: entityType },
    file
  );
  return response.asset_id;
}
