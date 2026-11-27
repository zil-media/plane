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

/** 0:42, 12:05, 1:02:03 (as the API labels a comment's moment). */
export const clock = (seconds: number) => {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
};

/** Time left, short: "2 d 4 h", "3 h 12 min", "12 min". */
export const remaining = (ms: number) => {
  const minutes = Math.max(1, Math.ceil(ms / 60_000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  if (days) return `${days} d ${hours} h`;
  if (hours) return `${hours} h ${minutes % 60} min`;
  return `${minutes} min`;
};
