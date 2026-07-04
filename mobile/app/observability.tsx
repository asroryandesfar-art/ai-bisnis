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

function timeAgo(iso: string | null) {
  if (!iso) return "—";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "baru saja";
  if (mins < 60) return `${mins} menit lalu`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h} jam lalu`;
  return `${Math.floor(h / 24)} hari lalu`;
}

const PERIODS = [
  { value: 1, label: "24 Jam" }, { value: 7, label: "7 Hari" }, { value: 30, label: "30 Hari" }, { value: 90, label: "90 Hari" },
];

const TRACE_STATUS_KIND: Record<string, BadgeKind> = { success: "success", failed: "danger", running: "warning" };

export default function Observability() {
  const router = useRouter();
  const [days, setDays] = useState(7);
  const [data, setData] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openTraceId, setOpenTraceId] = useState<string | null>(null);
  const [traceDetail, setTraceDetail] = useState<any>(null);
  const [traceLoading, setTraceLoading] = useState(false);

  const load = useCallback(async (period: number) => {
    try {
      setError(null);
      const res = await api.observabilitySummary(period);
      setData(res || {});
    } catch (e: any) {
      setError(e?.message || "Gagal memuat AI Observability.");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(days); }, [load, days]));

  async function onRefresh() {
    setRefreshing(true);
    await load(days);
    setRefreshing(false);
  }

  async function toggleTrace(traceId: string) {
    if (openTraceId === traceId) {
      setOpenTraceId(null);
      setTraceDetail(null);
      return;
    }
    setOpenTraceId(traceId);
    setTraceDetail(null);
    setTraceLoading(true);
    try {
      const detail = await api.observabilityTrace(traceId);
      setTraceDetail(detail);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memuat detail trace.");
      setOpenTraceId(null);
    } finally {
      setTraceLoading(false);
    }
  }

  const metrics = data.metrics || {};
  const agents = data.agents || [];
  const traces = data.traces || [];

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>AI Observability</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
          {PERIODS.map((p) => (
            <Pressable key={p.value} onPress={() => setDays(p.value)} style={[styles.pill, days === p.value && styles.pillActive]}>
              <Text style={[styles.pillText, days === p.value && styles.pillTextActive]}>{p.label}</Text>
            </Pressable>
          ))}
        </ScrollView>

        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        {loading ? <ActivityIndicator color={colors.brand.violet400} /> : (
          <>
            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Active Agents</Text><Text style={styles.kpiValue}>{num(metrics.active_agents)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Failed Agents</Text><Text style={[styles.kpiValue, (metrics.failed_agents || 0) > 0 && { color: colors.status.danger }]}>{num(metrics.failed_agents)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Avg Latency</Text><Text style={styles.kpiValue}>{Math.round(metrics.average_latency_ms || 0)}ms</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Token Usage</Text><Text style={styles.kpiValue}>{num(metrics.total_tokens)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Success Rate</Text><Text style={[styles.kpiValue, { color: colors.status.success }]}>{Number(metrics.success_rate || 0).toFixed(1)}%</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Error Rate</Text><Text style={[styles.kpiValue, (metrics.error_rate || 0) > 0 && { color: colors.status.danger }]}>{Number(metrics.error_rate || 0).toFixed(1)}%</Text></View>
            </View>

            <Text style={styles.sectionLabel}>AGENT HEALTH ({agents.length})</Text>
            {agents.length === 0 ? (
              <Card><Text style={styles.emptyText}>Belum ada data eksekusi. Kirim pesan ke AI agent untuk membuat trace pertama.</Text></Card>
            ) : (
              agents.map((a: any) => {
                const latest = a.last_status || "unknown";
                const healthy = latest === "success" || latest === "skipped";
                return (
                  <Card key={a.agent_name} style={{ gap: spacing.xs }}>
                    <View style={styles.rowBetween}>
                      <Text style={styles.itemTitle} numberOfLines={1}>{a.agent_name}</Text>
                      <Badge label={healthy ? "HEALTHY" : latest.toUpperCase()} kind={healthy ? "success" : latest === "running" ? "warning" : "danger"} />
                    </View>
                    <Text style={styles.hint}>
                      {num(a.executions)} eksekusi · {Math.round(a.average_latency_ms || 0)}ms avg · {num(a.total_tokens)} tokens · {a.last_seen_at ? timeAgo(a.last_seen_at) : "—"}
                    </Text>
                  </Card>
                );
              })
            )}

            <Text style={styles.sectionLabel}>REQUEST TRACES ({traces.length}) — TAP UNTUK DETAIL</Text>
            {traces.length === 0 ? (
              <Card><Text style={styles.emptyText}>Belum ada trace. Trace muncul setelah agent memproses pesan.</Text></Card>
            ) : (
              traces.map((t: any) => (
                <Pressable key={t.id} onPress={() => toggleTrace(t.id)}>
                  <Card style={{ gap: spacing.xs }}>
                    <View style={styles.rowBetween}>
                      <Badge label={(t.status || "").toUpperCase()} kind={TRACE_STATUS_KIND[t.status] || "neutral"} />
                      <Text style={styles.hint}>{timeAgo(t.started_at)}</Text>
                    </View>
                    <Text style={styles.itemTitle} numberOfLines={2}>{t.user_question}</Text>
                    <Text style={styles.hint}>
                      {num(t.agent_count)} agents · {t.duration_ms || 0}ms · {num(t.total_tokens)} tokens
                    </Text>
                    {openTraceId === t.id ? (
                      traceLoading ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : traceDetail ? (
                        <View style={styles.traceBox}>
                          {(traceDetail.executions || []).map((step: any, i: number) => (
                            <View key={i} style={styles.traceStep}>
                              <Text style={styles.traceStepTitle}>
                                {i + 1}. {step.agent_name} — {step.status} · {step.duration_ms || 0}ms · {num(step.total_tokens)} tokens
                              </Text>
                              {step.error_message ? <Text style={{ color: colors.status.danger, fontSize: 10 }}>{step.error_message}</Text> : null}
                            </View>
                          ))}
                          {traceDetail.trace?.final_answer ? (
                            <View style={{ gap: 2 }}>
                              <Text style={styles.blockTitle}>FINAL ANSWER</Text>
                              <Text style={styles.finalAnswer} numberOfLines={8}>{traceDetail.trace.final_answer}</Text>
                            </View>
                          ) : null}
                        </View>
                      ) : null
                    ) : null}
                  </Card>
                </Pressable>
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

  pill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  pillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  pillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  pillTextActive: { color: "#fff" },

  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpiCard: { width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 2 },
  kpiLabel: { color: colors.text.faint, fontSize: 10 },
  kpiValue: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },

  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  itemTitle: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  hint: { color: colors.text.faint, fontSize: 10, lineHeight: 15 },
  emptyText: { color: colors.text.muted, fontSize: 13, textAlign: "center" },

  traceBox: { backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, padding: spacing.md, gap: spacing.sm, marginTop: spacing.xs },
  traceStep: { borderLeftWidth: 2, borderLeftColor: colors.brand.violet500, paddingLeft: spacing.sm },
  traceStepTitle: { color: colors.text.body, fontSize: 11, fontWeight: "600" },
  blockTitle: { color: colors.text.muted, fontSize: 9, fontWeight: "700", letterSpacing: 0.5 },
  finalAnswer: { color: colors.text.body, fontSize: 11, lineHeight: 16 },
});
