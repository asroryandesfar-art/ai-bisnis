import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

function timeAgo(iso: string | null) {
  if (!iso) return "—";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "baru saja";
  if (mins < 60) return `${mins} menit lalu`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h} jam lalu`;
  return `${Math.floor(h / 24)} hari lalu`;
}

const INTENT_KIND: Record<string, BadgeKind> = {
  general: "neutral", business: "warning", faq: "success", sales: "warning",
  customer_service: "warning", knowledge: "success", analytics: "success", human_handoff: "danger",
};

export default function RoutingLogs() {
  const router = useRouter();
  const [bots, setBots] = useState<any[]>([]);
  const [botId, setBotId] = useState<string | null>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadBots = useCallback(async () => {
    try {
      const list = await api.bots();
      setBots(list || []);
      setBotId((prev) => prev || list?.[0]?.id || null);
      if (!list?.length) setLoading(false);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat daftar agen.");
      setLoading(false);
    }
  }, []);

  const loadLogs = useCallback(async (id: string) => {
    try {
      setError(null);
      const res = await api.routingLogs(id);
      setLogs(res.logs || []);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat routing logs (butuh izin analytics.read).");
      setLogs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { loadBots(); }, [loadBots]));
  useEffect(() => {
    if (botId) loadLogs(botId);
  }, [botId, loadLogs]);

  async function onRefresh() {
    setRefreshing(true);
    if (botId) await loadLogs(botId);
    setRefreshing(false);
  }

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Routing Logs</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {bots.length > 1 ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
            {bots.map((b) => (
              <Pressable key={b.id} onPress={() => setBotId(b.id)} style={[styles.pill, botId === b.id && styles.pillActive]}>
                <Text style={[styles.pillText, botId === b.id && styles.pillTextActive]}>{b.name}</Text>
              </Pressable>
            ))}
          </ScrollView>
        ) : null}

        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        {loading ? <ActivityIndicator color={colors.brand.violet400} /> : (
          <>
            <Text style={styles.sectionLabel}>ROUTING DECISIONS ({logs.length})</Text>
            {logs.length === 0 && !error ? (
              <Card><Text style={styles.emptyText}>Belum ada routing data. Kirim beberapa pesan ke agent ini untuk mengisi log.</Text></Card>
            ) : (
              logs.map((log) => (
                <Card key={log.id} style={{ gap: spacing.xs }}>
                  <View style={styles.rowBetween}>
                    <Badge label={(log.intent || "—").toUpperCase()} kind={INTENT_KIND[log.intent] || "neutral"} />
                    <Text style={styles.hint}>{timeAgo(log.created_at)}</Text>
                  </View>
                  <Text style={styles.customer}>{log.end_user_name || log.end_user_email || "Anonymous"}</Text>
                  <Text style={styles.message} numberOfLines={2}>{log.content}</Text>
                  <View style={styles.metaRow}>
                    <Text style={styles.hint}>Agent: {log.selected_agent || "—"}</Text>
                    <Text style={styles.hint}>
                      Confidence: {log.routing_confidence != null ? `${Math.round(Number(log.routing_confidence) * 100)}%` : "—"}
                    </Text>
                    {log.handoff_status ? <Badge label={log.handoff_status.toUpperCase()} kind="danger" /> : null}
                  </View>
                </Card>
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

  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  customer: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  message: { color: colors.text.muted, fontSize: 12, lineHeight: 17 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, flexWrap: "wrap" },
  hint: { color: colors.text.faint, fontSize: 10 },
  emptyText: { color: colors.text.muted, fontSize: 13, textAlign: "center" },
});
