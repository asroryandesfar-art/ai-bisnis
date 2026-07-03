import { MaterialCommunityIcons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";
import { colors } from "../theme/colors";
import { spacing } from "../theme/spacing";

type IconName = keyof typeof MaterialCommunityIcons.glyphMap;

export function ComingSoon({ title, icon }: { title: string; icon: IconName }) {
  return (
    <View style={styles.wrap}>
      <View style={styles.iconCircle}>
        <MaterialCommunityIcons name={icon} size={32} color={colors.brand.violet400} />
      </View>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.sub}>Halaman ini sedang dibangun di increment berikutnya.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, paddingHorizontal: spacing.xl, backgroundColor: colors.bg.base },
  iconCircle: {
    width: 72, height: 72, borderRadius: 36, backgroundColor: "rgba(139,92,246,0.10)",
    alignItems: "center", justifyContent: "center", marginBottom: spacing.sm,
  },
  title: { color: colors.text.primary, fontSize: 18, fontWeight: "700" },
  sub: { color: colors.text.muted, fontSize: 13, textAlign: "center" },
});
