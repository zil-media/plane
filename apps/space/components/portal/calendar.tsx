/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import {
  addDays,
  addMonths,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  isToday,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import { es } from "date-fns/locale";
import { ChevronLeft, ChevronRight } from "lucide-react";
// plane imports
import type { TZilPortalPost } from "@plane/types";
import { cn } from "@plane/utils";
// local imports
import { dayLabel, isoDay, monthLabel } from "./helpers";
import { PortalPostCard } from "./post-card";

type Props = {
  month: Date;
  posts: TZilPortalPost[];
  loading: boolean;
  onMonthChange: (month: Date) => void;
  onOpen: (postId: string) => void;
};

const WEEK = { weekStartsOn: 1 as const };

/** The month a calendar shows, as the range the API is asked for. */
export const monthRange = (month: Date) => ({
  start: isoDay(startOfWeek(startOfMonth(month), WEEK)),
  end: isoDay(endOfWeek(endOfMonth(month), WEEK)),
});

/** Month view on a computer, a list by day on a phone. */
export function PortalCalendar({ month, posts, loading, onMonthChange, onOpen }: Props) {
  const byDay = useMemo(() => {
    const map = new Map<string, TZilPortalPost[]>();
    for (const post of posts) {
      if (!post.publish_date) continue;
      map.set(post.publish_date, [...(map.get(post.publish_date) ?? []), post]);
    }
    return map;
  }, [posts]);

  const days = useMemo(() => {
    const first = startOfWeek(startOfMonth(month), WEEK);
    const last = endOfWeek(endOfMonth(month), WEEK);
    const out: Date[] = [];
    for (let day = first; day <= last; day = addDays(day, 1)) out.push(day);
    return out;
  }, [month]);

  // ISO days sort as text; posts arrive ordered by date, so the map's keys already are
  const monthDays = [...byDay.keys()].filter((day) => day.startsWith(format(month, "yyyy-MM")));

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-16 font-semibold text-primary capitalize">{monthLabel(month)}</h2>
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="Mes anterior"
            onClick={() => onMonthChange(addMonths(month, -1))}
            className="grid size-8 place-items-center rounded-md text-secondary hover:bg-layer-1"
          >
            <ChevronLeft className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => onMonthChange(startOfMonth(new Date()))}
            className="rounded-md px-2 py-1 text-13 text-secondary hover:bg-layer-1"
          >
            Hoy
          </button>
          <button
            type="button"
            aria-label="Mes siguiente"
            onClick={() => onMonthChange(addMonths(month, 1))}
            className="grid size-8 place-items-center rounded-md text-secondary hover:bg-layer-1"
          >
            <ChevronRight className="size-4" />
          </button>
        </div>
      </div>

      {/* computer: the month */}
      <div className={cn("hidden overflow-hidden rounded-md border border-subtle md:block", loading && "opacity-60")}>
        <div className="grid grid-cols-7 border-b border-subtle bg-layer-1">
          {days.slice(0, 7).map((day) => (
            <div key={day.toISOString()} className="px-2 py-1.5 text-11 font-medium text-tertiary capitalize">
              {format(day, "EEE", { locale: es })}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7">
          {days.map((day) => {
            const key = isoDay(day);
            return (
              <div
                key={key}
                className={cn(
                  "min-h-28 space-y-1 border-r border-b border-subtle p-1.5 [&:nth-child(7n)]:border-r-0",
                  !isSameMonth(day, month) && "bg-layer-1"
                )}
              >
                <span
                  className={cn(
                    "inline-grid size-6 place-items-center rounded-full text-11",
                    isToday(day) ? "bg-accent-primary text-on-color" : "text-tertiary"
                  )}
                >
                  {format(day, "d")}
                </span>
                {(byDay.get(key) ?? []).map((post) => (
                  <PortalPostCard key={post.id} post={post} onOpen={onOpen} />
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* phone: day by day */}
      <div className={cn("space-y-4 md:hidden", loading && "opacity-60")}>
        {monthDays.length === 0 && !loading && (
          <p className="rounded-md border border-subtle p-4 text-center text-13 text-tertiary">
            No hay publicaciones este mes.
          </p>
        )}
        {monthDays.map((day) => (
          <div key={day} className="space-y-2">
            <h3 className="text-13 font-medium text-secondary first-letter:uppercase">{dayLabel(day)}</h3>
            {(byDay.get(day) ?? []).map((post) => (
              <PortalPostCard key={post.id} post={post} onOpen={onOpen} />
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
