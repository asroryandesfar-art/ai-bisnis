import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge, BadgeKind } from "../../src/components/Badge";
import { Card } from "../../src/components/Card";
import { ScreenHeader } from "../../src/components/ScreenHeader";
import { api } from "../../src/api/client";
import { colors } from "../../src/theme/colors";
import { radius, spacing } from "../../src/theme/spacing";

type Task = {
  id: string;
  domain: "finance" | "marketing" | "hr" | "operations" | "security" | "executive";
  title: string;
  description: string | null;
  priority: "low" | "medium" | "high" | "critical";
  status: "pending" | "in_progress" | "blocked" | "completed" | "cancelled" | "escalated";
  requires_approval: boolean;
  approved_at: string | null;
  has_conflict?: boolean;
  conflict_note?: string | null;
  due_at: string | null;
  created_at: string;
};

type Workflow = { id: string; name: string; status: string; trigger_type: string | null; bot_id: string | null };

const FILTERS = [
  { key: "all", label: "Semua" },
  { key: "pending", label: "Pending" },
  { key: "in_progress", label: "Berjalan" },
  { key: "completed", label: "Selesai" },
] as const;

const DOMAIN_LABEL: Record<Task["domain"], string> = {
  finance: "Finance", marketing: "Marketing", hr: "HR",
  operations: "Operations", security: "Security", executive: "Executive",
};
const DOMAIN_ICON: Record<Task["domain"], keyof typeof MaterialCommunityIcons.glyphMap> = {
  finance: "cash-multiple", marketing: "bullhorn-outline", hr: "account-group-outline",
  operations: "cog-outline", security: "shield-outline", executive: "briefcase-outline",
};
const STATUS_BADGE: Record<Task["status"], { label: string; kind: BadgeKind }> = {
  pending: { label: "PENDING", kind: "neutral" },
  in_progress: { label: "BERJALAN", kind: "warning" },
  blocked: { label: "TERBLOKIR", kind: "danger" },
  completed: { label: "SELESAI", kind: "success" },
  cancelled: { label: "DIBATALKAN", kind: "neutral" },
  escalated: { label: "ESKALASI", kind: "danger" },
};
const PRIORITY_COLOR: Record<Task["priority"], string> = {
  low: colors.text.faint, medium: colors.brand.violet400, high: colors.status.warning, critical: colors.status.danger,
};

const WF_STATUS: Record<string, { label: string; kind: BadgeKind }> = {
  published: { label: "AKTIF", kind: "success" },
  scheduled: { label: "TERJADWAL", kind: "warning" },
  ready_to_publish: { label: "SIAP", kind: "warning" },
  draft: { label: "DRAFT", kind: "neutral" },
  cancelled: { label: "NONAKTIF", kind: "neutral" },
};
const TRIGGER_LABEL: Record<string, string> = {
  message_received: "Pesan masuk", new_lead: "Lead baru", new_customer: "Customer baru",
  new_ticket: "Tiket baru", manual_trigger: "Manual",
};

