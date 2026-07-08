/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import { cn } from "@plane/utils";

type AuthGradientProps = {
  className?: string;
};

/**
 * Animated "orb" gradient background inspired by the Zil brand mark.
 * Pure CSS (no Three.js) — soft, blurred, floating color blobs that sit
 * behind the auth panels. Theme-agnostic: the blobs are translucent brand
 * colors that read well over both the light and dark surfaces above them.
 */
export function AuthGradient({ className }: AuthGradientProps) {
  return (
    <div className={cn("pointer-events-none absolute inset-0 overflow-hidden", className)} aria-hidden>
      {/* Blue — primary Zil brand */}
      <span className="auth-orb auth-orb--blue" />
      {/* Violet */}
      <span className="auth-orb auth-orb--violet" />
      {/* Cyan */}
      <span className="auth-orb auth-orb--cyan" />
      {/* Pink */}
      <span className="auth-orb auth-orb--pink" />

      <style>{`
        .auth-orb {
          position: absolute;
          border-radius: 9999px;
          filter: blur(72px);
          opacity: 0.55;
          will-change: transform;
        }
        .auth-orb--blue {
          width: 34rem;
          height: 34rem;
          left: -6rem;
          top: -4rem;
          background: radial-gradient(circle at 30% 30%, #6d86ff, transparent 70%);
          animation: auth-orb-float-a 18s ease-in-out infinite;
        }
        .auth-orb--violet {
          width: 30rem;
          height: 30rem;
          right: -4rem;
          top: 6rem;
          background: radial-gradient(circle at 30% 30%, #a78bfa, transparent 70%);
          animation: auth-orb-float-b 22s ease-in-out infinite;
        }
        .auth-orb--cyan {
          width: 28rem;
          height: 28rem;
          left: 8%;
          bottom: -8rem;
          background: radial-gradient(circle at 30% 30%, #7dd3fc, transparent 70%);
          animation: auth-orb-float-c 20s ease-in-out infinite;
        }
        .auth-orb--pink {
          width: 26rem;
          height: 26rem;
          right: 6%;
          bottom: -6rem;
          background: radial-gradient(circle at 30% 30%, #f9a8d4, transparent 70%);
          animation: auth-orb-float-d 24s ease-in-out infinite;
        }
        @keyframes auth-orb-float-a {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(4rem, 3rem) scale(1.12); }
        }
        @keyframes auth-orb-float-b {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(-3rem, 4rem) scale(1.08); }
        }
        @keyframes auth-orb-float-c {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(3rem, -3rem) scale(1.1); }
        }
        @keyframes auth-orb-float-d {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(-4rem, -2rem) scale(1.14); }
        }
        @media (prefers-reduced-motion: reduce) {
          .auth-orb { animation: none !important; }
        }
      `}</style>
    </div>
  );
}
