import { StyleSheet, Text, View } from "react-native";
import { colors } from "../theme/colors";
import { radius, spacing } from "../theme/spacing";

export type BadgeKind = "success" | "warning" | "danger" | "neutral";

const KIND_STYLES: Record<BadgeKind, { bg: string; fg: string }> = {
  success: { bg: colors.status.successBgStrong, fg: colors.status.success },
  warning: { bg: colors.status.warningBgStrong, fg: colors.status.warning },
  danger: { bg: colors.status.dangerBg, fg: colors.status.danger },
  neutral: { bg: colors.bg.borderAlt, fg: colors.text.body },
};

export function Badge({ label, kind = "neutral" }: { label: string; kind?: BadgeKind }) {
  const s = KIND_STYLES[kind];
  return (
    <View style={[styles.badge, { backgroundColor: s.bg }]}>
      <Text style={[styles.label, { color: s.fg }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: spacing.sm + 2,
    paddingVertical: 4,
    borderRadius: radius.full,
    alignSelf: "flex-start",
  },
  label: { fontSize: 11, fontWeight: "700" },
});
