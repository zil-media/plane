/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { format } from "date-fns";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { ICalendarDate, TZilPortalPost } from "@plane/types";
import { cn, renderFormattedPayloadDate } from "@plane/utils";
// local imports
import { dateLocale } from "../helpers";
import { PortalCalendarIssueBlocks } from "./issue-blocks";

type Props = {
  date: ICalendarDate;
  postsByDay: Map<string, TZilPortalPost[]>;
  selectedDate: Date;
  setSelectedDate: (date: Date) => void;
  onOpen: (postId: string) => void;
  openPostId?: string | null;
};

/** A copy of Ops' CalendarDayTile (month layout), read-only: no drag and drop, no quick add. */
export function PortalCalendarDayTile(props: Props) {
  const { date, postsByDay, selectedDate, setSelectedDate, onOpen, openPostId } = props;
  const { currentLocale } = useTranslation();
  const formattedDatePayload = renderFormattedPayloadDate(date.date);
  if (!formattedDatePayload) return null;
  const posts = postsByDay.get(formattedDatePayload) ?? [];

  const isToday = date.date.toDateString() === new Date().toDateString();
  const isSelectedDate = date.date.toDateString() == selectedDate.toDateString();
  const isWeekend = [0, 6].includes(date.date.getDay());
  const normalBackground = isWeekend ? "bg-layer-1" : "bg-layer-transparent";

  return (
    <div className="group relative flex h-full w-full flex-col">
      {/* header */}
      <div
        className={`hidden flex-shrink-0 justify-end px-2 py-1.5 text-right text-11 md:flex ${
          date.is_current_month ? "font-medium" : "text-tertiary"
        } ${isWeekend ? "bg-layer-1" : "bg-layer-transparent"} `}
      >
        {date.date.getDate() === 1 && format(date.date, "MMM", { locale: dateLocale(currentLocale) }) + " "}
        {isToday ? (
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent-primary text-on-color">
            {date.date.getDate()}
          </span>
        ) : (
          <>{date.date.getDate()}</>
        )}
      </div>

      {/* content */}
      <div className="hidden h-full w-full md:block">
        <div className={cn("h-full min-h-[5rem] w-full select-none", normalBackground)}>
          <PortalCalendarIssueBlocks posts={posts} onOpen={onOpen} openPostId={openPostId} />
        </div>
      </div>

      {/* Mobile view content */}
      <button
        type="button"
        onClick={() => setSelectedDate(date.date)}
        className={cn(
          "mx-auto flex h-full w-full cursor-pointer flex-col items-center justify-start py-2.5 text-13 font-medium opacity-80 md:hidden",
          { "bg-layer-2": !isWeekend }
        )}
      >
        <div
          className={cn("flex size-6 items-center justify-center rounded-full", {
            "bg-accent-primary text-on-color": isSelectedDate,
            "bg-accent-primary/10 text-accent-primary": isToday && !isSelectedDate,
          })}
        >
          {date.date.getDate()}
        </div>
        {/* a dot when the day has posts, so the phone shows where to tap */}
        <span className={cn("mt-1 size-1 rounded-full", posts.length ? "bg-accent-primary" : "bg-transparent")} />
      </button>
    </div>
  );
}
