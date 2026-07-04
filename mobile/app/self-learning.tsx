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

const CATEGORY_LABEL: Record<string, string> = {
  sales_pattern: "Sales Pattern", complaint_resolution: "Complaint Resolution", successful_approach: "Successful Approach",
};
const STATUS_KIND: Record<string, BadgeKind> = { candidate: "warning", approved: "success", rejected: "danger", archived: "neutral" };

export default function SelfLearningCenter() {
  const router = useRouter();
  const [dash, setDash] = useState<any>({});
  const [insights, setInsights] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [dashRes, insightsRes] = await Promise.allSettled([api.learningDashboard(), api.learningInsights(50)]);
      setDash(dashRes.status === "fulfilled" ? dashRes.value : {});
      setInsights(insightsRes.status === "fulfilled" ? insightsRes.value.insights || [] : []);
      if (dashRes.status === "rejected") setError((dashRes as any).reason?.message || "Gagal memuat Self-Learning Center.");
    } catch (e: any) {
      setError(e?.message || "Gagal memuat Self-Learning Center.");
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
      await api.learningScan(90);
      await load();
      Alert.alert("Selesai", "Scan pola percakapan selesai dijalankan.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menjalankan scan.");
    } finally {
      setBusy(null);
    }
  }

  async function updateInsight(id: string, status: string) {
    setBusy(id);
    try {
      await api.updateLearningInsight(id, status);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memperbarui insight.");
    } finally {
      setBusy(null);
    }
  }

  const byStatus = dash.by_status || {};
  const approvedByCategory = dash.approved_by_category || {};

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Self-Learning Center</Text>
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
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Candidate</Text><Text style={[styles.kpiValue, (byStatus.candidate || 0) > 0 && { color: colors.status.warning }]}>{num(byStatus.candidate)}</Text><Text style={styles.kpiSub}>Menunggu review</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Approved</Text><Text style={[styles.kpiValue, { color: colors.status.success }]}>{num(byStatus.approved)}</Text><Text style={styles.kpiSub}>Aktif di chat</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Sales Pattern</Text><Text style={styles.kpiValue}>{num(approvedByCategory.sales_pattern)}</Text><Text style={styles.kpiSub}>Approved</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Successful Approach</Text><Text style={styles.kpiValue}>{num(approvedByCategory.successful_approach)}</Text><Text style={styles.kpiSub}>Approved</Text></View>
            </View>

            <Text style={styles.sectionLabel}>LEARNING INSIGHTS ({insights.length}) — HANYA YANG APPROVED MEMPENGARUHI JAWABAN BOT</Text>
            {insights.length === 0 ? (
              <Card><Text style={styles.emptyText}>Belum ada insight. Jalankan scan (ikon refresh di atas) untuk mendeteksi pola dari percakapan, penjualan, dan komplain.</Text></Card>
            ) : (
              insights.map((item) => (
                <Card key={item.id} style={{ gap: spacing.xs }}>
                  <View style={styles.rowBetween}>
                    <Badge label={(CATEGORY_LABEL[item.category] || item.category || "").toUpperCase()} kind="neutral" />
                    <Badge label={(item.status || "").toUpperCase()} kind={STATUS_KIND[item.status] || "neutral"} />
                  </View>
                  <Text style={styles.itemTitle}>{item.insight}</Text>
                  <Text style={styles.hint}>Terdeteksi {num(item.occurrence_count)}x</Text>
                  {busy === item.id ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                    <View style={styles.actionRow}>
                      {item.status === "candidate" ? (
                        <>
                          <ActionBtn label="Approve" primary onPress={() => updateInsight(item.id, "approved")} />
                          <ActionBtn label="Reject" danger onPress={() => updateInsight(item.id, "rejected")} />
                        </>
                      ) : null}
                      {item.status === "approved" ? <ActionBtn label="Archive" onPress={() => updateInsight(item.id, "archived")} /> : null}
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
  kpiSub: { color: colors.text.muted, fontSize: 9 },

  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  itemTitle: { color: colors.text.primary, fontSize: 13, fontWeight: "700", lineHeight: 18 },
  hint: { color: colors.text.faint, fontSize: 10 },
  emptyText: { color: colors.text.muted, fontSize: 13, textAlign: "center" },

  actionRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  actionBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt },
  actionBtnPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  actionBtnDanger: { backgroundColor: colors.status.dangerBg, borderColor: colors.status.danger },
  actionBtnText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },
});
