// Reference design uses "Plus Jakarta Sans" for headings. We don't bundle a
// custom font in Phase 1 (adds an expo-font asset-loading step) -- system
// font is visually close enough for now; swap in expo-font + Plus Jakarta
// Sans in a later increment if the founder wants exact typeface parity.
export const typography = {
  h1: { fontSize: 34, fontWeight: "800" as const, letterSpacing: -0.5 },
  h2: { fontSize: 24, fontWeight: "700" as const },
  h3: { fontSize: 18, fontWeight: "700" as const },
  body: { fontSize: 14, fontWeight: "400" as const },
  bodyMedium: { fontSize: 14, fontWeight: "600" as const },
  small: { fontSize: 12, fontWeight: "500" as const },
  tiny: { fontSize: 11, fontWeight: "500" as const },
};
