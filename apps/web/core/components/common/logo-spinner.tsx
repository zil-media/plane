/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Zil logo loader — faithful port of leads' ZilLogoLoader (only recolored to brand blue).

// isotype halves (top + bottom), outline and filled variants
const TOP_OUTLINE =
  "M59.2373 0L33.4619 32.8369L30.8994 36.0859H0V0H59.2373ZM3.24902 3.24902V32.8369H29.3682L52.583 3.24902H3.24902Z";
const TOP_FILLED = "M59.2373 0L33.4619 32.8369L30.8994 36.0859H0V0H59.2373Z";
const BOTTOM_OUTLINE =
  "M0 36.0859L25.7754 3.24903L28.3379 2.70131e-06L59.2373 0L59.2373 36.0859L0 36.0859ZM55.9883 32.8369L55.9883 3.24902L29.8691 3.24903L6.6543 32.8369L55.9883 32.8369Z";
const BOTTOM_FILLED = "M0 36.0859L25.7754 3.24903L28.3379 2.70131e-06L59.2373 0L59.2373 36.0859L0 36.0859Z";

const BRAND = "#6D86FF"; // Zil brand blue (--color-primary-blue)

const CSS = `
.zil-ll { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.zil-ll svg { display: block; width: 100%; height: auto; }

.zil-ll-pulse { animation: zil-scale-pulse 2.5s cubic-bezier(0.4, 0, 0.2, 1) infinite; }

.zil-ll-top { position: relative; width: 100%; animation: zil-join-top 2.5s cubic-bezier(0.4, 0, 0.2, 1) infinite; }
.zil-ll-bottom { position: relative; width: 100%; margin-top: -6.94%; animation: zil-join-bottom 2.5s cubic-bezier(0.4, 0, 0.2, 1) infinite; }

.zil-ll-fill { animation: zil-fade-fill 2.5s cubic-bezier(0.4, 0, 0.2, 1) infinite; }
.zil-ll-outline { position: absolute; inset: 0; animation: zil-fade-outline 2.5s cubic-bezier(0.4, 0, 0.2, 1) infinite; }

@keyframes zil-join-top {
  0% { transform: translateX(-50%); opacity: 0; }
  15% { transform: translateX(-25%); opacity: 1; }
  25% { transform: translateX(0); opacity: 1; }
  60% { transform: translateX(0); opacity: 1; }
  75% { transform: translateX(-25%); opacity: 0; }
  85% { transform: translateX(-50%); opacity: 0; }
  100% { transform: translateX(-50%); opacity: 0; }
}
@keyframes zil-join-bottom {
  0% { transform: translateX(50%); opacity: 0; }
  15% { transform: translateX(25%); opacity: 1; }
  25% { transform: translateX(-10%); opacity: 1; }
  60% { transform: translateX(-10%); opacity: 1; }
  75% { transform: translateX(25%); opacity: 0; }
  85% { transform: translateX(50%); opacity: 0; }
  100% { transform: translateX(50%); opacity: 0; }
}
@keyframes zil-fade-fill {
  0%, 22% { opacity: 0; }
  23%, 60% { opacity: 1; }
  61%, 100% { opacity: 0; }
}
@keyframes zil-fade-outline {
  0%, 22% { opacity: 1; }
  23%, 60% { opacity: 0; }
  61%, 100% { opacity: 1; }
}
@keyframes zil-scale-pulse {
  0%, 22% { transform: scale(1); }
  23% { transform: scale(1.05); }
  25.5% { transform: scale(1); }
  100% { transform: scale(1); }
}

.zil-ll-ripple { position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; pointer-events: none; z-index: 0; }
.zil-ll-ripple .zil-ll-r-top { width: 100%; transform: translateX(0); opacity: 0; }
.zil-ll-ripple .zil-ll-r-bottom { width: 100%; margin-top: -6.94%; transform: translateX(-10%); opacity: 0; }
.zil-ll-ripple-1 { animation: zil-ripple-1 2.5s cubic-bezier(0, 0, 0.2, 1) infinite; }
.zil-ll-ripple-2 { animation: zil-ripple-2 2.5s cubic-bezier(0, 0, 0.2, 1) infinite; }

@keyframes zil-ripple-1 {
  0%, 23% { opacity: 0; transform: scale(1); }
  24% { opacity: 0.8; transform: scale(1); }
  45% { opacity: 0; transform: scale(1.4); }
  100% { opacity: 0; transform: scale(1.4); }
}
@keyframes zil-ripple-2 {
  0%, 23% { opacity: 0; transform: scale(1); }
  24.5% { opacity: 0.6; transform: scale(1); }
  50% { opacity: 0; transform: scale(1.6); }
  100% { opacity: 0; transform: scale(1.6); }
}
`;

const Half = ({ path, className, color }: { path: string; className?: string; color: string }) => (
  <svg viewBox="0 0 60 37" fill={color} xmlns="http://www.w3.org/2000/svg" className={className} aria-hidden="true">
    <path d={path} fill={color} />
  </svg>
);

export function LogoSpinner({ size = 84 }: { size?: number }) {
  return (
    // text-primary drives the main mark (currentColor): black on light, white on dark — like leads.
    <div className="zil-ll zil-ll-pulse text-primary" style={{ width: size }} aria-label="Loading">
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      {/* ripple ghosts — brand blue accent (same role as in leads) */}
      <div className="zil-ll-ripple zil-ll-ripple-1">
        <Half path={TOP_FILLED} className="zil-ll-r-top" color={BRAND} />
        <Half path={BOTTOM_FILLED} className="zil-ll-r-bottom" color={BRAND} />
      </div>
      <div className="zil-ll-ripple zil-ll-ripple-2">
        <Half path={TOP_FILLED} className="zil-ll-r-top" color={BRAND} />
        <Half path={BOTTOM_FILLED} className="zil-ll-r-bottom" color={BRAND} />
      </div>

      {/* main mark — monochrome, follows theme text color */}
      <div style={{ position: "relative", zIndex: 10, width: "100%" }}>
        <div className="zil-ll-top">
          <Half path={TOP_OUTLINE} className="zil-ll-outline" color="currentColor" />
          <Half path={TOP_FILLED} className="zil-ll-fill" color="currentColor" />
        </div>
        <div className="zil-ll-bottom">
          <Half path={BOTTOM_OUTLINE} className="zil-ll-outline" color="currentColor" />
          <Half path={BOTTOM_FILLED} className="zil-ll-fill" color="currentColor" />
        </div>
      </div>
    </div>
  );
}
