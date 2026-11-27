/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment } from "react";
import { Dialog, Transition } from "@headlessui/react";
import { ExternalLink, X } from "lucide-react";
import useSWR from "swr";
// plane imports
import { SitesPortalService } from "@plane/services";
import { Loader } from "@plane/ui";
import { cn, getFileURL } from "@plane/utils";
// local imports
import { PortalComments } from "./comments";
import { STATUS_CLASS, dayLabel, isVideo } from "./helpers";
import { PortalContent } from "./portal-content";

const portalService = new SitesPortalService();

type Props = {
  projectId: string;
  postId: string | null;
  preview: boolean;
  onClose: () => void;
};

/** A post as it will look on the network: media big, copy below, date, status and the conversation. */
export function PortalPostDetail({ projectId, postId, preview, onClose }: Props) {
  const { data: post, error } = useSWR(postId ? `PORTAL_POST_${postId}` : null, () =>
    portalService.retrievePost(projectId, postId as string)
  );

  return (
    <Transition.Root show={!!postId} as={Fragment}>
      <Dialog as="div" className="relative z-20" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-backdrop transition-opacity" />
        </Transition.Child>
        <div className="fixed inset-0 overflow-y-auto">
          <div className="flex min-h-full items-end justify-center sm:items-center sm:p-6">
            <Dialog.Panel className="relative w-full max-w-2xl rounded-t-lg bg-surface-1 shadow-raised-200 sm:rounded-lg">
              <button
                type="button"
                aria-label="Cerrar"
                onClick={onClose}
                className="absolute top-3 right-3 z-10 grid size-8 place-items-center rounded-full bg-surface-1 text-secondary hover:bg-layer-1"
              >
                <X className="size-4" />
              </button>
              {error ? (
                <p className="p-8 text-center text-13 text-tertiary">Esta publicación ya no está disponible.</p>
              ) : !post ? (
                <Loader className="space-y-3 p-6">
                  <Loader.Item height="320px" />
                  <Loader.Item height="20px" width="60%" />
                  <Loader.Item height="60px" />
                </Loader>
              ) : (
                <div className="space-y-6 pb-6">
                  {post.media.length > 0 && (
                    <div className="flex snap-x snap-mandatory overflow-x-auto rounded-t-lg bg-layer-1 sm:rounded-t-lg">
                      {post.media.map((item) => {
                        const src = getFileURL(item.url);
                        return (
                          <div key={item.id} className="w-full flex-shrink-0 snap-center">
                            {isVideo(item.type) ? (
                              <video src={src} controls className="max-h-[70vh] w-full object-contain">
                                <track kind="captions" />
                              </video>
                            ) : (
                              <img src={src} alt={item.name} className="max-h-[70vh] w-full object-contain" />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                  <div className={cn("space-y-3 px-6", post.media.length === 0 && "pt-6")}>
                    <div className="flex flex-wrap items-center gap-2 pr-8">
                      <span className={cn("rounded-sm px-1.5 py-0.5 text-11", STATUS_CLASS[post.status])}>
                        {post.status}
                      </span>
                      {post.labels.map((label) => (
                        <span
                          key={label.name}
                          className="rounded-sm border border-subtle px-1.5 py-0.5 text-11 text-secondary"
                        >
                          {label.name}
                        </span>
                      ))}
                    </div>
                    <Dialog.Title className="text-18 font-semibold text-primary">{post.name}</Dialog.Title>
                    <p className="text-13 text-secondary first-letter:uppercase">
                      {post.publish_date ? `Sale el ${dayLabel(post.publish_date)}` : "Fecha a definir"}
                    </p>
                    <PortalContent id={post.id} projectId={projectId} html={post.description_html} />
                    {post.links.length > 0 && (
                      <ul className="space-y-1">
                        {post.links.map((link) => (
                          <li key={link.url}>
                            <a
                              href={link.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-13 text-accent-primary hover:underline"
                            >
                              <ExternalLink className="size-3.5" />
                              {link.title}
                            </a>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="border-t border-subtle px-6 pt-5">
                    <PortalComments projectId={projectId} postId={post.id} preview={preview} />
                  </div>
                </div>
              )}
            </Dialog.Panel>
          </div>
        </div>
      </Dialog>
    </Transition.Root>
  );
}
