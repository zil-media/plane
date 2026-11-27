/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { format, formatDistanceToNow, parseISO } from "date-fns";
import { es } from "date-fns/locale";
// plane imports
import type { TZilPortalStatus } from "@plane/types";

export const dayLabel = (iso: string) => format(parseISO(iso), "EEEE d 'de' MMMM", { locale: es });
export const shortDate = (iso: string) => format(parseISO(iso), "d MMM", { locale: es });
export const monthLabel = (date: Date) => format(date, "MMMM yyyy", { locale: es });
export const ago = (iso: string) => formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: es });
export const isoDay = (date: Date) => format(date, "yyyy-MM-dd");

/** The status chip's color, from the existing tokens. */
export const STATUS_CLASS: Record<TZilPortalStatus, string> = {
  "En preparación": "bg-layer-1 text-secondary",
  "Para revisar": "bg-accent-primary text-on-color",
  Programada: "bg-layer-1 text-accent-primary",
  Publicada: "bg-success-primary text-on-color",
};

export const isVideo = (type: string | undefined) => !!type && type.toLowerCase().startsWith("video/");
