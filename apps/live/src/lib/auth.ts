/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { IncomingHttpHeaders } from "http";
import type { TUserDetails } from "@plane/editor";
import { logger } from "@plane/logger";
import { AppError } from "@/lib/errors";
// services
import { getPageService } from "@/services/page/handler";
import { UserService } from "@/services/user.service";
// types
import type { HocusPocusServerContext, TDocumentTypes } from "@/types";

/**
 * Authenticate the user
 * @param requestHeaders - The request headers
 * @param context - The context
 * @param token - The token
 * @returns The authenticated user
 */
export const onAuthenticate = async ({
  requestHeaders,
  requestParameters,
  context,
  token,
  documentName,
}: {
  requestHeaders: IncomingHttpHeaders;
  context: HocusPocusServerContext;
  requestParameters: URLSearchParams;
  token: string;
  documentName: string;
}) => {
  let cookie: string | undefined = undefined;
  let userId: string | undefined = undefined;

  // Extract cookie (fallback to request headers) and userId from token (for scenarios where
  // the cookies are not passed in the request headers)
  try {
    const parsedToken = JSON.parse(token) as TUserDetails;
    userId = parsedToken.id;
    cookie = parsedToken.cookie;
  } catch (error) {
    const appError = new AppError(error, {
      context: { operation: "onAuthenticate" },
    });
    logger.error("Token parsing failed, using request headers", appError);
  } finally {
    // If cookie is still not found, fallback to request headers
    if (!cookie) {
      cookie = requestHeaders.cookie?.toString();
    }
  }

  if (!cookie || !userId) {
    const appError = new AppError("Credentials not provided", { code: "AUTH_MISSING_CREDENTIALS" });
    logger.error("Credentials not provided", appError);
    throw appError;
  }

  // set cookie in context, so it can be used throughout the ws connection
  context.cookie = cookie ?? requestParameters.get("cookie") ?? "";
  context.documentType = requestParameters.get("documentType")?.toString() as TDocumentTypes;
  context.projectId = requestParameters.get("projectId");
  context.userId = userId;
  context.workspaceSlug = requestParameters.get("workspaceSlug");

  const authenticationResult = await handleAuthentication({
    cookie: context.cookie,
    userId: context.userId,
  });

  // Authorize the authenticated user against the target page on EVERY connection.
  // Hocuspocus only re-runs the database extension's permission-scoped fetch for
  // documents that aren't already loaded in memory, so once a document is warm,
  // later connections would otherwise skip page-level authorization entirely.
  await authorizePageAccess({ context, pageId: documentName });

  return authenticationResult;
};

/**
 * Authorize the authenticated user for the target page/project using the same
 * permission-scoped Django endpoint the document fetch path relies on
 * (see apps/live/src/extensions/database.ts fetchDocument). Throws if the
 * user is not authorized to access the page, rejecting the connection.
 */
const authorizePageAccess = async ({
  context,
  pageId,
}: {
  context: HocusPocusServerContext;
  pageId: string;
}) => {
  try {
    const service = getPageService(context.documentType, context);
    await service.fetchDescriptionBinary(pageId);
  } catch (error) {
    const appError = new AppError(error, {
      context: { operation: "authorizePageAccess", pageId },
    });
    logger.error("Page authorization failed", appError);
    throw new AppError("Authentication unsuccessful: insufficient page permissions", {
      code: "AUTH_FORBIDDEN",
      statusCode: appError.statusCode,
    });
  }
};

export const handleAuthentication = async ({ cookie, userId }: { cookie: string; userId: string }) => {
  // fetch current user info
  try {
    const userService = new UserService();
    const user = await userService.currentUser(cookie);
    if (user.id !== userId) {
      throw new AppError("Authentication unsuccessful: User ID mismatch", { code: "AUTH_USER_MISMATCH" });
    }

    return {
      user: {
        id: user.id,
        name: user.display_name,
      },
    };
  } catch (error) {
    const appError = new AppError(error, {
      context: { operation: "handleAuthentication" },
    });
    logger.error("Authentication failed", appError);
    throw new AppError("Authentication unsuccessful", { code: appError.code });
  }
};
