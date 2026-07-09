/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useId, useState } from "react";
// eslint-disable-next-line no-unassigned-import
import "./animated-zil-logo.css";

type TAnimatedZilLogoProps = {
  size?: number;
  className?: string;
};

/**
 * Etapas de la animación, en ciclo. El logo recorre estas etapas en orden y
 * vuelve a empezar. Está pensado para AGREGAR etapas a futuro: sumás un objeto
 * acá (id + duración) y su regla CSS `[data-stage="id"] …` correspondiente.
 *
 *   1. sun   → las estrellas suben y, coordinado, el Sol de Mayo aparece y flota
 *   2. stars → el Sol baja y, coordinado, las estrellas entran juntas desde arriba
 */
const STAGES: { id: string; ms: number }[] = [
  { id: "sun", ms: 12000 },
  { id: "stars", ms: 12000 },
];

const ZIL_PATH =
  "M12.8857 19.0928H21.4629V32H0L10.1328 19.0928H1.67871V6.18555H23.0186L12.8857 19.0928ZM39.0742 32H26.166V6.18555H39.0742V32ZM57.001 32H44.0938V0H57.001V32Z";
// Estrella de 5 puntas centrada en (0,0), radio exterior ~5.2 (unidades del viewBox).
const STAR_PATH =
  "M0,-5.2 L1.167,-1.608 L4.947,-1.608 L1.889,0.614 L3.058,4.208 L0,1.986 L-3.058,4.208 L-1.889,0.614 L-4.947,-1.608 L-1.167,-1.608 Z";

/**
 * Animated Zil Logo — Edición Mundial Argentina.
 * Fondo de blobs celeste/blanco animados clipeados a las letras ZIL.
 * Sol de Mayo + tres estrellas, coreografiados por etapas (ver STAGES).
 * 100% SVG. El CSS reacciona al atributo `data-stage` del contenedor.
 *
 * Ported 1:1 from leads' `src/components/AnimatedZilLogo.tsx` — same
 * choreography/keyframes (see animated-zil-logo.css), only relocated into
 * Plane's component tree and pointed at a copy of the Sol de Mayo asset
 * under `public/zil/`.
 */
export function AnimatedZilLogo({ size = 48, className = "" }: TAnimatedZilLogoProps) {
  const uniqueId = useId().replace(/:/g, "_");

  // Avanza por las etapas en ciclo. Respeta prefers-reduced-motion (no cicla).
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const mq = typeof window !== "undefined" ? window.matchMedia?.("(prefers-reduced-motion: reduce)") : null;
    if (mq?.matches) return;
    const t = setTimeout(() => setStage((s) => (s + 1) % STAGES.length), STAGES[stage].ms);
    return () => clearTimeout(t);
  }, [stage]);

  return (
    <div
      className={`animated-zil-logo ${className}`}
      style={{ width: size, height: size * (32 / 57) }}
      data-stage={STAGES[stage].id}
    >
      <svg width="100%" height="100%" viewBox="0 0 57 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <clipPath id={`clip_${uniqueId}`}>
            <path d={ZIL_PATH} />
          </clipPath>

          {/* Blur moderado para los blobs internos */}
          <filter id={`blur_${uniqueId}`} x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="4" />
          </filter>
        </defs>

        {/* El Logo Principal — Clipeado a la forma de ZIL */}
        <g clipPath={`url(#clip_${uniqueId})`}>
          {/* Fondo celeste (bandera) */}
          <rect className="zil-bg" x="-10" y="-10" width="77" height="52" fill="#75AADB" />

          {/* Blobs animados en el interior */}
          <g filter={`url(#blur_${uniqueId})`}>
            <g className="zil-blob zil-blob-white1">
              <circle cx="6" cy="4" r="18" fill="#FFFFFF" fillOpacity="0.85" />
            </g>
            <g className="zil-blob zil-blob-cel1">
              <circle cx="50" cy="26" r="20" fill="#4A90C4" fillOpacity="0.9" />
            </g>
            <g className="zil-blob zil-blob-white2">
              <circle cx="28" cy="14" r="12" fill="#FFFFFF" fillOpacity="0.7" />
            </g>
            <g className="zil-blob zil-blob-cel2">
              <circle cx="14" cy="28" r="14" fill="#5BACD8" fillOpacity="0.8" />
            </g>
          </g>

          {/* Sol de Mayo — etapa "sun": sube y flota; etapa "sun-out": se va. */}
          <g className="zil-sol-move">
            <image
              href="/zil/Sol_de_Mayo-Bandera_de_Argentina.svg"
              x="-5.5"
              y="1"
              width="68"
              height="68"
              preserveAspectRatio="xMidYMid meet"
            />
          </g>

          {/* Tres estrellas — tricampeón (forma estilo AFA, la del medio más
              grande). DENTRO del clip de las letras: caen desde arriba en la
              etapa "stars" y se revelan dentro del wordmark (se recortan a la
              forma de las letras, a propósito). Cada estrella es un nodo aparte.
              Nesting: translate = posición, scale = tamaño, path = animación. */}
          <g className="zil-stars">
            {/* Escala del CONJUNTO (×1.4) alrededor de su centro y bajado a y=25 */}
            <g transform="translate(32.6 22) scale(1.4) translate(-32.6 -21)">
              <g transform="translate(16.6 22)">
                <g transform="scale(1.6)">
                  <path className="zil-star zil-star-1" d={STAR_PATH} />
                </g>
              </g>
              <g transform="translate(32.6 19)">
                <g transform="scale(2.2)">
                  <path className="zil-star zil-star-2" d={STAR_PATH} />
                </g>
              </g>
              <g transform="translate(48.6 22)">
                <g transform="scale(1.6)">
                  <path className="zil-star zil-star-3" d={STAR_PATH} />
                </g>
              </g>
            </g>
          </g>
        </g>
      </svg>
    </div>
  );
}
