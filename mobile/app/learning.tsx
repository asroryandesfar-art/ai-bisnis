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

const QUEUE_STATUS_KIND: Record<string, BadgeKind> = {
  pending: "warning", in_progress: "warning", resolved: "success", dismissed: "neutral",
};

export default function FeedbackLearning() {
  const router = useRouter();
  const [summary, setSummary] = useState<any>({});
  const [queue, setQueue] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [sumRes, queueRes] = await Promise.allSettled([api.feedbackSummary(30), api.feedbackQueue()]);
      setSummary(sumRes.status === "fulfilled" ? sumRes.value : {});
      setQueue(queueRes.status === "fulfilled" ? queueRes.value.queue || [] : []);
      if (sumRes.status === "rejected") setError((sumRes as any).reason?.message || "Gagal memuat Feedback Learning.");
    } catch (e: any) {
      setError(e?.message || "Gagal memuat Feedback Learning.");
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

  async function updateQueueItem(id: string, status: string) {
    setBusy(id);
    try {
      await api.updateFeedbackQueue(id, status);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memperbarui item ini.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Feedback Learning</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        {loading ? <ActivityIndicator color={colors.brand.violet400} /> : (
          <>
            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Total Feedback</Text><Text style={styles.kpiValue}>{num(summary.total_feedback)}</Text><Text style={styles.kpiSub}>{num(summary.helpful)} helpful (30 hari)</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Helpful Rate</Text><Text style={[styles.kpiValue, { color: colors.status.success }]}>{Number(summary.helpful_rate || 0).toFixed(1)}%</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Not Helpful</Text><Text style={[styles.kpiValue, (summary.not_helpful || 0) > 0 && { color: colors.status.danger }]}>{num(summary.not_helpful)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Learning Queue</Text><Text style={styles.kpiValue}>{num(summary.queue?.pending)}</Text><Text style={styles.kpiSub}>{num(summary.queue?.in_progress)} in progress</Text></View>
            </View>

            <SignalSection title="TOP FEEDBACK POSITIF" rows={summary.top_positive_feedback} />
            <SignalSection title="TOP FEEDBACK NEGATIF" rows={summary.top_negative_feedback} />
            <SignalSection title="PERTANYAAN GAGAL TERBANYAK" rows={summary.most_failed_questions} />
            <SignalSection title="KNOWLEDGE GAPS" rows={summary.knowledge_gaps} />

            <Text style={styles.sectionLabel}>LEARNING QUEUE ({queue.length})</Text>
            {queue.length === 0 ? (
              <Card><Text style={styles.emptyText}>Antrian kosong. Item muncul setelah user menilai jawaban AI.</Text></Card>
            ) : (
              queue.map((item) => (
                <Card key={item.id} style={{ gap: spacing.xs }}>
                  <View style={styles.rowBetween}>
                    <Badge label={(item.action_type || "").toUpperCase().replace(/_/g, " ")} kind="neutral" />
                    <Badge label={(item.status || "").toUpperCase()} kind={QUEUE_STATUS_KIND[item.status] || "neutral"} />
                  </View>
                  <Text style={styles.itemTitle} numberOfLines={2}>{item.question}</Text>
                  {item.failure_reason ? <Text style={styles.hint}>{item.failure_reason}</Text> : null}
                  <Text style={styles.hint}>{num(item.occurrence_count)} sinyal</Text>
                  {busy === item.id ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                    <View style={styles.actionRow}>
                      {item.status === "pending" ? <ActionBtn label="Start" onPress={() => updateQueueItem(item.id, "in_progress")} /> : null}
                      {item.status !== "resolved" && item.status !== "dismissed" ? (
                        <ActionBtn label="Resolve" primary onPress={() => updateQueueItem(item.id, "resolved")} />
                      ) : null}
                    </View>
                  )}
                </Card>
              ))
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function SignalSection({ title, rows }: { title: string; rows?: any[] }) {
  const data = rows || [];
  if (!data.length) return null;
  return (
    <>
      <Text style={styles.sectionLabel}>{title}</Text>
      {data.map((row, i) => (
        <Card key={i} style={{ gap: 2 }}>
          <Text style={styles.itemTitle} numberOfLines={2}>{row.question || "No question recorded"}</Text>
          {(row.comment || row.failure_reason || row.answer) ? (
            <Text style={styles.hint} numberOfLines={2}>{row.comment || row.failure_reason || row.answer}</Text>
          ) : null}
          <Text style={styles.hint}>{num(row.feedback_count || row.failure_count || row.occurrence_count || 1)} sinyal</Text>
        </Card>
      ))}
    </>
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

  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpiCard: { width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 2 },
  kpiLabel: { color: colors.text.faint, fontSize: 10 },
  kpiValue: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  kpiSub: { color: colors.text.muted, fontSize: 9 },

  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  itemTitle: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  hint: { color: colors.text.faint, fontSize: 10, lineHeight: 15 },
  emptyText: { color: colors.text.muted, fontSize: 13, textAlign: "center" },

  actionRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  actionBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt },
  actionBtnPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  actionBtnText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },
});
