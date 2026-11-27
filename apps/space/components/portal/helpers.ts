/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { format, formatDistanceToNow, parseISO } from "date-fns";
import { es } from "date-fns/locale";

export const dayLabel = (iso: string) => format(parseISO(iso), "EEEE d 'de' MMMM", { locale: es });
export const shortDate = (iso: string) => format(parseISO(iso), "d MMM", { locale: es });
export const ago = (iso: string) => formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: es });

export const isVideo = (type: string | undefined) => !!type && type.toLowerCase().startsWith("video/");
