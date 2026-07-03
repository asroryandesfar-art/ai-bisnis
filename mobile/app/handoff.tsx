import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { decodeJwtPayload } from "../src/auth/jwt";
import { tokenStore } from "../src/auth/tokenStore";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

type QueueItem = {
  id: string;
  conversation_id: string;
  end_user_name: string | null;
  end_user_id: string | null;
  reason: string | null;
  status: string;
  priority: string | null;
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  sla_due_at: string | null;
  created_at: string;
};

const STATUS_KIND: Record<string, BadgeKind> = {
  waiting: "warning", assigned: "neutral", resolved: "success",
};
const PRIORITY_KIND: Record<string, BadgeKind> = {
  urgent: "danger", high: "warning", medium: "neutral", low: "neutral",
};

function timeAgo(iso: string | null) {
  if (!iso) return "—";
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  const abs = Math.abs(mins);
  const label = abs < 60 ? `${abs} menit` : abs < 1440 ? `${Math.round(abs / 60)} jam` : `${Math.round(abs / 1440)} hari`;
  return mins < 0 ? `${label} lalu` : `${label} lagi`;
}

export default function HumanHandoff() {
  const router = useRouter();
  const [myUserId, setMyUserId] = useState<string | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [stats, setStats] = useState<any>({});
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [replyOpenId, setReplyOpenId] = useState<string | null>(null);
  const [replyText, setReplyText] = useState("");

  const load = useCallback(async () => {
    try {
      setError(null);
      const token = await tokenStore.get();
      const payload = token ? decodeJwtPayload(token) : {};
      setMyUserId(payload.sub ? String(payload.sub) : null);

      const [queueRes, statsRes] = await Promise.allSettled([
        api.handoffQueue({ limit: 100 }), api.handoffStats(),
      ]);
      setItems(queueRes.status === "fulfilled" ? (queueRes.value.queue || []) : []);
      setStats(statsRes.status === "fulfilled" ? statsRes.value.stats || {} : {});
      if (queueRes.status === "rejected") setError((queueRes as any).reason?.message || "Gagal memuat antrian handoff.");
    } catch (e: any) {
      setError(e?.message || "Gagal memuat antrian handoff.");
    }
  }, []);

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

  async function claim(item: QueueItem) {
    setBusyId(item.id);
    try {
      await api.claimHandoff(item.id);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal klaim", e?.message || "Tidak bisa mengklaim percakapan ini.");
    } finally {
      setBusyId(null);
    }
  }

  function openReply(item: QueueItem) {
    setReplyOpenId(replyOpenId === item.id ? null : item.id);
    setReplyText("");
  }

  async function sendReply(item: QueueItem) {
    const text = replyText.trim();
    if (!text) return;
    setBusyId(item.id);
    try {
      await api.replyHandoff(item.id, text);
      setReplyOpenId(null);
      setReplyText("");
      Alert.alert("Terkirim", "Balasan Anda sudah dikirim ke pelanggan.");
    } catch (e: any) {
      Alert.alert("Gagal kirim", e?.message || "Tidak bisa mengirim balasan.");
    } finally {
      setBusyId(null);
    }
  }

  function resolve(item: QueueItem) {
    Alert.alert("Selesaikan handoff?", "AI akan mengambil alih kembali percakapan ini.", [
      { text: "Batal", style: "cancel" },
      {
        text: "Selesaikan",
        onPress: async () => {
          setBusyId(item.id);
          try {
            await api.resolveHandoff(item.id, null);
            await load();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa menyelesaikan handoff ini.");
          } finally {
            setBusyId(null);
          }
        },
      },
    ]);
  }

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Human Handoff</Text>
        <View style={{ width: 32 }} />
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

        <View style={styles.kpiGrid}>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Pending</Text>
            <Text style={styles.kpiValue}>{stats.waiting ?? 0}</Text>
            <Text style={styles.kpiSub}>{stats.urgent_waiting ?? 0} urgent</Text>
          </View>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Assigned</Text>
            <Text style={styles.kpiValue}>{stats.assigned ?? 0}</Text>
          </View>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Resolved 24j</Text>
            <Text style={styles.kpiValue}>{stats.resolved_24h ?? 0}</Text>
          </View>
          <View style={styles.kpiCard}>
            <Text style={[styles.kpiValue, (stats.sla_breached ?? 0) > 0 && { color: colors.status.danger }]}>{stats.sla_breached ?? 0}</Text>
            <Text style={styles.kpiLabel}>SLA Breach</Text>
          </View>
        </View>

        <Text style={styles.sectionLabel}>ANTRIAN ({items.length})</Text>
        {items.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Tidak ada percakapan menunggu handoff.</Text></Card>
        ) : (
          items.map((item) => {
            const name = item.end_user_name || item.end_user_id || "Anonim";
            const mine = item.assigned_agent_id && myUserId && String(item.assigned_agent_id) === myUserId;
            const slaBreached = item.sla_due_at && new Date(item.sla_due_at) < new Date() && item.status !== "resolved";
            const busy = busyId === item.id;
            return (
              <Card key={item.id} style={styles.itemCard}>
                <View style={styles.itemHead}>
                  <Text style={styles.itemName} numberOfLines={1}>{name}</Text>
                  <Badge label={(item.status === "waiting" ? "PENDING" : item.status).toUpperCase()} kind={STATUS_KIND[item.status] || "neutral"} />
                </View>
                <View style={styles.chipRow}>
                  <Badge label={item.reason || "manual"} kind="neutral" />
                  {item.priority ? <Badge label={item.priority.toUpperCase()} kind={PRIORITY_KIND[item.priority] || "neutral"} /> : null}
                </View>
                <View style={styles.metaRow}>
                  <Text style={styles.metaText}>
                    {item.assigned_agent_name ? `Ditangani: ${item.assigned_agent_name}` : "Belum ditugaskan"}
                  </Text>
                  <Text style={[styles.metaText, slaBreached && { color: colors.status.danger }]}>
                    SLA {timeAgo(item.sla_due_at)}{slaBreached ? " · TERLEWAT" : ""}
                  </Text>
                </View>

                {busy ? (
                  <ActivityIndicator size="small" color={colors.brand.violet400} />
                ) : item.status === "waiting" ? (
                  <Pressable style={styles.primaryBtn} onPress={() => claim(item)}>
                    <Text style={styles.primaryBtnText}>Klaim</Text>
                  </Pressable>
                ) : mine ? (
                  <View style={{ gap: spacing.sm }}>
                    <View style={styles.actionRow}>
                      <Pressable style={styles.outlineBtn} onPress={() => openReply(item)}>
                        <Text style={styles.outlineBtnText}>{replyOpenId === item.id ? "Batal" : "Balas"}</Text>
                      </Pressable>
                      <Pressable style={styles.primaryBtnSm} onPress={() => resolve(item)}>
                        <Text style={styles.primaryBtnText}>Selesaikan</Text>
                      </Pressable>
                    </View>
                    {replyOpenId === item.id ? (
                      <View style={styles.replyRow}>
                        <TextInput
                          style={styles.replyInput}
                          value={replyText}
                          onChangeText={setReplyText}
                          placeholder="Balasan ke pelanggan…"
                          placeholderTextColor={colors.text.muted}
                          multiline
                        />
                        <Pressable style={styles.sendBtn} onPress={() => sendReply(item)} disabled={!replyText.trim()}>
                          <Ionicons name="send" size={16} color="#fff" />
                        </Pressable>
                      </View>
                    ) : null}
                  </View>
                ) : (
                  <Text style={styles.metaText}>Ditangani agen lain</Text>
                )}
              </Card>
            );
          })
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
  kpiCard: { width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 2 },
  kpiLabel: { color: colors.text.faint, fontSize: 10 },
  kpiValue: { color: colors.text.primary, fontSize: 18, fontWeight: "800" },
  kpiSub: { color: colors.text.muted, fontSize: 10 },

  itemCard: { gap: spacing.sm },
  itemHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  itemName: { flex: 1, color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  metaRow: { flexDirection: "row", justifyContent: "space-between" },
  metaText: { color: colors.text.muted, fontSize: 11 },

  actionRow: { flexDirection: "row", gap: spacing.sm },
  primaryBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingVertical: spacing.sm, alignItems: "center" },
  primaryBtnSm: { flex: 1, backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingVertical: spacing.sm, alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  outlineBtn: { flex: 1, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, paddingVertical: spacing.sm, alignItems: "center" },
  outlineBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },

  replyRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-end" },
  replyInput: {
    flex: 1, backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm, color: colors.text.primary, fontSize: 12, minHeight: 40, maxHeight: 100,
  },
  sendBtn: { width: 36, height: 36, borderRadius: radius.sm, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
});
