/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { MAX_FILE_SIZE } from "@plane/constants";
// hooks
import { useInstance } from "@/hooks/store/use-instance";

type TReturnProps = {
  maxFileSize: number;
  /** a video attached to a work item has its own, larger cap (the client portal plays it) */
  maxVideoFileSize: number;
  /** the largest file a dropzone takes; `sizeValidator` holds every other file to maxFileSize */
  maxDropSize: number;
  sizeValidator: (file: File) => { code: string; message: string } | null;
  /** the cap of this file, in MB, for the "too large" message */
  limitMbFor: (file: File | undefined) => number;
};

export const useFileSize = (): TReturnProps => {
  // store hooks
  const { config } = useInstance();

  const maxFileSize = config?.file_size_limit ?? MAX_FILE_SIZE;
  const maxVideoFileSize = Math.max(config?.video_file_size_limit ?? maxFileSize, maxFileSize);

  return {
    maxFileSize,
    maxVideoFileSize,
    maxDropSize: maxVideoFileSize,
    sizeValidator: (file: File) =>
      !file.type?.startsWith("video/") && file.size > maxFileSize
        ? { code: "file-too-large", message: `File is larger than ${maxFileSize} bytes` }
        : null,
    limitMbFor: (file: File | undefined) =>
      (file?.type?.startsWith("video/") ? maxVideoFileSize : maxFileSize) / 1024 / 1024,
  };
};
