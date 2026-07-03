import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View,
} from "react-native";
import { GradientButton } from "../src/components/GradientButton";
import { api, APIError } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

type Domain = "finance" | "marketing" | "hr" | "operations" | "security" | "executive";
type Priority = "low" | "medium" | "high" | "critical";

const DOMAINS: { key: Domain; label: string; icon: keyof typeof MaterialCommunityIcons.glyphMap }[] = [
  { key: "finance", label: "Finance", icon: "cash-multiple" },
  { key: "marketing", label: "Marketing", icon: "bullhorn-outline" },
  { key: "hr", label: "HR", icon: "account-group-outline" },
  { key: "operations", label: "Operations", icon: "cog-outline" },
  { key: "security", label: "Security", icon: "shield-outline" },
  { key: "executive", label: "Executive", icon: "briefcase-outline" },
];
const PRIORITIES: { key: Priority; label: string }[] = [
  { key: "low", label: "Rendah" },
  { key: "medium", label: "Sedang" },
  { key: "high", label: "Tinggi" },
  { key: "critical", label: "Kritis" },
];

export default function TaskCreate() {
  const router = useRouter();
  const [domain, setDomain] = useState<Domain>("finance");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<Priority>("medium");
  const [requiresApproval, setRequiresApproval] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!title.trim()) {
      setError("Judul task wajib diisi.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      await api.createWorkforceTask({
        domain,
        title: title.trim(),
        description: description.trim() || null,
        priority,
        requires_approval: requiresApproval,
      });
      router.back();
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Gagal membuat task.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={styles.topBar}>
        <Pressable style={styles.backBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Buat Task</Text>
        <View style={{ width: 36 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <Text style={styles.label}>DOMAIN</Text>
        <View style={styles.domainGrid}>
          {DOMAINS.map((d) => (
            <Pressable
              key={d.key}
              onPress={() => setDomain(d.key)}
              style={[styles.domainPill, domain === d.key && styles.domainPillActive]}
            >
              <MaterialCommunityIcons name={d.icon} size={15} color={domain === d.key ? "#fff" : colors.brand.violet400} />
              <Text style={[styles.domainLabel, domain === d.key && styles.domainLabelActive]}>{d.label}</Text>
            </Pressable>
          ))}
        </View>

        <Text style={styles.label}>JUDUL TASK</Text>
        <TextInput style={styles.input} value={title} onChangeText={setTitle} placeholder="mis. Follow-up invoice overdue" placeholderTextColor={colors.text.muted} />

        <Text style={styles.label}>DESKRIPSI (OPSIONAL)</Text>
        <TextInput
          style={[styles.input, styles.multiline]}
          value={description}
          onChangeText={setDescription}
          placeholder="Detail task…"
          placeholderTextColor={colors.text.muted}
          multiline
        />

        <Text style={styles.label}>PRIORITAS</Text>
        <View style={styles.segment}>
          {PRIORITIES.map((p) => (
            <Pressable key={p.key} onPress={() => setPriority(p.key)} style={[styles.segmentItem, priority === p.key && styles.segmentItemActive]}>
              <Text style={[styles.segmentLabel, priority === p.key && styles.segmentLabelActive]}>{p.label}</Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.switchRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.switchTitle}>Butuh Approval</Text>
            <Text style={styles.hint}>Task harus disetujui manusia sebelum dieksekusi.</Text>
          </View>
          <Switch
            value={requiresApproval}
            onValueChange={setRequiresApproval}
            trackColor={{ false: colors.bg.border, true: colors.brand.violet600 }}
            thumbColor="#fff"
          />
        </View>

        <View style={{ marginTop: spacing.lg }}>
          <GradientButton title="Buat Task" onPress={save} loading={saving} />
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  topBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingTop: spacing.xl, paddingBottom: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.bg.border,
  },
  backBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  topTitle: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  container: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  error: { color: colors.status.danger, fontSize: 13 },
  label: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },
  input: {
    backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.md,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md + 2, color: colors.text.primary, fontSize: 14,
  },
  multiline: { minHeight: 90, textAlignVertical: "top" },
  hint: { color: colors.text.muted, fontSize: 11, lineHeight: 15 },
  domainGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  domainPill: {
    flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2,
    borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border,
  },
  domainPillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  domainLabel: { color: colors.text.body, fontSize: 12, fontWeight: "700" },
  domainLabelActive: { color: "#fff" },
  segment: { flexDirection: "row", backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: 4, gap: 4 },
  segmentItem: { flex: 1, paddingVertical: spacing.md, borderRadius: radius.sm, alignItems: "center" },
  segmentItemActive: { backgroundColor: colors.brand.violet600 },
  segmentLabel: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  segmentLabelActive: { color: "#fff" },
  switchRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.sm },
  switchTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
});
