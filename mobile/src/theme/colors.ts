// Design tokens extracted directly from the reference Figma prototype
// (train-ethics-17051690.figma.site) — exact hex values pulled from its
// rendered DOM, not eyeballed from screenshots.
export const colors = {
  bg: {
    app: "#070B14",
    base: "#0D1017",
    card: "#0E1420",
    cardAlt: "#0A0F1C",
    border: "#1A2030",
    borderAlt: "#1A2235",
  },
  text: {
    primary: "#FFFFFF",
    body: "#A8B4CC",
    muted: "#5A6A88",
    faint: "#3A4A62",
  },
  brand: {
    violet400: "#A78BFA",
    violet500: "#8B5CF6",
    violet600: "#7C3AED",
    indigo500: "#6366F1",
    indigo600: "#4F46E5",
    gradient: ["#7C3AED", "#4F46E5"] as const,
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
