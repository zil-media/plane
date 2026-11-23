/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useState } from "react";
import { cn } from "@plane/utils";
// hooks
import { getValueFromLocalStorage, setValueIntoLocalStorage } from "@/hooks/use-local-storage";

// eslint-disable-next-line no-unassigned-import
import "./attention-highlight.css";

/** Cada novedad que se quiera destacar necesita su clave acá: así se ve de un
 *  vistazo qué está resaltado hoy, y borrar una fila apaga el realce. */
export const ATTENTION_KEYS = {
  supportBoard: "support-board",
} as const;

export type TAttentionKey = (typeof ATTENTION_KEYS)[keyof typeof ATTENTION_KEYS];

const STORAGE_PREFIX = "zil-attention-seen:";

/**
 * Marca algo como novedad hasta que la persona lo abre una vez.
 *
 * Arranca siempre en "ya visto" y recién después de montar consulta el
 * navegador: el markup prerenderizado y el primer render del cliente tienen que
 * coincidir, y el estado guardado sólo existe del lado del cliente.
 */
export function useAttention(key: TAttentionKey) {
  const [isNew, setIsNew] = useState(false);

  useEffect(() => {
    setIsNew(!getValueFromLocalStorage(`${STORAGE_PREFIX}${key}`, false));
  }, [key]);

  const dismiss = useCallback(() => {
    setIsNew(false);
    setValueIntoLocalStorage(`${STORAGE_PREFIX}${key}`, true);
  }, [key]);

  return { isNew, dismiss };
}

type TAttentionDotProps = {
  active: boolean;
  children: React.ReactNode;
  className?: string;
};

/** Punto con el degradé sobre un ícono. Con `active` en false no pinta nada. */
export function AttentionDot({ active, children, className }: TAttentionDotProps) {
  if (!active) return <>{children}</>;

  return <span className={cn("zil-attention-dot", className)}>{children}</span>;
}

type TAttentionTextProps = {
  active: boolean;
  children: React.ReactNode;
  className?: string;
};

/** El mismo degradé recortado sobre el texto, para una entrada de menú. */
export function AttentionText({ active, children, className }: TAttentionTextProps) {
  if (!active) return <>{children}</>;

  return <span className={cn("zil-attention-text", className)}>{children}</span>;
}
