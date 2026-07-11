// Premium enterprise design system (2026-07-11 retheme): pure black,
// one subtle brand accent, no gradients. Key shape kept identical to the
// prior theme so the ~50 files consuming these tokens don't need edits —
// only values changed.
export const colors = {
  bg: {
    app: "#000000",
    base: "#0A0A0A",
    card: "#111111",
    cardAlt: "#0D0D0D",
    border: "#1E1E1E",
    borderAlt: "#2A2A2A",
  },
  text: {
    primary: "#FFFFFF",
    body: "#B3B3B3",
    muted: "#808080",
    faint: "#4D4D4D",
  },
  brand: {
    // Single accent hue (deep, muted blue) at different tints/shades for
    // interactive states — not a second color. Never combine into a gradient.
    violet400: "#6E93BA",
    violet500: "#3D6791",
    violet600: "#2C4C6C",
    indigo500: "#2C4C6C",
    indigo600: "#21394F",
  },
  status: {
    successBg: "rgba(16,185,129,0.10)",
    successBgStrong: "rgba(16,185,129,0.15)",
    success: "#34D399",
    warningBg: "rgba(245,158,11,0.10)",
    warningBgStrong: "rgba(245,158,11,0.15)",
    warning: "#FBBF24",
    dangerBg: "rgba(244,63,94,0.10)",
    danger: "#FB7185",
  },
} as const;