export default function Tugas() {
  const router = useRouter();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [botNames, setBotNames] = useState<Record<string, string>>({});
  const [dash, setDash] = useState<any>({});
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [wfBusyId, setWfBusyId] = useState<string | null>(null);
  const [newWfPickerOpen, setNewWfPickerOpen] = useState(false);
  const [scanning, setScanning] = useState(false);

  const load = useCallback(async (status?: string) => {
    try {
      setError(null);
      const [tasksRes, dashRes, botsRes] = await Promise.allSettled([
        api.workforceTasks(status && status !== "all" ? { status } : {}),
        api.workforceDashboard(),
        api.bots(),
      ]);
      setTasks(tasksRes.status === "fulfilled" ? tasksRes.value.tasks || [] : []);
      setDash(dashRes.status === "fulfilled" ? dashRes.value : {});

      // Aggregate workflows across bots (route also returns global bot_id IS
      // NULL rows, so dedupe by id).
      const bots: any[] = botsRes.status === "fulfilled" ? (botsRes.value as any[]) : [];
      const nameMap: Record<string, string> = {};
      bots.forEach((b) => { nameMap[b.id] = b.name; });
      setBotNames(nameMap);
      const wfResults = await Promise.allSettled(bots.slice(0, 8).map((b) => api.wfList(b.id)));
      const map = new Map<string, Workflow>();
      wfResults.forEach((r) => {
        if (r.status !== "fulfilled") return;
        const list: any[] = r.value?.workflows || r.value || [];
        list.forEach((w) => map.set(w.id, w));
      });
      setWorkflows(Array.from(map.values()));
    } catch (e: any) {
      setError(e?.message || "Gagal memuat tugas.");
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load(filter);
    }, [filter, load])
  );

  async function onRefresh() {
    setRefreshing(true);
    await load(filter);
    setRefreshing(false);
  }

  async function changeStatus(id: string, status: string) {
    setBusyId(id);
    try {
      await api.updateWorkforceTaskStatus(id, status);
      await load(filter);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa mengubah status task.");
    } finally {
      setBusyId(null);
    }
  }

  async function approve(id: string) {
    setBusyId(id);
    try {
      await api.approveWorkforceTask(id);
      await load(filter);
    } catch (e: any) {
      Alert.alert("Gagal approve", e?.message || "Perlu izin workforce.approve.");
    } finally {
      setBusyId(null);
    }
  }

  async function scanConflicts() {
    setScanning(true);
    try {
      const res: any = await api.scanWorkforceConflicts();
      await load(filter);
      Alert.alert("Scan selesai", `${res?.conflicts_count ?? 0} konflik terdeteksi.`);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa scan konflik.");
    } finally {
      setScanning(false);
    }
  }

  async function runWorkflow(w: Workflow) {
    setWfBusyId(w.id);
    try {
      const res: any = await api.wfTest(w.id);
      const steps = res?.steps?.length ?? res?.execution?.steps?.length;
      Alert.alert("Otomatisasi dijalankan", `"${w.name}" selesai dieksekusi${steps != null ? ` (${steps} langkah)` : ""}.`);
    } catch (e: any) {
      Alert.alert("Gagal menjalankan", e?.message || "Workflow tidak bisa dijalankan (mungkin belum published).");
    } finally {
      setWfBusyId(null);
    }
  }

  const runningCount = useMemo(() => tasks.filter((t) => t.status === "in_progress").length, [tasks]);
  const activeWf = workflows.filter((w) => w.status === "published").length;
  const draftWf = workflows.length - activeWf;

  return (
    <View style={styles.flex}>
      <ScreenHeader
        title="Otomatisasi Tugas"
        subtitle={`${activeWf} otomatisasi aktif · ${runningCount} task berjalan`}
        action={
          <>
            <Pressable style={styles.scanBtn} onPress={scanConflicts} disabled={scanning}>
              {scanning ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : <MaterialCommunityIcons name="radar" size={18} color={colors.brand.violet400} />}
            </Pressable>
            <Pressable style={styles.addButton} onPress={() => router.push("/task-create")}>
              <Ionicons name="add" size={22} color="#fff" />
            </Pressable>
          </>
        }
      />

      <ScrollView
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
      >
        {error ? (
          <Card style={{ borderColor: colors.status.danger }}>
            <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
          </Card>
        ) : null}

        {/* ── OTOMATISASI (workflows) ── */}
        <View style={styles.wfStatRow}>
          <View style={styles.wfStatCard}>
            <Text style={[styles.wfStatValue, { color: colors.status.success }]}>{activeWf}</Text>
            <Text style={styles.wfStatLabel}>Aktif</Text>
          </View>
          <View style={styles.wfStatCard}>
            <Text style={[styles.wfStatValue, { color: colors.text.muted }]}>{draftWf}</Text>
            <Text style={styles.wfStatLabel}>Draft/nonaktif</Text>
          </View>
        </View>
        <View style={styles.wfSectionHead}>
          <Text style={styles.sectionLabel}>OTOMATISASI</Text>
          <Pressable
            onPress={() => {
              const botIds = Object.keys(botNames);
              if (botIds.length === 1) router.push({ pathname: "/workflow-editor", params: { botId: botIds[0] } });
              else setNewWfPickerOpen((v) => !v);
            }}
          >
            <Text style={styles.wfAddText}>+ Baru</Text>
          </Pressable>
        </View>
        {newWfPickerOpen ? (
          <Card style={{ gap: spacing.sm }}>
            <Text style={styles.wfAgent}>Pilih agen untuk otomatisasi baru:</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
              {Object.entries(botNames).map(([id, botName]) => (
                <Pressable
                  key={id}
                  style={styles.filterPill}
                  onPress={() => { setNewWfPickerOpen(false); router.push({ pathname: "/workflow-editor", params: { botId: id } }); }}
                >
                  <Text style={styles.filterLabel}>{botName}</Text>
                </Pressable>
              ))}
            </View>
          </Card>
        ) : null}
        {workflows.length === 0 ? (
          <Card>
            <Text style={{ color: colors.text.muted, fontSize: 12, textAlign: "center" }}>
              Belum ada otomatisasi. Tap "+ Baru" di atas untuk membuat.
            </Text>
          </Card>
        ) : (
          workflows.map((w) => {
            const st = WF_STATUS[w.status] || { label: (w.status || "").toUpperCase(), kind: "neutral" as BadgeKind };
            const wfBusy = wfBusyId === w.id;
            const agentName = (w.bot_id && botNames[w.bot_id]) || "Semua agen";
            return (
              <Card key={w.id} style={styles.wfCard}>
                <View style={styles.wfHead}>
                  <View style={styles.wfIcon}>
                    <MaterialCommunityIcons name="cog-sync-outline" size={16} color={colors.brand.violet400} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.wfName} numberOfLines={1}>{w.name}</Text>
                    <Text style={styles.wfAgent} numberOfLines={1}>{agentName}</Text>
                  </View>
                  <Badge label={st.label} kind={st.kind} />
                  <Pressable onPress={() => router.push({ pathname: "/workflow-editor", params: { id: w.id, botId: w.bot_id || "" } })} hitSlop={6}>
                    <MaterialCommunityIcons name="pencil-outline" size={16} color={colors.text.faint} />
                  </Pressable>
                </View>
                <Text style={styles.wfTrigger}>
                  Pemicu: {w.trigger_type ? TRIGGER_LABEL[w.trigger_type] || w.trigger_type : "belum diatur"}
                </Text>
                <Pressable
                  style={[styles.runWfBtnFull, (wfBusy || w.status !== "published") && styles.runWfBtnDisabled]}
                  onPress={() => runWorkflow(w)}
                  disabled={wfBusy || w.status !== "published"}
                >
                  {wfBusy ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : (
                    <>
                      <Ionicons name="play" size={14} color="#fff" />
                      <Text style={styles.runWfText}>Jalankan Tugas</Text>
                    </>
                  )}
                </Pressable>
              </Card>
            );
          })
        )}

        {/* ── WORKFORCE TASKS ── */}
        <View style={styles.metricRow}>
          <Metric label="Pending" value={dash?.by_status?.pending ?? 0} tint={colors.text.body} />
          <Metric label="Berjalan" value={dash?.by_status?.in_progress ?? 0} tint={colors.status.warning} />
          <Metric label="Approval" value={dash?.pending_approval_count ?? 0} tint={colors.brand.violet400} />
          <Metric label="Konflik" value={dash?.conflicts_count ?? 0} tint={colors.status.danger} />
        </View>

        <View style={styles.filterRow}>
          {FILTERS.map((f) => (
            <Pressable key={f.key} onPress={() => setFilter(f.key)} style={[styles.filterPill, filter === f.key && styles.filterPillActive]}>
              <Text style={[styles.filterLabel, filter === f.key && styles.filterLabelActive]}>{f.label}</Text>
            </Pressable>
          ))}
        </View>

        {!error && tasks.length === 0 ? (
          <Card>
            <Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Tidak ada task.</Text>
          </Card>
        ) : null}

        {tasks.map((task) => {
          const sb = STATUS_BADGE[task.status];
          const busy = busyId === task.id;
          const closed = task.status === "completed" || task.status === "cancelled";
          const needsApproval = task.requires_approval && !task.approved_at;
          return (
            <Card key={task.id} style={styles.taskCard}>
              <View style={styles.taskHeaderRow}>
                <View style={[styles.priorityDot, { backgroundColor: PRIORITY_COLOR[task.priority] }]} />
                <View style={styles.domainIcon}>
                  <MaterialCommunityIcons name={DOMAIN_ICON[task.domain]} size={14} color={colors.brand.violet400} />
                </View>
                <Text style={styles.domainLabel}>{DOMAIN_LABEL[task.domain]}</Text>
                <View style={{ flex: 1 }} />
                <Badge label={sb.label} kind={sb.kind} />
              </View>
              <Text style={styles.taskTitle}>{task.title}</Text>
              {task.description ? <Text style={styles.taskDesc} numberOfLines={2}>{task.description}</Text> : null}
              {task.has_conflict ? (
                <View style={styles.conflictRow}>
                  <MaterialCommunityIcons name="alert-outline" size={13} color={colors.status.danger} />
                  <Text style={styles.conflictText} numberOfLines={2}>Konflik: {task.conflict_note || "perlu review manusia"}</Text>
                </View>
              ) : null}
              <View style={styles.taskFooterRow}>
                {task.requires_approval ? (
                  <View style={styles.approvalTag}>
                    <MaterialCommunityIcons name={task.approved_at ? "shield-check" : "shield-alert-outline"} size={12} color={task.approved_at ? colors.status.success : colors.status.warning} />
                    <Text style={[styles.approvalTagText, { color: task.approved_at ? colors.status.success : colors.status.warning }]}>
                      {task.approved_at ? "Approved" : "Butuh approval"}
                    </Text>
                  </View>
                ) : null}
                {task.due_at ? (
                  <Text style={styles.dueText}>Tempo: {new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short" }).format(new Date(task.due_at))}</Text>
                ) : null}
              </View>
              {busy ? (
                <View style={styles.actionRow}><ActivityIndicator size="small" color={colors.brand.violet400} /></View>
              ) : !closed || needsApproval ? (
                <View style={styles.actionRow}>
                  {task.status === "pending" ? <ActionBtn label="Mulai" onPress={() => changeStatus(task.id, "in_progress")} /> : null}
                  {!closed ? <ActionBtn label="Selesai" primary onPress={() => changeStatus(task.id, "completed")} /> : null}
                  {!closed ? <ActionBtn label="Batal" danger onPress={() => changeStatus(task.id, "cancelled")} /> : null}
                  {needsApproval ? <ActionBtn label="Approve" primary onPress={() => approve(task.id)} /> : null}
                </View>
              ) : null}
            </Card>
          );
        })}

        {/* ── AGENT OS ── */}
        <Text style={styles.sectionLabel}>AGENT OS</Text>
        <View style={styles.agentOsGrid}>
          <AgentOsLink icon="robot-outline" label="Agent Center" onPress={() => router.push("/agent-center")} />
          <AgentOsLink icon="routes" label="Routing Logs" onPress={() => router.push("/routing-logs")} />
          <AgentOsLink icon="eye-outline" label="Observability" onPress={() => router.push("/observability")} />
          <AgentOsLink icon="cash-multiple" label="Cost Intelligence" onPress={() => router.push("/costs")} />
        </View>
      </ScrollView>
    </View>
  );
}

