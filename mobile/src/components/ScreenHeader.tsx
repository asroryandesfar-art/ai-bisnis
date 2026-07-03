import type { ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";
import { colors } from "../theme/colors";
import { spacing } from "../theme/spacing";

// Shared fixed (non-scrolling) header used by every tab except Beranda,
// which keeps its own distinct brand header (logo + bell) per the
// Figma-parity decision. Title/subtitle typography matches what
// Agen/Tugas/Billing already used independently -- this just makes the
// wrapper (and the "stays fixed while content scrolls" behavior) consistent
// across all of them.
export function ScreenHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <View style={styles.header}>
      <View style={{ flex: 1 }}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {action}
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.lg, paddingTop: spacing.xl,
  },
  title: { color: colors.text.primary, fontSize: 22, fontWeight: "800" },
  subtitle: { color: colors.text.muted, fontSize: 12, marginTop: 2 },
});
