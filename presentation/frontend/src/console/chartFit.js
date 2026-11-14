/** Device-pixel backing store for a chart that fills its CSS box. */
export function backingSize(cssWidth, cssHeight, devicePixelRatio) {
  const dpr =
    Number.isFinite(devicePixelRatio) && devicePixelRatio > 0
      ? devicePixelRatio
      : 1;
  const cssW = Math.max(0, Number(cssWidth) || 0);
  const cssH = Math.max(0, Number(cssHeight) || 0);
  const width = Math.round(cssW * dpr);
  const height = Math.round(cssH * dpr);
  return {
    dpr,
    cssWidth: cssW,
    cssHeight: cssH,
    width,
    height,
    scaleX: cssW > 0 ? width / cssW : dpr,
    scaleY: cssH > 0 ? height / cssH : dpr,
  };
}

/** Nearest sample for a pointer inside the plot, clamped to the series. */
export function pointerIndex(offsetX, plotWidth, count) {
  const n = Math.max(0, count | 0);
  if (n <= 1 || !(plotWidth > 0)) return 0;
  const i = Math.round((offsetX / plotWidth) * (n - 1));
  return Math.max(0, Math.min(n - 1, i));
}

/** Collapse a burst of resize notifications into one trailing call. */
export function debounce(fn, wait) {
  let timer = 0;
  return function debounced(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), wait);
  };
}
