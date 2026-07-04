import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { formatDate } from "../src/utils/format";

function timeAgo(iso: string | null) {
  if (!iso) return "—";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "baru saja";
  if (mins < 60) return `${mins} menit lalu`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h} jam lalu`;
  return `${Math.floor(h / 24)} hari lalu`;
}

const SEVERITY_KIND: Record<string, BadgeKind> = { critical: "danger", high: "danger", medium: "warning", low: "neutral" };
const HEALTH_KIND: Record<string, BadgeKind> = { healthy: "success", warning: "warning", critical: "danger" };

export default function OperationsCenter() {
  const router = useRouter();
  const [dash, setDash] = useState<any>({});
  const [alerts, setAlerts] = useState<any[]>([]);
  const [reports, setReports] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [dashRes, alertsRes, reportsRes] = await Promise.allSettled([
        api.opsDashboard(), api.opsAlerts({ status: "open", limit: 50 }), api.opsReports(10),
      ]);
      setDash(dashRes.status === "fulfilled" ? dashRes.value : {});
      setAlerts(alertsRes.status === "fulfilled" ? alertsRes.value.alerts || [] : []);
      setReports(reportsRes.status === "fulfilled" ? reportsRes.value.reports || [] : []);
      if (dashRes.status === "rejected") setError((dashRes as any).reason?.message || "Gagal memuat Operations Center.");
    } catch (e: any) {
      setError(e?.message || "Gagal memuat Operations Center.");
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function runScan() {
    setBusy("scan");
    try {
      await api.opsScan();
      await load();
      Alert.alert("Selesai", "Operations scan selesai dijalankan.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menjalankan scan.");
    } finally {
      setBusy(null);
    }
  }

  async function generateReport(type: "weekly" | "monthly") {
    setBusy(`report-${type}`);
    try {
      await api.opsGenerateReport(type);
      await load();
      Alert.alert("Berhasil", `Laporan ${type === "weekly" ? "mingguan" : "bulanan"} dibuat.`);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa membuat laporan.");
    } finally {
      setBusy(null);
    }
  }

  async function updateAlert(id: string, status: string) {
    setBusy(id);
    try {
      await api.opsUpdateAlert(id, status);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memperbarui alert.");
    } finally {
      setBusy(null);
    }
  }

  const health = dash.health || {};

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Operations Center</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.actionRowScroll}>
          <ActionChip label="Run Scan" busy={busy === "scan"} onPress={runScan} primary />
          <ActionChip label="Laporan Mingguan" busy={busy === "report-weekly"} onPress={() => generateReport("weekly")} />
          <ActionChip label="Laporan Bulanan" busy={busy === "report-monthly"} onPress={() => generateReport("monthly")} />
        </ScrollView>

        <View style={styles.kpiGrid}>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Health Score</Text>
            <Text style={styles.kpiValue}>{health.score ?? "—"}</Text>
            <Badge label={(health.label || "watch").toUpperCase()} kind={HEALTH_KIND[health.label] || "neutral"} />
          </View>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Workflow Success</Text>
            <Text style={styles.kpiValue}>{dash.workflow_health?.success_rate_pct ?? "—"}%</Text>
            <Text style={styles.kpiSub}>{dash.workflow_health?.total_executions ?? 0} eksekusi</Text>
          </View>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>SLA Breach Rate</Text>
            <Text style={styles.kpiValue}>{dash.sla_health?.breach_rate_pct ?? "—"}%</Text>
            <Text style={styles.kpiSub}>{dash.sla_health?.total_handoffs ?? 0} handoff</Text>
          </View>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Open Alerts</Text>
            <Text style={styles.kpiValue}>{alerts.length}</Text>
            <Text style={styles.kpiSub}>{dash.open_alerts_by_severity?.critical ?? 0} critical</Text>
          </View>
        </View>

        <Text style={styles.sectionLabel}>ALERTS ({alerts.length})</Text>
        {alerts.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Tidak ada alert terbuka.</Text></Card>
        ) : (
          alerts.map((a) => (
            <Card key={a.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Badge label={a.severity.toUpperCase()} kind={SEVERITY_KIND[a.severity] || "neutral"} />
                <Text style={styles.itemMeta}>{timeAgo(a.created_at)}</Text>
              </View>
              <Text style={styles.itemTitle}>{(a.category || "").replace(/_/g, " ")}</Text>
              <Text style={styles.itemMeta}>{a.message}</Text>
              {busy === a.id ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                <View style={styles.actionRow}>
                  <ActionBtn label="Acknowledge" onPress={() => updateAlert(a.id, "acknowledged")} />
                  <ActionBtn label="Resolve" primary onPress={() => updateAlert(a.id, "resolved")} />
                </View>
              )}
            </Card>
          ))
        )}

        <Text style={styles.sectionLabel}>LAPORAN OPERASIONAL ({reports.length})</Text>
        {reports.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada laporan.</Text></Card>
        ) : (
          reports.map((r) => (
            <Card key={r.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Badge label={r.report_type} kind="neutral" />
                <Text style={styles.itemMeta}>{formatDate(r.created_at)}</Text>
              </View>
              <Text style={styles.itemMeta} numberOfLines={3}>{r.summary}</Text>
            </Card>
          ))
        )}
      </ScrollView>
    </View>
  );
}

function ActionChip({ label, onPress, busy, primary }: { label: string; onPress: () => void; busy?: boolean; primary?: boolean }) {
  return (
    <Pressable style={[styles.chip, primary && styles.chipPrimary, busy && { opacity: 0.6 }]} onPress={onPress} disabled={busy}>
      {busy ? <ActivityIndicator size="small" color={primary ? "#fff" : colors.brand.violet400} /> : (
        <Text style={[styles.chipText, primary && { color: "#fff" }]}>{label}</Text>
      )}
    </Pressable>
  );
}

function ActionBtn({ label, onPress, primary }: { label: string; onPress: () => void; primary?: boolean }) {
  return (
    <Pressable onPress={onPress} style={[styles.actionBtn, primary && styles.actionBtnPrimary]}>
      <Text style={[styles.actionBtnText, primary && { color: "#fff" }]}>{label}</Text>
    </Pressable>
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

  actionRowScroll: { gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  chipPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  chipText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },

  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpiCard: { width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 4 },
  kpiLabel: { color: colors.text.faint, fontSize: 10 },
  kpiValue: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  kpiSub: { color: colors.text.muted, fontSize: 10 },

  itemCard: { gap: spacing.xs },
  itemHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  itemTitle: { color: colors.text.primary, fontSize: 13, fontWeight: "700", textTransform: "capitalize" },
  itemMeta: { color: colors.text.faint, fontSize: 11 },
  actionRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  actionBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt },
  actionBtnPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  actionBtnText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },
});
