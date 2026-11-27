/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { format, formatDistanceToNow, parseISO } from "date-fns";
import type { Locale } from "date-fns";
import { enUS, es } from "date-fns/locale";

/** The date-fns locale for the language Ops' i18n is showing (the client's profile language). */
export const dateLocale = (language: string | undefined): Locale => (language?.startsWith("en") ? enUS : es);

// "{weekday} {day} de {month}" in Spanish, "{weekday}, {month} {day}" in English
export const dayLabel = (iso: string, locale: Locale) =>
  format(parseISO(iso), locale === es ? "EEEE d 'de' MMMM" : "EEEE, MMMM d", { locale });
export const shortDate = (iso: string, locale: Locale) => format(parseISO(iso), "d MMM", { locale });
export const ago = (iso: string, locale: Locale) => formatDistanceToNow(parseISO(iso), { addSuffix: true, locale });

export const isVideo = (type: string | undefined) => !!type && type.toLowerCase().startsWith("video/");
