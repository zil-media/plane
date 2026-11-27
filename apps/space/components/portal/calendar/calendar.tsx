/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { format } from "date-fns";
import { es } from "date-fns/locale";
// plane imports
import { ChevronLeftIcon, ChevronRightIcon } from "@plane/propel/icons";
import type { ICalendarDate, ICalendarWeek, TZilPortalPost } from "@plane/types";
import { EStartOfTheWeek } from "@plane/types";
import { Row } from "@plane/ui";
import { cn, generateCalendarData, getOrderedDays, renderFormattedPayloadDate } from "@plane/utils";
// local imports
import { PortalCalendarDayTile } from "./day-tile";
import { PortalCalendarIssueBlocks } from "./issue-blocks";

type Props = {
  month: Date;
  posts: TZilPortalPost[];
  loading: boolean;
  onMonthChange: (month: Date) => void;
  onOpen: (postId: string) => void;
  openPostId?: string | null;
};

// the client's week starts on Monday (Argentina)
const START_OF_WEEK = EStartOfTheWeek.MONDAY;

/** The weeks of a month, as Ops' calendar store builds them (generateCalendarData). */
const weeksOf = (month: Date): ICalendarWeek[] => {
  const payload = generateCalendarData(null, month, START_OF_WEEK);
  const weeks = payload[`y-${month.getFullYear()}`]?.[`m-${month.getMonth()}`] ?? {};
  // the generator keys weeks by sequential index (w-0, w-1, …)
  return Object.keys(weeks).map((_, index) => weeks[`w-${index}`]);
};

/** The range of days the month shows, for the API. */
export const monthRange = (month: Date) => {
  const weeks = weeksOf(month);
  const first = Object.keys(weeks[0] ?? {});
  const last = Object.keys(weeks[weeks.length - 1] ?? {});
  return { start: first[0] ?? "", end: last[last.length - 1] ?? "" };
};

/**
 * The portal's calendar: a read-only copy of Ops' calendar mode (month layout,
 * apps/web/core/components/issues/issue-layouts/calendar/calendar.tsx): the same header, week header,
 * week rows and day tiles; on a phone, the list of the day picked, as in Ops.
 */
export function PortalCalendar({ month, posts, loading, onMonthChange, onOpen, openPostId }: Props) {
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());
  const weeks = useMemo(() => weeksOf(month), [month]);
  const postsByDay = useMemo(() => {
    const map = new Map<string, TZilPortalPost[]>();
    for (const post of posts) {
      if (!post.publish_date) continue;
      map.set(post.publish_date, [...(map.get(post.publish_date) ?? []), post]);
    }
    return map;
  }, [posts]);
  const orderedDays = useMemo(
    () => getOrderedDays(Object.values(weeks[0] ?? {}), (item) => item.date.getDay(), START_OF_WEEK),
    [weeks]
  );

  const handleToday = () => {
    const today = new Date();
    onMonthChange(new Date(today.getFullYear(), today.getMonth(), 1));
    setSelectedDate(today);
  };

  const selectedPayload = renderFormattedPayloadDate(selectedDate) ?? "";
  const selectedPosts = postsByDay.get(selectedPayload) ?? [];

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* header (Ops' CalendarHeader) */}
      <Row className="mb-4 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            aria-label="Mes anterior"
            className="grid place-items-center"
            onClick={() => onMonthChange(new Date(month.getFullYear(), month.getMonth() - 1, 1))}
          >
            <ChevronLeftIcon height={16} width={16} strokeWidth={2} />
          </button>
          <button
            type="button"
            aria-label="Mes siguiente"
            className="grid place-items-center"
            onClick={() => onMonthChange(new Date(month.getFullYear(), month.getMonth() + 1, 1))}
          >
            <ChevronRightIcon height={16} width={16} strokeWidth={2} />
          </button>
          <span className="text-18 font-semibold first-letter:uppercase">
            {format(month, "MMMM yyyy", { locale: es })}
          </span>
        </div>
        <button
          type="button"
          className="rounded-sm bg-layer-transparent px-2.5 py-1 text-11 font-medium text-secondary hover:bg-layer-transparent-hover hover:text-primary"
          onClick={handleToday}
        >
          Hoy
        </button>
      </Row>

      <div className="flex w-full flex-col overflow-hidden rounded-md border border-subtle">
        {/* week header (Ops' CalendarWeekHeader) */}
        <div className="relative sticky top-0 z-[1] grid grid-cols-7 divide-subtle-1 text-13 font-medium md:divide-x-[0.5px]">
          {loading && (
            <div className="absolute h-[1.5px] w-3/4 animate-[bar-loader_2s_linear_infinite] bg-accent-primary" />
          )}
          {orderedDays.map((day: ICalendarDate) => (
            <div
              key={day.date.getDay()}
              className="flex h-11 items-center justify-center bg-layer-1 px-4 capitalize md:justify-end"
            >
              {format(day.date, "EEE", { locale: es })}
            </div>
          ))}
        </div>

        {/* weeks (Ops' CalendarWeekDays) */}
        <div className="grid h-full w-full grid-cols-1 divide-y-[0.5px] divide-subtle-1">
          {weeks.map((week) => (
            <div key={Object.keys(week)[0]} className="grid grid-cols-7 divide-subtle-1 md:divide-x-[0.5px]">
              {getOrderedDays(Object.values(week), (item) => item.date.getDay(), START_OF_WEEK).map(
                (date: ICalendarDate) => (
                  <PortalCalendarDayTile
                    key={renderFormattedPayloadDate(date.date)}
                    date={date}
                    postsByDay={postsByDay}
                    selectedDate={selectedDate}
                    setSelectedDate={setSelectedDate}
                    onOpen={onOpen}
                    openPostId={openPostId}
                  />
                )
              )}
            </div>
          ))}
        </div>
      </div>

      {/* mobile view: the day picked */}
      <div className={cn("md:hidden", loading && "opacity-60")}>
        <p className="p-4 text-18 font-semibold first-letter:uppercase">
          {format(selectedDate, "EEEE d 'de' MMMM", { locale: es })}
        </p>
        {selectedPosts.length === 0 ? (
          <p className="px-4 text-13 text-tertiary">No hay publicaciones este día.</p>
        ) : (
          <PortalCalendarIssueBlocks posts={selectedPosts} onOpen={onOpen} openPostId={openPostId} />
        )}
      </div>
    </div>
  );
}
