/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { Maximize, Pause, Play, Volume2, VolumeX } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Tooltip } from "@plane/propel/tooltip";
import { cn } from "@plane/utils";
// local imports
import { clock } from "./helpers";

/** A comment pinned to a second of the video: a mark on its timeline. */
export type TVideoMarker = {
  id: string;
  at: number;
  author: string;
  text: string;
  /** the client's own change, not sent yet */
  draft?: boolean;
};

type Props = {
  src: string | undefined;
  name: string;
  markers: TVideoMarker[];
  /** the comment whose mark was picked last (its mark stands out) */
  activeMarker?: string | null;
  onPlayer: (element: HTMLVideoElement | null) => void;
  onTime: (seconds: number) => void;
  onMarker: (marker: TVideoMarker) => void;
};

/**
 * The post's video with its own controls, so its timeline can carry the comments: each comment
 * pinned to a second is a mark on the bar (like YouTube's), its text on hover, and a click on it
 * goes to that second and to the comment.
 */
export function PortalVideoPlayer({ src, name, markers, activeMarker, onPlayer, onTime, onMarker }: Props) {
  const { t } = useTranslation();
  const frame = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  const [duration, setDuration] = useState(0);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [dragging, setDragging] = useState(false);

  const toggle = () => {
    const element = video.current;
    if (!element) return;
    if (element.paused) void element.play().catch(() => undefined);
    else element.pause();
  };

  const seekTo = (clientX: number) => {
    const element = video.current;
    const rect = bar.current?.getBoundingClientRect();
    if (!element || !rect || !duration) return;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    element.currentTime = ratio * duration;
    setTime(element.currentTime);
  };

  const onBarDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
    seekTo(event.clientX);
  };

  const percent = (seconds: number) => (duration ? `${Math.min(100, (seconds / duration) * 100)}%` : "0%");

  return (
    <div ref={frame} className="group relative flex w-full flex-col bg-black">
      <video
        ref={(element) => {
          video.current = element;
          onPlayer(element);
        }}
        src={src}
        preload="metadata"
        playsInline
        onClick={toggle}
        onLoadedMetadata={(event) => setDuration(event.currentTarget.duration || 0)}
        onDurationChange={(event) => setDuration(event.currentTarget.duration || 0)}
        onTimeUpdate={(event) => {
          if (!dragging) setTime(event.currentTarget.currentTime);
          onTime(event.currentTarget.currentTime);
        }}
        onSeeked={(event) => onTime(event.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onVolumeChange={(event) => setMuted(event.currentTarget.muted)}
        className="max-h-[60vh] w-full cursor-pointer object-contain"
        aria-label={name}
      >
        <track kind="captions" />
      </video>

      {/* controls: the timeline with the comments' marks, then play, time, sound, full screen */}
      <div className="flex flex-col gap-1 bg-surface-1 px-3 pt-3 pb-2">
        <div
          ref={bar}
          role="slider"
          tabIndex={0}
          aria-label={name}
          aria-valuemin={0}
          aria-valuemax={Math.round(duration)}
          aria-valuenow={Math.round(time)}
          aria-valuetext={clock(time)}
          onPointerDown={onBarDown}
          onPointerMove={(event) => dragging && seekTo(event.clientX)}
          onPointerUp={() => setDragging(false)}
          onKeyDown={(event) => {
            const element = video.current;
            if (!element) return;
            if (event.key === "ArrowRight") element.currentTime = Math.min(duration, element.currentTime + 5);
            if (event.key === "ArrowLeft") element.currentTime = Math.max(0, element.currentTime - 5);
          }}
          className="relative flex h-4 cursor-pointer items-center"
        >
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-layer-3">
            <div className="h-full bg-accent-primary" style={{ width: percent(time) }} />
          </div>
          {markers.map((marker) => (
            <Tooltip
              key={marker.id}
              position="top"
              tooltipHeading={`${clock(marker.at)} · ${marker.author}`}
              tooltipContent={marker.text}
            >
              <button
                type="button"
                aria-label={t("zil_portal.go_to_moment", { time: clock(marker.at) })}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={() => onMarker(marker)}
                className={cn(
                  "absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-accent-strong bg-surface-1 shadow-raised-100 transition-transform hover:scale-125",
                  marker.draft && "border-dashed",
                  activeMarker === marker.id && "scale-125 bg-accent-primary"
                )}
                style={{ left: percent(marker.at) }}
              />
            </Tooltip>
          ))}
        </div>
        <div className="flex items-center gap-3 text-secondary">
          <button
            type="button"
            onClick={toggle}
            aria-label={playing ? t("zil_portal.pause") : t("zil_portal.play")}
            className="hover:text-primary"
          >
            {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
          </button>
          <span className="text-12 tabular-nums">
            {clock(time)} / {clock(duration)}
          </span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => video.current && (video.current.muted = !video.current.muted)}
            aria-label={muted ? t("zil_portal.unmute") : t("zil_portal.mute")}
            className="hover:text-primary"
          >
            {muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
          </button>
          <button
            type="button"
            onClick={() => void frame.current?.requestFullscreen?.().catch(() => undefined)}
            aria-label={t("zil_portal.fullscreen")}
            className="hover:text-primary"
          >
            <Maximize className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
