import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView,
  StyleSheet, Switch, Text, TextInput, View,
} from "react-native";
import { GradientButton } from "../src/components/GradientButton";
import { api, APIError } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

type Status = "active" | "training" | "inactive";
type Lang = "id" | "en";
type Reasoning = "standard" | "pro";

const STATUS_OPTS: { key: Status; label: string }[] = [
  { key: "active", label: "Aktif" },
  { key: "training", label: "Training" },
  { key: "inactive", label: "Jeda" },
];
const LANG_OPTS: { key: Lang; label: string }[] = [
  { key: "id", label: "Indonesia" },
  { key: "en", label: "English" },
];
const REASONING_OPTS: { key: Reasoning; label: string }[] = [
  { key: "standard", label: "Standard" },
  { key: "pro", label: "Pro" },
];
// Preset swatches — RN has no native color picker; matches the brand palette.
const COLORS = ["#2F257E", "#482C77", "#343073", "#356E59", "#7D6526", "#7C2733", "#28627B", "#782B53"];

export default function AgentEditor() {
  const router = useRouter();
  const params = useLocalSearchParams<{ id?: string }>();
  const id = params.id;
  const isEdit = !!id;

  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [status, setStatus] = useState<Status>("active");
  const [greeting, setGreeting] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [language, setLanguage] = useState<Lang>("id");
  const [reasoning, setReasoning] = useState<Reasoning>("standard");
  const [computerAgent, setComputerAgent] = useState(false);
  const [color, setColor] = useState(COLORS[0]);

  useEffect(() => {
    if (!isEdit) return;
    (async () => {
      try {
        const bots: any[] = await api.bots();
        const bot = bots.find((b) => String(b.id) === String(id));
        if (!bot) {
          setError("Agen tidak ditemukan.");
          return;
        }
        setName(bot.name || "");
        setStatus((bot.status as Status) || "active");
        setGreeting(bot.greeting || "");
        setSystemPrompt(bot.system_prompt || "");
        setLanguage((bot.language as Lang) || "id");
        setReasoning(bot.reasoning_mode === "pro" ? "pro" : "standard");
        setComputerAgent(!!bot.computer_agent_enabled);
        setColor(bot.primary_color || COLORS[0]);
      } catch (e: any) {
        setError(e?.message || "Gagal memuat agen.");
      } finally {
        setLoading(false);
      }
    })();
  }, [id, isEdit]);

  async function save() {
    if (!name.trim()) {
      setError("Nama agen wajib diisi.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      if (isEdit) {
        await api.updateBot(id!, {
          name: name.trim(),
          status,
          greeting,
          system_prompt: systemPrompt || null,
          language,
          primary_color: color,
          reasoning_mode: reasoning,
          computer_agent_enabled: computerAgent,
        });
      } else {
        await api.createBot({
          name: name.trim(),
          language,
          greeting: greeting || "Halo! Ada yang bisa saya bantu?",
          system_prompt: systemPrompt || null,
          primary_color: color,
          status,
        });
      }
      router.back();
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Gagal menyimpan agen.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <View style={[styles.flex, styles.center]}>
        <ActivityIndicator color={colors.brand.violet400} />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={styles.topBar}>
        <Pressable style={styles.backBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>{isEdit ? "Edit Agen" : "Agen Baru"}</Text>
        <View style={{ width: 36 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <Field label="Nama Agen">
          <TextInput style={styles.input} value={name} onChangeText={setName} placeholder="mis. CS Toko Saya" placeholderTextColor={colors.text.muted} />
        </Field>

        <Field label="Status">
          <Segmented options={STATUS_OPTS} value={status} onChange={setStatus} />
        </Field>

        <Field label="Salam Pembuka">
          <TextInput
            style={[styles.input, styles.multiline]}
            value={greeting}
            onChangeText={setGreeting}
            placeholder="Halo! Ada yang bisa saya bantu?"
            placeholderTextColor={colors.text.muted}
            multiline
          />
        </Field>

        <Field label="System Prompt">
          <TextInput
            style={[styles.input, styles.multilineTall]}
            value={systemPrompt}
            onChangeText={setSystemPrompt}
            placeholder="Definisikan peran, nada bicara, batasan, dan konteks bisnis…"
            placeholderTextColor={colors.text.muted}
            multiline
          />
        </Field>

        <Field label="Bahasa">
          <Segmented options={LANG_OPTS} value={language} onChange={setLanguage} />
        </Field>

        <Field label="Mode Reasoning">
          <Segmented options={REASONING_OPTS} value={reasoning} onChange={setReasoning} />
          <Text style={styles.hint}>Pro: reasoning multi-agent lebih dalam untuk pertanyaan kompleks (lebih lambat).</Text>
        </Field>

        <View style={styles.switchRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.switchTitle}>Computer Agent</Text>
            <Text style={styles.hint}>Izinkan bot browsing web, screenshot, & isi form atas permintaan user.</Text>
          </View>
          <Switch
            value={computerAgent}
            onValueChange={setComputerAgent}
            trackColor={{ false: colors.bg.border, true: colors.brand.violet600 }}
            thumbColor="#fff"
          />
        </View>

        <Field label="Warna">
          <View style={styles.colorRow}>
            {COLORS.map((c) => (
              <Pressable key={c} onPress={() => setColor(c)} style={[styles.swatch, { backgroundColor: c }, color === c && styles.swatchActive]}>
                {color === c ? <Ionicons name="checkmark" size={16} color="#fff" /> : null}
              </Pressable>
            ))}
          </View>
        </Field>

        <View style={{ marginTop: spacing.lg }}>
          <GradientButton title={isEdit ? "Simpan Perubahan" : "Buat Agen"} onPress={save} loading={saving} />
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label.toUpperCase()}</Text>
      {children}
    </View>
  );
}

function Segmented<T extends string>({
  options, value, onChange,
}: {
  options: { key: T; label: string }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <View style={styles.segment}>
      {options.map((o) => (
        <Pressable key={o.key} onPress={() => onChange(o.key)} style={[styles.segmentItem, value === o.key && styles.segmentItemActive]}>
          <Text style={[styles.segmentLabel, value === o.key && styles.segmentLabelActive]}>{o.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  center: { alignItems: "center", justifyContent: "center" },
  topBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingTop: spacing.xl, paddingBottom: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.bg.border,
  },
  backBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  topTitle: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  container: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxl },
  error: { color: colors.status.danger, fontSize: 13 },
  field: { gap: spacing.sm },
  label: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  input: {
    backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.md,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md + 2, color: colors.text.primary, fontSize: 14,
  },
  multiline: { minHeight: 76, textAlignVertical: "top" },
  multilineTall: { minHeight: 120, textAlignVertical: "top" },
  hint: { color: colors.text.muted, fontSize: 11, lineHeight: 15 },
  segment: { flexDirection: "row", backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: 4, gap: 4 },
  segmentItem: { flex: 1, paddingVertical: spacing.md, borderRadius: radius.sm, alignItems: "center" },
  segmentItemActive: { backgroundColor: colors.brand.violet600 },
  segmentLabel: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  segmentLabelActive: { color: "#fff" },
  switchRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  switchTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  colorRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  swatch: { width: 40, height: 40, borderRadius: radius.md, alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: "transparent" },
  swatchActive: { borderColor: "#fff" },
});