function AgentOsLink({ icon, label, onPress }: { icon: keyof typeof MaterialCommunityIcons.glyphMap; label: string; onPress: () => void }) {
  return (
    <Pressable style={styles.agentOsCard} onPress={onPress}>
      <MaterialCommunityIcons name={icon} size={18} color={colors.brand.violet400} />
      <Text style={styles.agentOsLabel} numberOfLines={2}>{label}</Text>
    </Pressable>
  );
}

function Metric({ label, value, tint }: { label: string; value: number; tint: string }) {
  return (
    <View style={styles.metricCard}>
      <Text style={[styles.metricValue, { color: tint }]}>{value}</Text>
      <Text style={styles.metricLabel}>{label}</Text>
    </View>
  );
}

function ActionBtn({ label, onPress, primary, danger }: { label: string; onPress: () => void; primary?: boolean; danger?: boolean }) {
  return (
    <Pressable onPress={onPress} style={[styles.actionBtn, primary && styles.actionBtnPrimary, danger && styles.actionBtnDanger]}>
      <Text style={[styles.actionBtnText, primary && { color: "#fff" }, danger && { color: colors.status.danger }]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  scanBtn: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border, alignItems: "center", justifyContent: "center" },
  addButton: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  list: { padding: spacing.lg, paddingTop: 0, gap: spacing.md, paddingBottom: spacing.xxl },
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },
  wfSectionHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.sm },
  wfAddText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },

  agentOsGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  agentOsCard: {
    width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border,
    padding: spacing.md, gap: spacing.xs, alignItems: "flex-start",
  },
  agentOsLabel: { color: colors.text.body, fontSize: 12, fontWeight: "700" },

  wfStatRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  wfStatCard: { flex: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, paddingVertical: spacing.md, alignItems: "center" },
  wfStatValue: { fontSize: 20, fontWeight: "800" },
  wfStatLabel: { color: colors.text.muted, fontSize: 10, marginTop: 2 },

  wfCard: { gap: spacing.sm },
  wfHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  wfIcon: { width: 30, height: 30, borderRadius: radius.sm, backgroundColor: "rgba(139,92,246,0.12)", alignItems: "center", justifyContent: "center" },
  wfName: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  wfAgent: { color: colors.text.muted, fontSize: 11, marginTop: 1 },
  wfTrigger: { color: colors.text.muted, fontSize: 12 },
  runWfBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.brand.violet600, paddingVertical: spacing.sm + 2, borderRadius: radius.md, alignSelf: "flex-start", paddingHorizontal: spacing.lg },
  runWfBtnFull: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.brand.violet600, paddingVertical: spacing.sm + 4, borderRadius: radius.md },
  runWfBtnDisabled: { opacity: 0.5 },
  runWfText: { color: "#fff", fontSize: 12, fontWeight: "700" },

  metricRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  metricCard: { flex: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, paddingVertical: spacing.md, alignItems: "center" },
  metricValue: { fontSize: 20, fontWeight: "800" },
  metricLabel: { color: colors.text.muted, fontSize: 10, marginTop: 2 },
  filterRow: { flexDirection: "row", gap: spacing.sm },
  filterPill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  filterPillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  filterLabel: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  filterLabelActive: { color: "#fff" },
  taskCard: { gap: spacing.sm },
  taskHeaderRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  priorityDot: { width: 8, height: 8, borderRadius: 4 },
  domainIcon: { width: 22, height: 22, borderRadius: radius.sm, backgroundColor: "rgba(139,92,246,0.12)", alignItems: "center", justifyContent: "center" },
  domainLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700" },
  taskTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  taskDesc: { color: colors.text.body, fontSize: 12 },
  conflictRow: { flexDirection: "row", alignItems: "flex-start", gap: 6, backgroundColor: colors.status.dangerBg, borderRadius: radius.sm, padding: spacing.sm },
  conflictText: { color: colors.status.danger, fontSize: 11, flex: 1 },
  taskFooterRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.xs },
  approvalTag: { flexDirection: "row", alignItems: "center", gap: 4 },
  approvalTagText: { fontSize: 11, fontWeight: "600" },
  dueText: { color: colors.text.faint, fontSize: 11, marginLeft: "auto" },
  actionRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs, borderTopWidth: 1, borderTopColor: colors.bg.border, paddingTop: spacing.md, flexWrap: "wrap" },
  actionBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt },
  actionBtnPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  actionBtnDanger: { backgroundColor: colors.status.dangerBg, borderColor: colors.status.danger },
  actionBtnText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },
});
