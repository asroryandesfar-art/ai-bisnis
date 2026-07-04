import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}

function timeAgo(iso: string | null) {
  if (!iso) return "—";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "baru saja";
  if (mins < 60) return `${mins} menit lalu`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h} jam lalu`;
  return `${Math.floor(h / 24)} hari lalu`;
}

// Business-domain agents runnable directly from mobile. Computer/local
// agents are deliberately excluded here -- mobile already has a dedicated
// Computer Agent screen (app/computer.tsx) for those.
const RUN_AGENTS = [
  { key: "finance", label: "Finance Agent" },
  { key: "marketing", label: "Marketing Agent" },
  { key: "hr", label: "HR Agent" },
  { key: "operations", label: "Operations Agent" },
] as const;

const LOG_STATUS_KIND: Record<string, BadgeKind> = {
  success: "success", completed: "success", failed: "danger", rejected: "danger",
  pending: "warning", pending_approval: "warning", running: "warning",
};

export default function AgentCenter() {
  const router = useRouter();
  const [overview, setOverview] = useState<any>({});
  const [agents, setAgents] = useState<any[]>([]);
  const [logEntries, setLogEntries] = useState<any[]>([]);
  const [localAgent, setLocalAgent] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [runAgent, setRunAgent] = useState<(typeof RUN_AGENTS)[number]["key"]>("finance");
  const [goal, setGoal] = useState("");
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<any>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [ovRes, agentsRes, logRes, laRes] = await Promise.allSettled([
      api.agentCenterOverview(), api.agentCenterAgents(), api.executionLogList(20), api.localAgentStatus(),
    ]);
    setOverview(ovRes.status === "fulfilled" ? ovRes.value : {});
    setAgents(agentsRes.status === "fulfilled" ? agentsRes.value.agents || [] : []);
    setLogEntries(logRes.status === "fulfilled" ? logRes.value.entries || [] : []);
    setLocalAgent(laRes.status === "fulfilled" ? laRes.value : {});
    setLoading(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function runTask() {
    if (!goal.trim()) {
      Alert.alert("Lengkapi form", "Tulis pertanyaan atau tugas untuk agent.");
      return;
    }
    setRunning(true);
    setRunError(null);
    setRunResult(null);
    try {
      const fn = { finance: api.financeRunTask, marketing: api.marketingRunTask, hr: api.hrRunTask, operations: api.opsRunTask }[runAgent];
      const result = await fn(goal.trim());
      setRunResult(result);
      await load();
    } catch (e: any) {
      setRunError(e?.message || "Tidak bisa menjalankan tugas.");
    } finally {
      setRunning(false);
    }
  }

  const bySourceType = overview.execution_log?.by_source_type || {};
  const totalLogEntries = Object.values(bySourceType).reduce((s: number, v: any) => s + Number(v || 0), 0);
  const approvalPending =
    (overview.workforce?.pending_approval_count || 0) + (overview.computer_agent_pending_approval_count || 0);

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Agent Center</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {loading ? <ActivityIndicator color={colors.brand.violet400} /> : (
          <>
            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Total Agent</Text><Text style={styles.kpiValue}>{num(agents.length)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Execution Log</Text><Text style={styles.kpiValue}>{num(totalLogEntries)}</Text></View>
              <Pressable style={styles.kpiCard} onPress={() => router.push("/antrian")}>
                <Text style={styles.kpiLabel}>Approval Queue</Text>
                <Text style={[styles.kpiValue, approvalPending > 0 && { color: colors.status.warning }]}>{num(approvalPending)}</Text>
                <Text style={styles.kpiSub}>Tap untuk buka Antrian Izin</Text>
              </Pressable>
              <Pressable style={styles.kpiCard} onPress={() => router.push("/computer")}>
                <Text style={styles.kpiLabel}>Local Agent</Text>
                <Text style={[styles.kpiValue, { color: localAgent.connected ? colors.status.success : colors.text.muted }]}>
                  {localAgent.connected ? "● Online" : "○ Offline"}
                </Text>
                <Text style={styles.kpiSub}>{localAgent.connected ? localAgent.meta?.hostname || "" : "Kelola di Computer Agent"}</Text>
              </Pressable>
            </View>

            <Text style={styles.sectionLabel}>TANYA / BERI TUGAS KE AI AGENT</Text>
            <Card style={{ gap: spacing.sm }}>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
                {RUN_AGENTS.map((a) => (
                  <Pressable key={a.key} onPress={() => setRunAgent(a.key)} style={[styles.pill, runAgent === a.key && styles.pillActive]}>
                    <Text style={[styles.pillText, runAgent === a.key && styles.pillTextActive]}>{a.label}</Text>
                  </Pressable>
                ))}
              </ScrollView>
              <TextInput
                style={[styles.input, { minHeight: 70, textAlignVertical: "top" }]}
                value={goal}
                onChangeText={setGoal}
                placeholder="Contoh: Cek invoice yang belum lunas"
                placeholderTextColor={colors.text.muted}
                multiline
              />
              {running ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                <Pressable style={styles.primaryBtn} onPress={runTask}>
                  <Text style={styles.primaryBtnText}>Jalankan Tugas</Text>
                </Pressable>
              )}
              {runError ? <Text style={{ color: colors.status.danger, fontSize: 12 }}>{runError}</Text> : null}
              {runResult ? (
                <View style={styles.resultBox}>
                  <View style={styles.rowBetween}>
                    <Badge label={(runResult.status || "completed").toUpperCase()} kind={runResult.status === "completed" ? "success" : "warning"} />
                    <Text style={styles.hint}>{runResult.agent_name || ""}</Text>
                  </View>
                  <Text style={styles.resultText}>{runResult.report || "(tidak ada report)"}</Text>
                  {runResult.verification?.reasoning ? (
                    <Text style={styles.hint}>Verifikasi: {runResult.verification.reasoning}</Text>
                  ) : null}
                </View>
              ) : null}
            </Card>

            <Text style={styles.sectionLabel}>AGENT DIRECTORY ({agents.length})</Text>
            {agents.length === 0 ? (
              <Card><Text style={styles.emptyText}>Agent directory kosong.</Text></Card>
            ) : (
              agents.map((a, i) => (
                <Card key={`${a.name}-${i}`} style={styles.agentCard}>
                  <View style={styles.agentIcon}>
                    <MaterialCommunityIcons name="robot-outline" size={16} color={colors.brand.violet400} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.agentName} numberOfLines={1}>{a.name}</Text>
                    <Text style={styles.hint}>{a.category} · {(a.skills || []).length} skills · {(a.tools || []).length} tools</Text>
                  </View>
                  <Badge
                    label={a.channel === "chat_pipeline" ? "CHAT PIPELINE" : "API"}
                    kind={a.channel === "chat_pipeline" ? "success" : "neutral"}
                  />
                </Card>
              ))
            )}

            <Text style={styles.sectionLabel}>EXECUTION LOG TERBARU ({logEntries.length})</Text>
            {logEntries.length === 0 ? (
              <Card><Text style={styles.emptyText}>Belum ada entri execution log.</Text></Card>
            ) : (
              logEntries.map((e) => (
                <Card key={e.id} style={{ gap: spacing.xs }}>
                  <View style={styles.rowBetween}>
                    <Badge label={(e.source_type || "").toUpperCase()} kind="neutral" />
                    <Badge label={(e.status || "").toUpperCase()} kind={LOG_STATUS_KIND[e.status] || "neutral"} />
                  </View>
                  <Text style={styles.agentName} numberOfLines={2}>{e.label || "—"}</Text>
                  <Text style={styles.hint}>{timeAgo(e.started_at)}</Text>
                </Card>
              ))
            )}
          </>
        )}
      </ScrollView>
    </View>
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
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },

  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpiCard: { width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 2 },
  kpiLabel: { color: colors.text.faint, fontSize: 10 },
  kpiValue: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  kpiSub: { color: colors.text.muted, fontSize: 9 },

  pill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border },
  pillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  pillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  pillTextActive: { color: "#fff" },

  input: {
    backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, color: colors.text.primary, fontSize: 13,
  },
  primaryBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },

  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  resultBox: { backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: spacing.sm },
  resultText: { color: colors.text.body, fontSize: 12, lineHeight: 18 },
  hint: { color: colors.text.faint, fontSize: 10 },

  agentCard: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  agentIcon: { width: 30, height: 30, borderRadius: radius.sm, backgroundColor: "rgba(139,92,246,0.12)", alignItems: "center", justifyContent: "center" },
  agentName: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  emptyText: { color: colors.text.muted, fontSize: 13, textAlign: "center" },
});
