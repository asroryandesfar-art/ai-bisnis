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

const HEALTH_KIND: Record<string, BadgeKind> = { healthy: "success", warning: "warning", critical: "danger" };
const DOMAIN_DEFS = [
  { key: "finance", label: "Finance" }, { key: "marketing", label: "Marketing" }, { key: "hr", label: "HR" },
  { key: "operations", label: "Operations" }, { key: "security", label: "Security" }, { key: "sales", label: "Sales" },
];
const ANALYSIS_HEALTH_KIND: Record<string, BadgeKind> = { Excellent: "success", Good: "success", Warning: "warning", Critical: "danger" };

export default function ExecutiveCenter() {
  const router = useRouter();
  const [dash, setDash] = useState<any>({});
  const [trends, setTrends] = useState<any>({});
  const [reports, setReports] = useState<any[]>([]);
  const [brief, setBrief] = useState<any>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [dashRes, reportsRes, trendsRes] = await Promise.allSettled([
        api.executiveDashboard(), api.executiveReports(10), api.executiveTrends(30),
      ]);
      setDash(dashRes.status === "fulfilled" ? dashRes.value : {});
      setTrends(trendsRes.status === "fulfilled" ? trendsRes.value || {} : {});
      const reportList = reportsRes.status === "fulfilled" ? reportsRes.value.reports || [] : [];
      setReports(reportList);
      if (dashRes.status === "rejected") setError((dashRes as any).reason?.message || "Gagal memuat Executive Center.");
      // Same as web: fetch the latest report's full body to show its brief inline.
      if (reportList.length) {
        try {
          const full = await api.executiveReport(reportList[0].id);
          setBrief({ report_type: full.report_type, ...(full.data?.brief || {}) });
        } catch {
          setBrief(null);
        }
      } else {
        setBrief(null);
      }
    } catch (e: any) {
      setError(e?.message || "Gagal memuat Executive Center.");
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

  async function generateBrief(type: "weekly" | "monthly") {
    setBusy(`brief-${type}`);
    try {
      await api.generateExecutiveReport(type);
      await load();
      Alert.alert("Berhasil", `Executive brief ${type === "weekly" ? "mingguan" : "bulanan"} dibuat.`);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa membuat brief.");
    } finally {
      setBusy(null);
    }
  }

  async function runAnalysis() {
    setBusy("analyze");
    try {
      const result = await api.analyzeBusiness();
      setAnalysis(result);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menganalisis bisnis.");
    } finally {
      setBusy(null);
    }
  }

  const health = dash.health || {};
  const byDomain = health.by_domain || {};
  const analysisBody = analysis?.analysis || {};
  const recs = analysisBody.recommendations || {};
  const plan = analysisBody.action_plan || {};

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Executive Center</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
          <ActionChip label="Analyze My Business" busy={busy === "analyze"} onPress={runAnalysis} primary />
          <ActionChip label="Weekly Brief" busy={busy === "brief-weekly"} onPress={() => generateBrief("weekly")} />
          <ActionChip label="Monthly Brief" busy={busy === "brief-monthly"} onPress={() => generateBrief("monthly")} />
        </ScrollView>

        {loading ? <ActivityIndicator color={colors.brand.violet400} /> : (
          <>
            <Card style={{ gap: spacing.md }}>
              <View style={styles.rowBetween}>
                <Text style={styles.cardTitle}>Company Health Score</Text>
                <Badge label={(health.label || "watch").toUpperCase()} kind={HEALTH_KIND[health.label] || "neutral"} />
              </View>
              <View style={styles.scoreRow}>
                <Text style={styles.scoreBig}>{health.overall ?? "—"}</Text>
                <Text style={styles.scoreOutOf}>/ 100</Text>
              </View>
              <View style={{ gap: spacing.sm }}>
                {DOMAIN_DEFS.map(({ key, label }) => {
                  const score = byDomain[key] ?? null;
                  const pct = score !== null ? Math.min(100, Number(score)) : 0;
                  return (
                    <View key={key} style={styles.domainRow}>
                      <Text style={styles.domainLabel}>{label}</Text>
                      <View style={styles.progressTrack}>
                        <View style={[styles.progressFill, { width: `${pct}%` }]} />
                      </View>
                      <Text style={styles.domainScore}>{score ?? "—"}</Text>
                    </View>
                  );
                })}
              </View>
            </Card>

            {analysis ? (
              <Card style={{ gap: spacing.sm }}>
                <View style={styles.rowBetween}>
                  <Text style={styles.cardTitle}>AI Business Analyst</Text>
                  <Badge label={analysis.business_health_label || "—"} kind={ANALYSIS_HEALTH_KIND[analysis.business_health_label] || "neutral"} />
                </View>
                {analysis.deltas?.has_historical_data === false ? (
                  <Text style={styles.hint}>Belum ada riwayat report sebelumnya — analisis berdasarkan kondisi saat ini saja. Generate brief dulu agar root-cause bisa membandingkan tren.</Text>
                ) : null}
                {analysisBody.executive_summary ? <Text style={styles.bodyText}>{analysisBody.executive_summary}</Text> : null}
                {(analysisBody.root_cause_analysis || []).map((item: any, i: number) => (
                  <View key={i} style={styles.insightBox}>
                    <Text style={styles.insightTitle}>{item.question}</Text>
                    <Text style={styles.hint}>{item.explanation}</Text>
                  </View>
                ))}
                <ListBlock title="Prioritas Tinggi" items={recs.high} />
                <ListBlock title="Prioritas Sedang" items={recs.medium} />
                <ListBlock title="Prioritas Rendah" items={recs.low} />
                <ListBlock title="Action Plan — 7 Hari" items={plan["7_days"]} />
                <ListBlock title="Action Plan — 30 Hari" items={plan["30_days"]} />
                <ListBlock title="Action Plan — 90 Hari" items={plan["90_days"]} />
              </Card>
            ) : null}

            {brief ? (
              <Card style={{ gap: spacing.sm }}>
                <View style={styles.rowBetween}>
                  <Text style={styles.cardTitle}>Executive Brief Terbaru</Text>
                  <Badge label={(brief.report_type || "").toUpperCase()} kind="neutral" />
                </View>
                {brief.executive_summary ? <Text style={styles.bodyText}>{brief.executive_summary}</Text> : null}
                <ListBlock title="Growth Recommendations" items={brief.growth_recommendations} />
                <ListBlock title="Cost Optimization" items={brief.cost_optimization} />
                <ListBlock title="Revenue Opportunities" items={brief.revenue_opportunities} />
                <ListBlock title="Strategic Insights" items={brief.strategic_insights} />
              </Card>
            ) : null}

            <Text style={styles.sectionLabel}>EXECUTIVE ANALYTICS (30 HARI)</Text>
            <TrendCard title="Revenue Trend" rows={trends.revenue_trend} />
            <TrendCard title="Customer Growth" rows={trends.customer_growth} />
            <TrendCard title="Sales Growth" rows={trends.sales_growth} />
            <TrendCard title="Customer Satisfaction" rows={trends.customer_satisfaction} />

            <Text style={styles.sectionLabel}>RIWAYAT EXECUTIVE BRIEF ({reports.length})</Text>
            {reports.length === 0 ? (
              <Card><Text style={styles.emptyText}>Belum ada executive brief. Generate brief weekly/monthly pertama Anda.</Text></Card>
            ) : (
              reports.map((r) => (
                <Card key={r.id} style={{ gap: spacing.xs }}>
                  <View style={styles.rowBetween}>
                    <Badge label={r.report_type} kind="neutral" />
                    <Text style={styles.hint}>{formatDate(r.created_at)}</Text>
                  </View>
                  <Text style={styles.hint} numberOfLines={3}>{r.summary}</Text>
                </Card>
              ))
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function TrendCard({ title, rows }: { title: string; rows?: any[] }) {
  const data = rows || [];
  // Same field-fallback order as web's drawChart(): value may live in
  // .convs, .value, or .cost depending on which trend endpoint produced it.
  const values = data.map((r) => Number(r.convs ?? r.value ?? r.cost ?? 0));
  const max = Math.max(1, ...values);
  return (
    <Card style={{ gap: spacing.sm }}>
      <Text style={styles.cardTitle}>{title}</Text>
      {data.length === 0 ? (
        <Text style={styles.hint}>Belum ada data — normal untuk bisnis baru, bukan kesalahan sistem.</Text>
      ) : (
        <View style={styles.chartRow}>
          {data.map((r, i) => (
            <View key={i} style={styles.barCol}>
              <View style={styles.barTrack}>
                <View style={[styles.barFill, { height: `${Math.max(4, (values[i] / max) * 100)}%` }]} />
              </View>
            </View>
          ))}
        </View>
      )}
    </Card>
  );
}

function ListBlock({ title, items }: { title: string; items?: string[] }) {
  if (!items || !items.length) return null;
  return (
    <View style={{ gap: 4 }}>
      <Text style={styles.blockTitle}>{title.toUpperCase()}</Text>
      {items.map((item, i) => (
        <Text key={i} style={styles.bulletText}>• {item}</Text>
      ))}
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

  chip: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  chipPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  chipText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },

  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  cardTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  scoreRow: { flexDirection: "row", alignItems: "baseline", gap: spacing.xs },
  scoreBig: { color: colors.brand.violet400, fontSize: 42, fontWeight: "800" },
  scoreOutOf: { color: colors.text.faint, fontSize: 14 },

  domainRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  domainLabel: { width: 80, color: colors.text.muted, fontSize: 11, fontWeight: "600" },
  progressTrack: { flex: 1, height: 6, borderRadius: 3, backgroundColor: colors.bg.cardAlt, overflow: "hidden" },
  progressFill: { height: "100%", borderRadius: 3, backgroundColor: colors.brand.violet500 },
  domainScore: { width: 32, textAlign: "right", color: colors.text.primary, fontSize: 12, fontWeight: "700" },

  bodyText: { color: colors.text.body, fontSize: 13, lineHeight: 19 },
  hint: { color: colors.text.faint, fontSize: 11, lineHeight: 16 },
  blockTitle: { color: colors.text.muted, fontSize: 10, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.xs },
  bulletText: { color: colors.text.body, fontSize: 12, lineHeight: 18 },
  insightBox: { backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, padding: spacing.md, gap: 2 },
  insightTitle: { color: colors.status.warning, fontSize: 12, fontWeight: "700" },
  emptyText: { color: colors.text.muted, fontSize: 13, textAlign: "center" },

  chartRow: { flexDirection: "row", alignItems: "flex-end", gap: 2, height: 90 },
  barCol: { flex: 1, height: "100%", justifyContent: "flex-end" },
  barTrack: { flex: 1, justifyContent: "flex-end" },
  barFill: { borderRadius: 2, backgroundColor: colors.brand.violet500 },
});
