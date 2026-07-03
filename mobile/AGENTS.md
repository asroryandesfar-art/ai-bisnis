# Expo SDK 54

This project targets **Expo SDK 54** (started on 57 → downgraded to 56 → then 54 on
2026-07-03 for Expo Go compatibility — the user's Android Expo Go can't update past the
version that supports SDK 54, so 56/57 were rejected as "incompatible").

- Read the exact versioned docs at https://docs.expo.dev/versions/v54.0.0/ before writing any code.
- SDK 54 uses the OLD per-package versioning (expo-router ~6.x, expo-constants ~18.x, etc.),
  NOT the SDK-aligned numbers that started in SDK 55. react 19.1.0, react-native 0.81.5.
- `.npmrc` sets `legacy-peer-deps=true` (kept from the 56 attempt; harmless on 54).
- Keep all `expo-*` packages on the SDK-54 canonical versions; run `npx expo install --fix`
  after adding any, and `npx expo-doctor` should stay at 0 issues.
