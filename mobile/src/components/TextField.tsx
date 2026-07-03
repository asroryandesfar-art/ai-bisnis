import { useState } from "react";
import { StyleSheet, Text, TextInput, TextInputProps, View } from "react-native";
import { colors } from "../theme/colors";
import { radius, spacing } from "../theme/spacing";

export function TextField({ label, ...props }: TextInputProps & { label: string }) {
  const [focused, setFocused] = useState(false);
  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>{label.toUpperCase()}</Text>
      <TextInput
        {...props}
        onFocus={(e) => {
          setFocused(true);
          props.onFocus?.(e);
        }}
        onBlur={(e) => {
          setFocused(false);
          props.onBlur?.(e);
        }}
        placeholderTextColor={colors.text.muted}
        style={[styles.input, focused && styles.inputFocused]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
  label: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  input: {
    backgroundColor: colors.bg.card,
    borderWidth: 1,
    borderColor: colors.bg.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md + 2,
    color: colors.text.primary,
    fontSize: 14,
  },
  inputFocused: { borderColor: colors.brand.indigo500 },
});
