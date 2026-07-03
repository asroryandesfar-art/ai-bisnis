import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

const PERIODS = [7, 30, 90] as const;

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}

export default function Analytics() {
  const router = useRouter();
  const params = useLocalSearchParams<{ botId?: string }>();
  const [bots, setBots] = useState<{ id: string; name: string }[]>([]);
  const [botId, setBotId] = useState<string | null>(params.botId ?? null);
  const [days, setDays] = useState<(typeof PERIODS)[number]>(30);
  const [analytics, setAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAnalytics = useCallback(async (id: string, d: number) => {
    try {
      setError(null);
      const res = await api.botAnalytics(id, d);
      setAnalytics(res);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat analytics.");
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const botsRes = await api.bots();
      const list = (botsRes as any[]).map((b) => ({ id: b.id, name: b.name }));
      setBots(list);
      const activeBotId = botId || list[0]?.id || null;
      setBotId(activeBotId);
      if (activeBotId) await loadAnalytics(activeBotId, days);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat analytics.");
    } finally {
      setLoading(false);
    }
  }, [botId, days, loadAnalytics]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  function switchBot(id: string) {
    setBotId(id);
    loadAnalytics(id, days);
  }

  function switchPeriod(d: (typeof PERIODS)[number]) {
    setDays(d);
    if (botId) loadAnalytics(botId, d);
  }

  const summary = analytics?.summary || {};
  const dailyVolume: { date: string; convs: number }[] = analytics?.daily_volume || [];
  const topQuestions: { content: string; frequency: number }[] = analytics?.top_questions || [];

  const resolution = summary.total_convs
    ? Math.round((1 - (summary.handoff_count || 0) / summary.total_convs) * 100)
    : 0;
  const coveragePct = Math.max(0, 100 - Math.round(((summary.handoff_count || 0) / (summary.total_convs || 1)) * 100));
  const ratingPct = Math.min(100, Number(summary.avg_rating || 0) * 20);

  const maxVolume = useMemo(() => Math.max(1, ...dailyVolume.map((d) => d.convs)), [dailyVolume]);
  const maxFrequency = topQuestions[0]?.frequency || 1;

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Analytics</Text>
        <View style={{ width: 32 }} />
      </View>

      {bots.length > 1 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.pillRow}>
          {bots.map((b) => (
            <Pressable key={b.id} onPress={() => switchBot(b.id)} style={[styles.pill, botId === b.id && styles.pillActive]}>
              <Text style={[styles.pillText, botId === b.id && styles.pillTextActive]} numberOfLines={1}>{b.name}</Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : null}

      <View style={styles.periodRow}>
        {PERIODS.map((d) => (
          <Pressable key={d} onPress={() => switchPeriod(d)} style={[styles.pill, days === d && styles.pillActive]}>
            <Text style={[styles.pillText, days === d && styles.pillTextActive]}>{d}d</Text>
          </Pressable>
        ))}
      </View>

      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
      >
        {error ? (
          <Card style={{ borderColor: colors.status.danger }}>
            <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
          </Card>
        ) : null}

        {!botId ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada agen.</Text></Card>
        ) : loading ? (
          <View style={{ paddingVertical: spacing.xxl, alignItems: "center" }}>
            <ActivityIndicator color={colors.brand.violet400} />
          </View>
        ) : (
          <>
            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Percakapan</Text>
                <Text style={styles.kpiValue}>{num(summary.total_convs)}</Text>
                <Text style={styles.kpiSub}>{num(summary.total_msgs)} pesan</Text>
              </View>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>AI Resolution</Text>
                <Text style={styles.kpiValue}>{resolution}%</Text>
                <Text style={styles.kpiSub}>{num(summary.handoff_count)} handoff</Text>
              </View>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Avg Rating</Text>
                <Text style={styles.kpiValue}>{summary.avg_rating ? `${Number(summary.avg_rating).toFixed(1)}/5` : "—"}</Text>
                <Text style={styles.kpiSub}>kepuasan pelanggan</Text>
              </View>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>AI Latency</Text>
                <Text style={styles.kpiValue}>{summary.avg_latency_ms ? `${Math.round(summary.avg_latency_ms)}ms` : "—"}</Text>
                <Text style={styles.kpiSub}>waktu respons</Text>
              </View>
            </View>

            <Text style={styles.sectionLabel}>VOLUME PERCAKAPAN HARIAN</Text>
            <Card>
              {dailyVolume.length === 0 ? (
                <Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada data percakapan pada periode ini.</Text>
              ) : (
                <View style={styles.chartRow}>
                  {dailyVolume.map((d) => (
                    <View key={d.date} style={styles.barCol}>
                      <View style={styles.barTrack}>
                        <View style={[styles.barFill, { height: `${Math.max(4, (d.convs / maxVolume) * 100)}%` }]} />
                      </View>
                      <Text style={styles.barLabel} numberOfLines={1}>{d.date.slice(5)}</Text>
                    </View>
                  ))}
                </View>
              )}
            </Card>

            <Text style={styles.sectionLabel}>KUALITAS LAYANAN</Text>
            <Card style={{ gap: spacing.md }}>
              <QualityRow label="AI Resolution" value={resolution} />
              <QualityRow label="Customer Rating" value={ratingPct} display={summary.avg_rating ? `${Number(summary.avg_rating).toFixed(1)}/5` : "0/5"} />
              <QualityRow label="Automated Coverage" value={coveragePct} />
            </Card>

            <Text style={styles.sectionLabel}>PERTANYAAN TERPOPULER</Text>
            {topQuestions.length === 0 ? (
              <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada data pertanyaan.</Text></Card>
            ) : (
              <Card style={{ padding: 0 }}>
                {topQuestions.map((q, i) => (
                  <View key={i} style={[styles.qRow, i > 0 && styles.qRowBorder]}>
                    <Text style={styles.qRank}>{String(i + 1).padStart(2, "0")}</Text>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.qText} numberOfLines={2}>{q.content}</Text>
                      <View style={styles.qBarTrack}>
                        <View style={[styles.qBarFill, { width: `${Math.max(6, Math.round((q.frequency / maxFrequency) * 100))}%` }]} />
                      </View>
                    </View>
                    <Text style={styles.qFreq}>{num(q.frequency)}x</Text>
                  </View>
                ))}
              </Card>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function QualityRow({ label, value, display }: { label: string; value: number; display?: string }) {
  return (
    <View style={{ gap: spacing.xs }}>
      <View style={styles.qualityHead}>
        <Text style={styles.qualityLabel}>{label}</Text>
        <Text style={styles.qualityValue}>{display ?? `${value}%`}</Text>
      </View>
      <View style={styles.progressTrack}>
        <View style={[styles.progressFill, { width: `${Math.min(100, Math.max(0, value))}%` }]} />
      </View>
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
  pillRow: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  periodRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  pill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  pillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  pillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  pillTextActive: { color: "#fff" },

  container: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },

  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpiCard: { width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 2 },
  kpiLabel: { color: colors.text.faint, fontSize: 10 },
  kpiValue: { color: colors.text.primary, fontSize: 18, fontWeight: "800", marginTop: 2 },
  kpiSub: { color: colors.text.muted, fontSize: 10 },

  chartRow: { flexDirection: "row", alignItems: "flex-end", gap: 3, height: 140 },
  barCol: { flex: 1, alignItems: "center", gap: 4, height: "100%", justifyContent: "flex-end" },
  barTrack: { width: "100%", flex: 1, justifyContent: "flex-end" },
  barFill: { width: "100%", backgroundColor: colors.brand.violet500, borderRadius: 3, minHeight: 4 },
  barLabel: { color: colors.text.faint, fontSize: 8 },

  qualityHead: { flexDirection: "row", justifyContent: "space-between" },
  qualityLabel: { color: colors.text.body, fontSize: 13 },
  qualityValue: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  progressTrack: { height: 6, borderRadius: 3, backgroundColor: colors.bg.border, overflow: "hidden" },
  progressFill: { height: "100%", backgroundColor: colors.brand.violet500, borderRadius: 3 },

  qRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md },
  qRowBorder: { borderTopWidth: 1, borderTopColor: colors.bg.border },
  qRank: { color: colors.text.faint, fontSize: 11, fontWeight: "700", width: 20 },
  qText: { color: colors.text.primary, fontSize: 13, fontWeight: "600" },
  qBarTrack: { height: 4, borderRadius: 2, backgroundColor: colors.bg.border, overflow: "hidden", marginTop: spacing.xs, width: "80%" },
  qBarFill: { height: "100%", backgroundColor: colors.brand.violet500, borderRadius: 2 },
  qFreq: { color: colors.text.muted, fontSize: 11, fontWeight: "700" },
});
