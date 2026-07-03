// The web dashboard (frontend/styles.css) uses "Manrope". Mobile
// deliberately stays on the system font (San Francisco/Roboto) -- confirmed
// with the founder (2026-07-03, mobile-web parity audit) not worth the
// app-wide re-render risk of bundling a custom font for a foundation pass;
// revisit with expo-font + Manrope only if exact typeface parity is
// explicitly requested later.
export const typography = {
  h1: { fontSize: 34, fontWeight: "800" as const, letterSpacing: -0.5 },
  h2: { fontSize: 24, fontWeight: "700" as const },
  h3: { fontSize: 18, fontWeight: "700" as const },
  body: { fontSize: 14, fontWeight: "400" as const },
  bodyMedium: { fontSize: 14, fontWeight: "600" as const },
  small: { fontSize: 12, fontWeight: "500" as const },
  tiny: { fontSize: 11, fontWeight: "500" as const },
};
