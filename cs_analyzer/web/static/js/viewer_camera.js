// Viewer camera (Phase E M4): wheel zoom-to-cursor + drag pan over the map.
// Pure math lives here so playwright can probe it via window.__viewerDebug.cam.
//
// Coordinate model: screen = viewCenter + (mapPx - camCenter) * scale * zoom
//   cam {cx, cy}  map-pixel point shown at the viewport center (0,0 = fit)
//   zoom          1 = contain-fit baseline; clamped to [minZoom, maxZoom]
(function () {
  'use strict';

  function create() {
    // cx/cy null = "fit" (map center, zoom 1); resolved on first draw
    return { cx: null, cy: null, zoom: 1 };
  }

  /** Snap back to the contain-fit view. */
  function reset(cam) {
    cam.cx = null;
    cam.cy = null;
    cam.zoom = 1;
    return cam;
  }

  /** Resolve the fit sentinel to the map center (mutates when null).
   * Degenerate dims (image not loaded yet) are ignored — a later call resolves. */
  function resolve(cam, mapW, mapH) {
    if (!mapW || !mapH) return cam;
    if (cam.cx == null) cam.cx = mapW / 2;
    if (cam.cy == null) cam.cy = mapH / 2;
    return cam;
  }

  function clamp(val, lo, hi) {
    return Math.max(lo, Math.min(hi, val));
  }

  /**
   * Zoom keeping the map point under `cursor` ({x,y} viewport CSS px) fixed.
   * factor > 1 zooms in. Mutates and returns cam. `scale` is the contain-fit
   * map->css-px factor (drawMapLayer.geom.scale); mapW/H are map-pixel dims.
   */
  function zoomAt(cam, cursor, factor, view, scale, mapW, mapH, minZoom, maxZoom) {
    const z0 = cam.zoom;
    const z1 = clamp(z0 * factor, minZoom == null ? 1 : minZoom, maxZoom == null ? 8 : maxZoom);
    if (z1 === z0) return cam;
    resolve(cam, mapW, mapH);
    // map pixel under the cursor before the change
    const mx = cam.cx + (cursor.x - view.w / 2) / (scale * z0);
    const my = cam.cy + (cursor.y - view.h / 2) / (scale * z0);
    cam.zoom = z1;
    // keep that map pixel under the cursor afterwards
    cam.cx = mx - (cursor.x - view.w / 2) / (scale * z1);
    cam.cy = my - (cursor.y - view.h / 2) / (scale * z1);
    return clampPan(cam, view, scale, mapW, mapH);
  }

  /** Drag pan by a screen-space delta; clamped to the map rect. */
  function panBy(cam, dxScreen, dyScreen, view, scale, mapW, mapH) {
    resolve(cam, mapW, mapH);
    cam.cx -= dxScreen / (scale * cam.zoom);
    cam.cy -= dyScreen / (scale * cam.zoom);
    return clampPan(cam, view, scale, mapW, mapH);
  }

  /**
   * Never show area outside the map; re-center an axis when the zoomed map is
   * smaller than the viewport on that axis.
   */
  function clampPan(cam, view, scale, mapW, mapH) {
    const halfW = view.w / (2 * scale * cam.zoom);
    const halfH = view.h / (2 * scale * cam.zoom);
    cam.cx = halfW * 2 >= mapW ? mapW / 2 : clamp(cam.cx, halfW, mapW - halfW);
    cam.cy = halfH * 2 >= mapH ? mapH / 2 : clamp(cam.cy, halfH, mapH - halfH);
    return cam;
  }

  window.ViewerCam = { create, reset, resolve, zoomAt, panBy, clampPan };
})();
