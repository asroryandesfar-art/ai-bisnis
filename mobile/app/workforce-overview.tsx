import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { idr } from "../src/utils/format";

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}

const HEALTH_KIND: Record<string, BadgeKind> = { healthy: "success", warning: "warning", critical: "danger" };

export default function WorkforceOverview() {
  const router = useRouter();
  const [data, setData] = useState<Record<string, any>>({});
  const [failed, setFailed] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const defs: [string, Promise<any>][] = [
      ["finance", api.financeDashboard()], ["marketing", api.marketingDashboard()], ["hr", api.hrDashboard()],
      ["operations", api.opsDashboard()], ["security", api.securityDashboard()], ["executive", api.executiveDashboard()],
      ["workforce", api.workforceDashboard()], ["learning", api.learningDashboard()],
    ];
    const results = await Promise.allSettled(defs.map(([, p]) => p));
    const next: Record<string, any> = {};
    const failedLabels: string[] = [];
    results.forEach((res, i) => {
      const label = defs[i][0];
      if (res.status === "fulfilled") next[label] = res.value;
      else failedLabels.push(label);
    });
    setData(next);
    setFailed(failedLabels);
    setLoading(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  const executiveHealth = data.executive?.health || {};
  const opsHealth = data.operations?.health || {};
  const securityRisk = data.security?.risk_level || "—";
  const workforceStatus = data.workforce?.by_status || {};
  const learningStatus = data.learning?.by_status || {};
  const openOpsAlerts = Object.values(data.operations?.open_alerts_by_severity || {}).reduce((s: number, v: any) => s + Number(v || 0), 0);
  const securityOpenAlerts = data.security?.open_risk_alerts_count ?? data.security?.security_events_24h ?? 0;
  const activeTasks = (workforceStatus.pending || 0) + (workforceStatus.in_progress || 0);

  const domains: { key: string; label: string; value: string; meta: string; route: string | null; icon: keyof typeof MaterialCommunityIcons.glyphMap }[] = [
    { key: "finance", label: "Finance", value: idr(data.finance?.revenue_30d_idr || 0), meta: `${num(data.finance?.pending_invoices_count || 0)} invoice pending`, route: "/finance", icon: "cash-multiple" },
    { key: "marketing", label: "Marketing", value: num(data.marketing?.content_published ?? 0), meta: "Konten published", route: "/marketing", icon: "bullhorn-outline" },
    { key: "hr", label: "HR", value: num(data.hr?.pending_training_recommendations ?? 0), meta: "Training/kandidat perlu review", route: "/hr", icon: "account-group-outline" },
    { key: "operations", label: "Operations", value: String(opsHealth.score ?? "—"), meta: `${num(openOpsAlerts)} alert terbuka`, route: "/operations", icon: "cog-sync-outline" },
    { key: "security", label: "Security", value: String(securityRisk), meta: `${num(securityOpenAlerts)} sinyal risiko`, route: "/security", icon: "shield-outline" },
    { key: "executive", label: "Executive", value: String(executiveHealth.overall ?? "—"), meta: executiveHealth.label || "Company health", route: "/executive", icon: "briefcase-outline" },
    { key: "workforce", label: "Workforce", value: num(activeTasks), meta: "Task aktif lintas-agent", route: "/tugas", icon: "account-hard-hat" },
    { key: "learning", label: "Self-Learning", value: num(learningStatus.candidate || 0), meta: "Insight menunggu approval", route: "/self-learning", icon: "school-outline" },
  ];

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>AI Workforce Overview</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {loading ? <ActivityIndicator color={colors.brand.violet400} /> : (
          <>
            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Company Health</Text>
                <Text style={styles.kpiValue}>{executiveHealth.overall ?? "—"}</Text>
                <Badge label={(executiveHealth.label || "watch").toUpperCase()} kind={HEALTH_KIND[executiveHealth.label] || "neutral"} />
              </View>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Operations Health</Text>
                <Text style={styles.kpiValue}>{opsHealth.score ?? "—"}</Text>
                <Badge label={(opsHealth.label || "watch").toUpperCase()} kind={HEALTH_KIND[opsHealth.label] || "neutral"} />
              </View>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Security Risk</Text>
                <Text style={styles.kpiValue}>{String(securityRisk).charAt(0).toUpperCase() + String(securityRisk).slice(1)}</Text>
              </View>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Active Tasks</Text>
                <Text style={styles.kpiValue}>{num(activeTasks)}</Text>
                <Text style={styles.kpiSub}>{num(data.workforce?.pending_approval_count || 0)} butuh approval</Text>
              </View>
            </View>

            <Text style={styles.sectionLabel}>DOMAIN OVERVIEW — TAP UNTUK MASUK</Text>
            {domains.map((d) => {
              const card = (
                <Card style={styles.domainCard}>
                  <View style={styles.domainIcon}>
                    <MaterialCommunityIcons name={d.icon} size={18} color={colors.brand.violet400} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.domainLabel}>{d.label}</Text>
                    <Text style={styles.domainMeta}>{d.meta}</Text>
                  </View>
                  <Text style={styles.domainValue}>{d.value}</Text>
                  {d.route ? <Ionicons name="chevron-forward" size={16} color={colors.text.faint} /> : null}
                </Card>
              );
              return d.route ? (
                <Pressable key={d.key} onPress={() => router.push(d.route as any)}>{card}</Pressable>
              ) : (
                <View key={d.key}>{card}</View>
              );
            })}

            {failed.length ? (
              <Card style={{ borderColor: colors.status.warning }}>
                <Text style={styles.hint}>Data belum lengkap: {failed.join(", ")} tidak bisa dimuat (kemungkinan keterbatasan izin role).</Text>
              </Card>
            ) : null}
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
  kpiCard: { width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 4 },
  kpiLabel: { color: colors.text.faint, fontSize: 10 },
  kpiValue: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  kpiSub: { color: colors.text.muted, fontSize: 10 },

  domainCard: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  domainIcon: { width: 34, height: 34, borderRadius: radius.sm, backgroundColor: "rgba(139,92,246,0.12)", alignItems: "center", justifyContent: "center" },
  domainLabel: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  domainMeta: { color: colors.text.faint, fontSize: 10, marginTop: 1 },
  domainValue: { color: colors.brand.violet400, fontSize: 15, fontWeight: "800" },
  hint: { color: colors.text.faint, fontSize: 11, lineHeight: 16 },
});
