import { memo } from 'react';

/**
 * 4-layer Backdrop — Hermes-inspired visual depth.
 *
 * Layer stack (all pointer-events-none, all fixed inset-0):
 *   z-1   bg-primary           — deep canvas, sets the base tone
 *   z-2   inverted SVG noise   — subtle texture (0.04 opacity)
 *   z-99  radial vignette      — accent glow from top-left corner
 *   z-101 fine grain           — color-dodge noise (0.04 opacity)
 *
 * Mounted once at the App root so all views (chat / research / ppt / ...)
 * benefit from the same atmosphere. Color tokens cascade from :root via
 * CSS variables so dark/light theme parity is automatic.
 */
export const Backdrop = memo(function Backdrop() {
  return (
    <>
      <div aria-hidden className="backdrop-layer backdrop-layer--base" />
      <div aria-hidden className="backdrop-layer backdrop-layer--filler" />
      <div aria-hidden className="backdrop-layer backdrop-layer--vignette" />
      <div aria-hidden className="backdrop-layer backdrop-layer--grain" />
    </>
  );
});
