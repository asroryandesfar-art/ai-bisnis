import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}

const SEVERITY_KIND: Record<string, BadgeKind> = { critical: "danger", high: "danger", medium: "warning", low: "neutral" };
const REC_STATUS_KIND: Record<string, BadgeKind> = { new: "warning", reviewed: "success", applied: "success", dismissed: "neutral" };

export default function ImprovementCenter() {
  const router = useRouter();
  const [data, setData] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const res = await api.improvementDashboard(30);
      setData(res || {});
    } catch (e: any) {
      setError(e?.message || "Gagal memuat Improvement Center.");
    } finally {
      setLoading(false);
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
      await api.improvementScan(30);
      await load();
      Alert.alert("Selesai", "Scan self-evaluation selesai dijalankan.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menjalankan scan.");
    } finally {
      setBusy(null);
    }
  }

  async function updateRec(id: string, status: string) {
    setBusy(id);
    try {
      await api.updateImprovementRecommendation(id, status);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memperbarui rekomendasi.");
    } finally {
      setBusy(null);
    }
  }

  const summary = data.summary || {};

  function RecList({ rows }: { rows?: any[] }) {
    const items = rows || [];
    if (!items.length) return <Card><Text style={styles.emptyText}>Belum ada — jalankan scan untuk mendeteksi.</Text></Card>;
    return (
      <>
        {items.map((rec) => (
          <Card key={rec.id} style={{ gap: spacing.xs }}>
            <View style={styles.rowBetween}>
              <Badge label={(rec.severity || "").toUpperCase()} kind={SEVERITY_KIND[rec.severity] || "neutral"} />
              <Badge label={(rec.status || "").toUpperCase()} kind={REC_STATUS_KIND[rec.status] || "neutral"} />
            </View>
            <Text style={styles.itemTitle}>{rec.title}</Text>
            <Text style={styles.hint}>{rec.description}</Text>
            <Text style={styles.hint}>{(rec.category || "").replace(/_/g, " ")} · {num(rec.occurrence_count)}x terdeteksi</Text>
            {busy === rec.id ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
              <View style={styles.actionRow}>
                {rec.status === "new" ? <ActionBtn label="Reviewed" onPress={() => updateRec(rec.id, "reviewed")} /> : null}
                {rec.status !== "applied" ? <ActionBtn label="Applied" primary onPress={() => updateRec(rec.id, "applied")} /> : null}
                {rec.status !== "dismissed" ? <ActionBtn label="Dismiss" danger onPress={() => updateRec(rec.id, "dismissed")} /> : null}
              </View>
            )}
          </Card>
        ))}
      </>
    );
  }

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>AI Improvement Center</Text>
        <Pressable style={styles.iconBtn} onPress={runScan} disabled={busy === "scan"}>
          {busy === "scan" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
            <Ionicons name="refresh" size={20} color={colors.brand.violet400} />
          )}
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        {loading ? <ActivityIndicator color={colors.brand.violet400} /> : (
          <>
            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Failed Answers</Text><Text style={[styles.kpiValue, (summary.failed_answers || 0) > 0 && { color: colors.status.danger }]}>{num(summary.failed_answers)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Low Confidence</Text><Text style={styles.kpiValue}>{num(summary.low_confidence)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Negative Feedback</Text><Text style={styles.kpiValue}>{num(summary.negative_feedback)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Handoffs</Text><Text style={styles.kpiValue}>{num(summary.handoffs)}</Text></View>
            </View>

            <Text style={styles.sectionLabel}>TOP ISSUES ({(data.top_issues || []).length})</Text>
            {(data.top_issues || []).length === 0 ? (
              <Card><Text style={styles.emptyText}>Tidak ada issue terdeteksi. Jalankan scan (ikon refresh di atas) untuk menganalisis percakapan terbaru.</Text></Card>
            ) : (
              (data.top_issues || []).map((issue: any, i: number) => (
                <Card key={i} style={styles.issueRow}>
                  <Badge label={(issue.type || "").replace(/_/g, " ").toUpperCase()} kind="neutral" />
                  <Text style={[styles.itemTitle, { flex: 1 }]} numberOfLines={2}>{issue.title}</Text>
                  <Text style={styles.countText}>{num(issue.count)}</Text>
                </Card>
              ))
            )}

            <Text style={styles.sectionLabel}>AGENT WEAKNESSES ({(data.agent_weaknesses || []).length})</Text>
            {(data.agent_weaknesses || []).length === 0 ? (
              <Card><Text style={styles.emptyText}>Belum ada data rollup per agent.</Text></Card>
            ) : (
              (data.agent_weaknesses || []).map((row: any, i: number) => (
                <Card key={i} style={{ gap: 2 }}>
                  <Text style={styles.itemTitle}>{row.bot_name}</Text>
                  <Text style={styles.hint}>
                    {num(row.conversations)} percakapan · quality {row.avg_quality_score ?? "—"} · confidence {row.avg_confidence ?? "—"} · {num(row.failed_verifications)} verif gagal · {num(row.bad_outcomes)} bad outcome
                  </Text>
                </Card>
              ))
            )}

            <Text style={styles.sectionLabel}>KNOWLEDGE GAPS</Text>
            <RecList rows={data.knowledge_gaps} />

            <Text style={styles.sectionLabel}>SUGGESTED IMPROVEMENTS</Text>
            <RecList rows={data.suggested_improvements} />
          </>
        )}
      </ScrollView>
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

  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  itemTitle: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  hint: { color: colors.text.faint, fontSize: 10, lineHeight: 15 },
  emptyText: { color: colors.text.muted, fontSize: 13, textAlign: "center" },
  issueRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  countText: { color: colors.brand.violet400, fontSize: 14, fontWeight: "800" },

  actionRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap", marginTop: spacing.xs },
  actionBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt },
  actionBtnPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  actionBtnDanger: { backgroundColor: colors.status.dangerBg, borderColor: colors.status.danger },
  actionBtnText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },
});
