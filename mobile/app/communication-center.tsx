import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}

const PERIODS = [
  { value: 1, label: "Hari Ini" }, { value: 7, label: "7 Hari" }, { value: 30, label: "30 Hari" },
  { value: 90, label: "90 Hari" }, { value: 365, label: "1 Tahun" },
];

const CATALOG: { key: string; label: string; icon: keyof typeof MaterialCommunityIcons.glyphMap }[] = [
  { key: "whatsapp", label: "WhatsApp", icon: "whatsapp" },
  { key: "telegram", label: "Telegram", icon: "send-outline" },
  { key: "instagram", label: "Instagram", icon: "instagram" },
  { key: "facebook", label: "Facebook Messenger", icon: "facebook" },
  { key: "website", label: "Website Chat", icon: "web" },
];

const STATUS_KIND: Record<string, BadgeKind> = { connected: "success", active: "success", pending: "warning", disconnected: "neutral" };

export default function CommunicationCenter() {
  const router = useRouter();
  const [days, setDays] = useState(30);
  const [channels, setChannels] = useState<any[]>([]);
  const [analytics, setAnalytics] = useState<any>({});
  const [gmail, setGmail] = useState<any>({});
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (period: number) => {
    try {
      setError(null);
      const [statusRes, analyticsRes, gmailRes] = await Promise.allSettled([
        api.channelStatus(), api.channelAnalytics(period), api.gmailPoller(),
      ]);
      setChannels(statusRes.status === "fulfilled" ? statusRes.value.channels || [] : []);
      setAnalytics(analyticsRes.status === "fulfilled" ? analyticsRes.value : {});
      setGmail(gmailRes.status === "fulfilled" ? gmailRes.value : {});
      if (statusRes.status === "rejected" && analyticsRes.status === "rejected") {
        setError("Gagal memuat Communication Center.");
      }
    } catch (e: any) {
      setError(e?.message || "Gagal memuat Communication Center.");
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

  const usageByChannel = useMemo(() => {
    const map: Record<string, any> = {};
    (analytics.channel_usage || []).forEach((row: any) => { map[row.channel] = row; });
    return map;
  }, [analytics]);

  const gmailStatus = gmail.enabled && gmail.running ? "connected" : gmail.enabled ? "pending" : "disconnected";

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Communication Center</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
          {PERIODS.map((p) => (
            <Pressable key={p.value} onPress={() => setDays(p.value)} style={[styles.pill, days === p.value && styles.pillActive]}>
              <Text style={[styles.pillText, days === p.value && styles.pillTextActive]}>{p.label}</Text>
            </Pressable>
          ))}
        </ScrollView>

        {loading ? <ActivityIndicator color={colors.brand.violet400} /> : (
          <>
            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Total Messages</Text><Text style={styles.kpiValue}>{num(analytics.total_messages)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Response Rate</Text><Text style={styles.kpiValue}>{analytics.response_rate_pct != null ? `${analytics.response_rate_pct}%` : "—"}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Satisfaction</Text><Text style={styles.kpiValue}>{analytics.satisfaction_avg != null ? `${analytics.satisfaction_avg}/5` : "—"}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>AI Resolution</Text><Text style={styles.kpiValue}>{analytics.ai_resolution_rate_pct != null ? `${analytics.ai_resolution_rate_pct}%` : "—"}</Text></View>
            </View>

            <Text style={styles.sectionLabel}>PERFORMA PER CHANNEL</Text>
            {CATALOG.map((c) => {
              const item = channels.find((row) => row.channel_type === c.key && row.status !== "disconnected") || channels.find((row) => row.channel_type === c.key);
              const status = item?.status || "disconnected";
              const usage = usageByChannel[c.key] || {};
              return (
                <Card key={c.key} style={styles.channelCard}>
                  <View style={styles.channelHead}>
                    <View style={styles.channelIcon}>
                      <MaterialCommunityIcons name={c.icon} size={18} color={colors.brand.violet400} />
                    </View>
                    <Text style={styles.channelName}>{c.label}</Text>
                    <Badge label={status.charAt(0).toUpperCase() + status.slice(1)} kind={STATUS_KIND[status] || "neutral"} />
                  </View>
                  <View style={styles.statGrid}>
                    <Stat label="Messages" value={num(usage.messages || 0)} />
                    <Stat label="Response Rate" value={usage.response_rate_pct != null ? `${usage.response_rate_pct}%` : "—"} />
                    <Stat label="Response Time" value={usage.response_time_ms != null ? `${Number(usage.response_time_ms).toFixed(0)}ms` : "—"} />
                    <Stat label="Satisfaction" value={usage.satisfaction_avg != null ? `${usage.satisfaction_avg}/5` : "—"} />
                    <Stat label="AI Resolution" value={usage.ai_resolution_rate_pct != null ? `${usage.ai_resolution_rate_pct}%` : "—"} />
                  </View>
                </Card>
              );
            })}

            <Card style={styles.channelCard}>
              <View style={styles.channelHead}>
                <View style={styles.channelIcon}>
                  <MaterialCommunityIcons name="email-outline" size={18} color={colors.brand.violet400} />
                </View>
                <Text style={styles.channelName}>Email (Gmail)</Text>
                <Badge label={gmailStatus.charAt(0).toUpperCase() + gmailStatus.slice(1)} kind={STATUS_KIND[gmailStatus] || "neutral"} />
              </View>
              <View style={styles.statGrid}>
                <Stat label="Polling Interval" value={`${num(gmail.interval_seconds || 0)}s`} />
                <Stat label="Max per Poll" value={num(gmail.max_messages || 0)} />
              </View>
              <Text style={styles.gmailNote}>Email memakai jalur polling terpisah dari channel lain — metrik response/satisfaction belum tersedia.</Text>
            </Card>
          </>
        )}
      </ScrollView>
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.statItem}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statValue}>{value}</Text>
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

  channelCard: { gap: spacing.sm },
  channelHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  channelIcon: { width: 32, height: 32, borderRadius: radius.sm, backgroundColor: "rgba(139,92,246,0.12)", alignItems: "center", justifyContent: "center" },
  channelName: { flex: 1, color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  statGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  statItem: { width: "31%", flexGrow: 1 },
  statLabel: { color: colors.text.faint, fontSize: 9 },
  statValue: { color: colors.text.body, fontSize: 13, fontWeight: "700" },
  gmailNote: { color: colors.text.faint, fontSize: 10, lineHeight: 14 },
});
