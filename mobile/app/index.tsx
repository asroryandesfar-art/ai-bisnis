import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Image, StyleSheet, Text, View } from "react-native";
import { GradientButton } from "../src/components/GradientButton";
import { tokenStore } from "../src/auth/tokenStore";
import { colors } from "../src/theme/colors";
import { spacing } from "../src/theme/spacing";

export default function Splash() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    // Returning user with a stored token skips straight to the app --
    // Splash still flashes briefly as the branded loading screen.
    (async () => {
      const token = await tokenStore.get();
      if (token) {
        router.replace("/beranda");
        return;
      }
      setChecking(false);
    })();
  }, []);

  return (
    <View style={styles.container}>
      <View style={styles.center}>
        <View style={styles.logoWrap}>
          <Image source={require("../assets/brand-logo.png")} style={styles.logoBox} />
          <View style={styles.onlineDot}>
            <View style={styles.onlineDotInner} />
          </View>
        </View>

        <Text style={styles.title}>BotNesia</Text>
        <Text style={styles.subtitle}>AI Business Platform</Text>
        <Text style={styles.tagline}>Otomatiskan bisnis Anda dengan kekuatan AI yang cerdas</Text>

        <View style={styles.dots}>
          <View style={styles.dot} />
          <View style={styles.dot} />
          <View style={styles.dot} />
        </View>
      </View>

      <View style={styles.bottom}>
        {checking ? (
          <ActivityIndicator color={colors.brand.violet400} />
        ) : (
          <GradientButton title="Mulai Sekarang  →" onPress={() => router.push("/login")} />
        )}
        <Text style={styles.version}>v1.0.0 · Powered by BotNesia AI</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg.app, alignItems: "center", justifyContent: "center" },
  center: { alignItems: "center", gap: spacing.lg, paddingHorizontal: spacing.xl },
  logoWrap: { position: "relative" },
  logoBox: {
    width: 96, height: 96, borderRadius: 24, resizeMode: "cover",
    shadowColor: "#000000", shadowOpacity: 0.4, shadowRadius: 12, shadowOffset: { width: 0, height: 4 },
  },
  onlineDot: {
    position: "absolute", top: -4, right: -4, width: 20, height: 20, borderRadius: 10,
    backgroundColor: colors.status.success, borderWidth: 2, borderColor: colors.bg.app,
    alignItems: "center", justifyContent: "center",
  },
  onlineDotInner: { width: 8, height: 8, borderRadius: 4, backgroundColor: "#6EE7B7" },
  title: { color: colors.text.primary, fontSize: 34, fontWeight: "800", letterSpacing: -0.5, marginTop: spacing.sm },
  subtitle: { color: colors.text.muted, fontSize: 13, fontWeight: "600", letterSpacing: 0.5, marginTop: -spacing.md },
  tagline: { color: colors.text.body, fontSize: 14, textAlign: "center", lineHeight: 20, marginTop: spacing.sm },
  dots: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brand.violet500 },
  bottom: { position: "absolute", bottom: 56, width: "100%", paddingHorizontal: spacing.xl, alignItems: "center", gap: spacing.lg },
  version: { color: colors.text.faint, fontSize: 12 },
});
