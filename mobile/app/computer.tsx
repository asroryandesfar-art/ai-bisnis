import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View,
} from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

type Task = { id: string; goal?: string; status: string; created_at: string };

const QUICK = ["Buat laporan", "Cek email", "Input data", "Buka website"];

const STATUS_KIND: Record<string, BadgeKind> = {
  completed: "success", success: "success", done: "success",
  pending: "warning", running: "warning", in_progress: "warning", pending_approval: "warning",
  failed: "danger", error: "danger", rejected: "danger",
};

function timeAgo(iso: string) {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "baru saja";
  if (mins < 60) return `${mins} menit lalu`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h} jam lalu`;
  return `${Math.floor(h / 24)} hari lalu`;
}

export default function Computer() {
  const router = useRouter();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [goal, setGoal] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const res = await api.computerAgentTasksAll();
      setTasks((res.tasks || []) as Task[]);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat log Computer Agent.");
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  async function run() {
    const g = goal.trim();
    if (!g || running) return;
    setRunning(true);
    try {
      const res = await api.computerAgentRunLocal(g);
      setGoal("");
      await load();
      Alert.alert("Perintah dikirim", res?.message || res?.status || "Computer Agent memproses perintah Anda.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menjalankan perintah (agen lokal mungkin belum terhubung).");
    } finally {
      setRunning(false);
    }
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Computer Agent</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.subtitle}>Kontrol komputer dengan perintah AI</Text>

        {/* Session preview */}
        <Card style={styles.sessionCard}>
          <View style={styles.preview}>
            <MaterialCommunityIcons name="monitor" size={40} color={colors.text.faint} />
            <Text style={styles.previewText}>Kirim perintah untuk memulai sesi</Text>
          </View>
        </Card>

        {/* Command */}
        <Text style={styles.sectionLabel}>BERIKAN PERINTAH</Text>
        <View style={styles.cmdRow}>
          <TextInput
            style={styles.cmdInput}
            value={goal}
            onChangeText={setGoal}
            placeholder="Contoh: Buka Excel dan buat laporan…"
            placeholderTextColor={colors.text.muted}
            multiline
          />
          <Pressable style={[styles.runBtn, (!goal.trim() || running) && styles.runBtnDisabled]} onPress={run} disabled={!goal.trim() || running}>
            {running ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="play" size={18} color="#fff" />}
          </Pressable>
        </View>
        <View style={styles.chipRow}>
          {QUICK.map((q) => (
            <Pressable key={q} style={styles.chip} onPress={() => setGoal(q)}>
              <Text style={styles.chipText}>{q}</Text>
            </Pressable>
          ))}
        </View>

        {/* Log */}
        <Text style={styles.sectionLabel}>LOG TINDAKAN</Text>
        {error ? (
          <Card style={{ borderColor: colors.status.danger }}>
            <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
          </Card>
        ) : null}
        {!error && tasks.length === 0 ? (
          <Card>
            <Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada tindakan.</Text>
          </Card>
        ) : (
          <Card style={{ padding: 0 }}>
            {tasks.map((task, i) => (
              <View key={task.id} style={[styles.logRow, i > 0 && styles.logRowBorder]}>
                <MaterialCommunityIcons
                  name={STATUS_KIND[task.status] === "success" ? "check-circle-outline" : STATUS_KIND[task.status] === "danger" ? "close-circle-outline" : "progress-clock"}
                  size={18}
                  color={STATUS_KIND[task.status] === "success" ? colors.status.success : STATUS_KIND[task.status] === "danger" ? colors.status.danger : colors.status.warning}
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.logGoal} numberOfLines={2}>{task.goal || "Tindakan"}</Text>
                  <Text style={styles.logTime}>{timeAgo(task.created_at)}</Text>
                </View>
                <Badge label={(task.status || "").toUpperCase()} kind={STATUS_KIND[task.status] || "neutral"} />
              </View>
            ))}
          </Card>
        )}
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
  iconBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  topTitle: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  container: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  subtitle: { color: colors.text.muted, fontSize: 12 },
  sessionCard: { padding: spacing.lg },
  preview: {
    height: 150, borderRadius: radius.md, backgroundColor: colors.bg.cardAlt, borderWidth: 1,
    borderColor: colors.bg.border, borderStyle: "dashed", alignItems: "center", justifyContent: "center", gap: spacing.sm,
  },
  previewText: { color: colors.text.muted, fontSize: 12 },
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },
  cmdRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-end" },
  cmdInput: {
    flex: 1, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.md,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md, color: colors.text.primary, fontSize: 14, minHeight: 48, maxHeight: 120,
  },
  runBtn: { width: 48, height: 48, borderRadius: radius.md, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  runBtnDisabled: { opacity: 0.5 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, borderWidth: 1, borderColor: colors.brand.violet500, backgroundColor: "rgba(139,92,246,0.12)" },
  chipText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "600" },
  logRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md },
  logRowBorder: { borderTopWidth: 1, borderTopColor: colors.bg.border },
  logGoal: { color: colors.text.primary, fontSize: 13, fontWeight: "600" },
  logTime: { color: colors.text.faint, fontSize: 11, marginTop: 2 },
});
