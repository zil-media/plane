/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Input } from "@plane/ui";
import { cn } from "@plane/utils";
import type { TDraftKind, TDraftQuestion } from "@/services/support.service";
import { supportService } from "@/services/support.service";

/** Mirror of MIN_REVIEWABLE on the server: below this the model isn't called. */
const MIN_CHARS = 40;
/**
 * How much stillness counts as "done writing". What gets reviewed is a quiet draft, not one being
 * typed: a shorter wait re-asks on every comma while the person is still mid-sentence.
 */
const IDLE_MS = 3000;

type Props = {
  kind: TDraftKind;
  /** The request's title, when the form has one apart from the body. */
  title?: string;
  text: string;
  /** Turn the review off without unmounting (e.g. while the form is being sent). */
  enabled?: boolean;
  /**
   * Stop asking but keep what's there (questions and answers): for a form step where the draft
   * can't change and the panel isn't visible, so a late review can't land unseen.
   */
  paused?: boolean;
  /** What was answered, ready to append to the request. Empty while nothing is answered. */
  onAnswersChange: (appendix: string) => void;
  className?: string;
};

/**
 * Draft review: once the person stops typing, a cheap model reads what they wrote and, if
 * something essential is missing, asks right there, while the context is still fresh. Asking a
 * day later by comment gets the same answer much slower, from someone already on something else.
 *
 * It never blocks anything: no disabled submit, no errors, no required question. With no review
 * the panel doesn't show and the form works exactly as before. Answers travel apart from the text
 * (being edited by a third party while typing is unsettling) and the form appends them on send.
 */
export function DraftReview(props: Props) {
  const { kind, title = "", text, enabled = true, paused = false, onAnswersChange, className } = props;
  const { t } = useTranslation();
  const [checking, setChecking] = useState(false);
  const [questions, setQuestions] = useState<TDraftQuestion[] | null>(null);
  const [ready, setReady] = useState(false);
  // Keyed by question, not position: a re-review that reorders questions keeps what was answered.
  const [answers, setAnswers] = useState<Record<string, string>>({});
  // Read inside the effect without re-triggering it: answering must not fire another review.
  const answersRef = useRef<Record<string, string>>({});
  // Last draft reviewed, so effects re-running for other reasons don't repeat the call.
  const lastReviewed = useRef<string | null>(null);

  const draftKey = `${title.trim()}\n${text.trim()}`;
  const longEnough = (title.trim() + text.trim()).length >= MIN_CHARS;

  useEffect(() => {
    if (!enabled || !longEnough) {
      setQuestions(null);
      setReady(false);
      // The questions are gone, so the same text coming back (undo, paste) has to be reviewed again.
      lastReviewed.current = null;
      return;
    }
    if (paused || lastReviewed.current === draftKey) return;

    const controller = new AbortController();
    const review = async () => {
      setChecking(true);
      const result = await supportService.reviewDraft(
        kind,
        // The screen travels with the request anyway: given to the reviewer so it doesn't spend a
        // question on "which screen?".
        // Capped like the server's serializer: past it the call would just answer 400.
        { title: title.trim().slice(0, 200), text: text.trim().slice(0, 4000), screen: window.location.pathname },
        controller.signal
      );
      if (controller.signal.aborted) return;
      lastReviewed.current = draftKey;
      setChecking(false);
      // null = couldn't review: whatever was there stays, and nothing is announced.
      if (!result) return;
      setReady(result.ready);
      // An answered question doesn't vanish because the next review didn't repeat it: the person
      // wrote it and it gets sent. Unanswered ones do go.
      setQuestions((previous) => {
        const next = result.ready ? [] : result.questions;
        const answered = (previous ?? []).filter(
          (q) => (answersRef.current[q.question] ?? "").trim() && !next.some((n) => n.question === q.question)
        );
        return [...next, ...answered];
      });
    };
    const timer = setTimeout(() => void review(), IDLE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
      setChecking(false);
    };
  }, [kind, title, text, draftKey, longEnough, enabled, paused]);

  // Only what was actually answered is sent, in the order it was asked.
  useEffect(() => {
    const appendix = (questions ?? [])
      .map((q) => ({ q: q.question, a: (answers[q.question] ?? "").trim() }))
      .filter(({ a }) => a.length > 0)
      .map(({ q, a }) => `${q}\n${a}`)
      .join("\n\n");
    onAnswersChange(appendix);
  }, [questions, answers, onAnswersChange]);

  const setAnswer = useCallback((question: string, value: string) => {
    setAnswers((previous) => {
      const next = { ...previous, [question]: value };
      answersRef.current = next;
      return next;
    });
  }, []);

  if (!enabled || !longEnough) return null;
  const hasQuestions = !!questions && questions.length > 0;
  // Answered questions stay listed (they get sent), but only unanswered ones are "missing".
  const missing = (questions ?? []).filter((q) => !(answers[q.question] ?? "").trim()).length;
  if (!checking && !hasQuestions && !ready) return null;

  return (
    <div className={cn("flex flex-col gap-2 rounded-md border border-subtle bg-layer-1 px-3 py-2.5", className)}>
      {checking && (
        <span className="flex items-center gap-2 text-caption-sm-regular text-tertiary">
          <Loader2 className="size-3 shrink-0 animate-spin" />
          {t("helpdesk.review.checking")}
        </span>
      )}
      {!checking && ready && missing === 0 && (
        <span className="flex items-center gap-2 text-caption-sm-regular text-tertiary">
          <Check className="size-3 shrink-0 text-success-primary" />
          {t("helpdesk.review.ready")}
        </span>
      )}
      {hasQuestions && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-col">
            {missing > 0 && (
              <span className="text-body-xs-medium text-primary">
                {t(missing === 1 ? "helpdesk.review.one_missing" : "helpdesk.review.some_missing")}
              </span>
            )}
            <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.review.hint")}</span>
          </div>
          {questions.map((q) => (
            <label key={q.question} className="flex flex-col gap-1">
              <span className="text-caption-sm-medium text-primary">
                {q.question}
                {q.why && <span className="block text-caption-sm-regular text-tertiary">{q.why}</span>}
              </span>
              <Input
                value={answers[q.question] ?? ""}
                onChange={(event) => setAnswer(q.question, event.target.value)}
                placeholder={t("helpdesk.review.answer_placeholder")}
                maxLength={500}
                className="w-full text-body-xs-regular"
              />
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
