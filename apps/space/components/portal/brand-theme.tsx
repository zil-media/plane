/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import type { ReactNode } from "react";
// assets
import merakiFont from "@/app/assets/brands/meraki/red-hat-display-latin-wght-normal.woff2?url";
import merakiIso from "@/app/assets/brands/meraki/iso.svg?url";
import merakiLogo from "@/app/assets/brands/meraki/logo-dark.svg?url";
import zilBold from "@/app/assets/brands/zil/CircularStd-Bold.woff2?url";
import zilBook from "@/app/assets/brands/zil/CircularStd-Book.woff2?url";
import zilMedium from "@/app/assets/brands/zil/CircularStd-Medium.woff2?url";
import zilLogo from "@/app/assets/brands/zil/logo.svg?url";
import zilLogoWhite from "@/app/assets/brands/zil/logo-white.svg?url";

/** Whose brand the portal wears: the business unit that works the brand (the API's `unit`). */
export type TPortalUnit = "zil" | "meraki";

type TUnitBrand = {
  name: string;
  /** the logo on light surfaces (header, form) */
  logo: string;
  /** the logo over the gradient */
  logoOnGradient: string;
  font: string;
  fontFaces: string;
  /** accent: the unit's primary color, and darker steps for hover / pressed */
  accent: string;
  accentHover: string;
  accentActive: string;
  /** a light tint of the accent, for subtle fills and borders */
  accentSubtle: string;
  /** the gradient blobs, in the unit's colors */
  gradient: [string, string, string];
};

// Zil: brand book (~/.claude/brand/zil/BRAND.md): Circular, Azul Zil as the action color and the
// Gradient Zil (salmón → azul → negro). Meraki: its site (Red Hat Display, naranja, celeste, violeta).
export const PORTAL_UNITS: Record<TPortalUnit, TUnitBrand> = {
  zil: {
    name: "Zil",
    logo: zilLogo,
    logoOnGradient: zilLogoWhite,
    font: '"Circular Std", "Inter Variable", ui-sans-serif, system-ui, sans-serif',
    fontFaces: [
      [zilBook, 400],
      [zilMedium, 500],
      [zilBold, 700],
    ]
      .map(
        ([src, weight]) =>
          `@font-face{font-family:"Circular Std";src:url(${src}) format("woff2");font-weight:${weight};font-style:normal;font-display:swap}`
      )
      .join(""),
    accent: "#5271DD",
    accentHover: "#4561C8",
    accentActive: "#3A53AE",
    accentSubtle: "#E5EAFA",
    gradient: ["#FF7C7E", "#5271DD", "#000000"],
  },
  meraki: {
    name: "Meraki",
    logo: merakiLogo,
    logoOnGradient: merakiIso,
    font: '"Red Hat Display", "Inter Variable", ui-sans-serif, system-ui, sans-serif',
    fontFaces: `@font-face{font-family:"Red Hat Display";src:url(${merakiFont}) format("woff2");font-weight:300 900;font-style:normal;font-display:swap}`,
    accent: "#FF6746",
    accentHover: "#E8583A",
    accentActive: "#CC4C31",
    accentSubtle: "#FFE4DD",
    gradient: ["#FF6746", "#3CC5FF", "#D782FF"],
  },
};

export const portalUnit = (unit: string | undefined): TPortalUnit => (unit === "meraki" ? "meraki" : "zil");

type Props = {
  unit: TPortalUnit;
  children: ReactNode;
};

/**
 * The unit's brand over Ops' own components: its font, and its color in the accent tokens the
 * components already use (bg-accent-primary, text-accent-primary, border-accent-*, links). No new
 * classes: the same buttons, tabs and markers, in the unit's color. Set on the document root while
 * the portal is mounted, so what renders in a portal of its own (the post detail dialog) wears it too.
 */
export function PortalBrandTheme({ unit, children }: Props) {
  const brand = PORTAL_UNITS[unit];
  useEffect(() => {
    const root = document.documentElement;
    const vars: Record<string, string> = {
      "--bg-accent-primary": brand.accent,
      "--bg-accent-primary-hover": brand.accentHover,
      "--bg-accent-primary-active": brand.accentActive,
      "--bg-accent-subtle": brand.accentSubtle,
      "--bg-accent-subtle-hover": brand.accentSubtle,
      "--bg-accent-subtle-active": brand.accentSubtle,
      "--txt-accent-primary": brand.accent,
      "--txt-icon-accent-primary": brand.accent,
      "--border-accent-strong": brand.accent,
      "--border-accent-subtle": brand.accentSubtle,
      "--txt-link-primary": brand.accent,
      "--txt-link-primary-hover": brand.accentHover,
    };
    for (const [name, value] of Object.entries(vars)) root.style.setProperty(name, value);
    const previousFont = document.body.style.fontFamily;
    document.body.style.fontFamily = brand.font;
    return () => {
      for (const name of Object.keys(vars)) root.style.removeProperty(name);
      document.body.style.fontFamily = previousFont;
    };
  }, [brand]);
  return (
    <>
      <style>{brand.fontFaces}</style>
      {children}
    </>
  );
}
