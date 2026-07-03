import { StyleSheet, View, ViewProps } from "react-native";
import { colors } from "../theme/colors";
import { radius, spacing } from "../theme/spacing";

export function Card({ style, ...props }: ViewProps) {
  return <View style={[styles.card, style]} {...props} />;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.bg.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.bg.border,
    padding: spacing.lg,
  },
});
