import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

type Source = "local_agent" | "computer_agent" | "channel_messaging";

type QueueItem = {
  id: string;
  source: Source;
  title: string;
  subtitle: string;
  meta: string;
  createdAt: string;
};

const SOURCE_LABEL: Record<Source, string> = {
  local_agent: "Local Agent",
  computer_agent: "Computer Agent",
  channel_messaging: "Channel Messaging",
};

const SOURCE_ICON: Record<Source, keyof typeof MaterialCommunityIcons.glyphMap> = {
  local_agent: "laptop",
  computer_agent: "monitor",
  channel_messaging: "message-outline",
};

function timeAgo(iso: string) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "baru saja";
  if (mins < 60) return `${mins} menit lalu`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} jam lalu`;
  return `${Math.floor(hours / 24)} hari lalu`;
}

export default function Antrian() {
  const router = useRouter();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [laRes, caRes, cmRes] = await Promise.allSettled([
        api.localAgentPending(),
        api.computerAgentPending(),
        api.channelMessagingPending(),
      ]);

      const merged: QueueItem[] = [];

      if (laRes.status === "fulfilled") {
        for (const c of laRes.value.commands || []) {
          let argsPreview = "";
          try {
            argsPreview = JSON.stringify(JSON.parse(c.args || "{}"));
          } catch {
            argsPreview = c.args || "";
          }
          merged.push({
            id: c.id,
            source: "local_agent",
            title: `Jalankan: ${c.tool}`,
            subtitle: argsPreview,
            meta: "Aksi di komputer Anda",
            createdAt: c.created_at,
          });
        }
      }
      if (caRes.status === "fulfilled") {
        for (const t of caRes.value.tasks || []) {
          merged.push({
            id: t.id,
            source: "computer_agent",
            title: t.goal || "Aksi browser",
            subtitle: t.target_url || "",
            meta: "Aksi browser otomatis",
            createdAt: t.created_at,
          });
        }
      }
      if (cmRes.status === "fulfilled") {
        for (const t of cmRes.value.tasks || []) {
          merged.push({
            id: t.id,
            source: "channel_messaging",
            title: `Kirim pesan ke ${t.recipient || "pelanggan"}`,
            subtitle: t.message || "",
            meta: `${t.channel || "channel"} · ${t.agent_name || "AI Agent"}`,
            createdAt: t.created_at,
          });
        }
      }

      merged.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
      setItems(merged);

      const failedCount = [laRes, caRes, cmRes].filter((r) => r.status === "rejected").length;
      if (failedCount > 0 && merged.length === 0) {
        setError("Sebagian antrian gagal dimuat. Tarik ke bawah untuk coba lagi.");
      }
    } catch (e: any) {
      setError(e?.message || "Gagal memuat antrian persetujuan.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function handleApprove(item: QueueItem) {
    setBusyId(item.id);
    try {
      if (item.source === "local_agent") await api.localAgentApprove(item.id);
      else if (item.source === "computer_agent") await api.computerAgentApprove(item.id);
      else await api.channelMessagingApprove(item.id);
      setItems((prev) => prev.filter((i) => i.id !== item.id));
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Approve gagal, coba lagi.");
    } finally {
      setBusyId(null);
    }
  }

  function handleReject(item: QueueItem) {
    Alert.alert("Tolak item ini?", item.title, [
      { text: "Batal", style: "cancel" },
      {
        text: "Tolak",
        style: "destructive",
        onPress: async () => {
          setBusyId(item.id);
          try {
            const reason = "Ditolak dari app mobile";
            if (item.source === "local_agent") await api.localAgentReject(item.id, reason);
            else if (item.source === "computer_agent") await api.computerAgentReject(item.id, reason);
            else await api.channelMessagingReject(item.id, reason);
            setItems((prev) => prev.filter((i) => i.id !== item.id));
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Reject gagal, coba lagi.");
          } finally {
            setBusyId(null);
          }
        },
      },
    ]);
  }

  const highPriorityCount = useMemo(() => items.filter((i) => i.source === "local_agent").length, [items]);

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.container}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
    >
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Ionicons name="chevron-back" size={20} color={colors.text.body} />
        </Pressable>
        <View style={styles.brandRow}>
          <View style={styles.brandIcon}>
            <MaterialCommunityIcons name="robot-outline" size={16} color="#fff" />
          </View>
          <Text style={styles.brandText}>BotNesia</Text>
        </View>
        <View style={{ width: 36 }} />
      </View>

      <View>
        <Text style={styles.title}>Antrian Persetujuan</Text>
        <Text style={styles.subtitle}>{items.length} item menunggu tindakan Anda</Text>
      </View>

      {highPriorityCount > 0 ? (
        <View style={styles.warningBanner}>
          <MaterialCommunityIcons name="alert-circle-outline" size={18} color={colors.status.warning} />
          <View style={{ flex: 1 }}>
            <Text style={styles.warningTitle}>Perhatian Dibutuhkan</Text>
            <Text style={styles.warningText}>
              {highPriorityCount} item akses komputer lokal membutuhkan persetujuan segera
            </Text>
          </View>
        </View>
      ) : null}

      {error ? (
        <Card style={{ borderColor: colors.status.danger }}>
          <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
        </Card>
      ) : null}

      {!error && items.length === 0 ? (
        <Card>
          <Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>
            Tidak ada antrean persetujuan. Semua beres!
          </Text>
        </Card>
      ) : null}

      {items.map((item) => (
        <Card key={`${item.source}-${item.id}`} style={styles.itemCard}>
          <View style={styles.itemHeaderRow}>
            <View style={styles.sourceIcon}>
              <MaterialCommunityIcons name={SOURCE_ICON[item.source]} size={16} color={colors.brand.violet400} />
            </View>
            <Text style={styles.itemTitle} numberOfLines={2}>
              {item.title}
            </Text>
          </View>
          <Text style={styles.itemMeta}>
            {SOURCE_LABEL[item.source]} · {item.meta} · {timeAgo(item.createdAt)}
          </Text>
          {item.subtitle ? (
            <View style={styles.subtitleBox}>
              <Text style={styles.subtitleText} numberOfLines={3}>
                {item.subtitle}
              </Text>
            </View>
          ) : null}
          <View style={styles.actionsRow}>
            <Pressable
              style={[styles.actionButton, styles.rejectButton]}
              disabled={busyId === item.id}
              onPress={() => handleReject(item)}
            >
              <Text style={styles.rejectText}>Tolak</Text>
            </Pressable>
            <Pressable
              style={[styles.actionButton, styles.approveButton]}
              disabled={busyId === item.id}
              onPress={() => handleApprove(item)}
            >
              <Text style={styles.approveText}>{busyId === item.id ? "..." : "Setuju"}</Text>
            </Pressable>
          </View>
        </Card>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  container: { padding: spacing.lg, paddingTop: spacing.xxl, gap: spacing.lg, paddingBottom: spacing.xxl },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  backButton: {
    width: 36, height: 36, borderRadius: radius.md, backgroundColor: colors.bg.card,
    alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.bg.border,
  },
  brandRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  brandIcon: { width: 28, height: 28, borderRadius: radius.sm, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  brandText: { color: colors.text.primary, fontSize: 14, fontWeight: "800" },
  title: { color: colors.text.primary, fontSize: 22, fontWeight: "800" },
  subtitle: { color: colors.text.muted, fontSize: 12, marginTop: 2 },
  warningBanner: {
    flexDirection: "row", gap: spacing.sm, backgroundColor: colors.status.warningBg, borderWidth: 1,
    borderColor: "rgba(245,158,11,0.3)", borderRadius: radius.lg, padding: spacing.md,
  },
  warningTitle: { color: colors.status.warning, fontWeight: "700", fontSize: 13 },
  warningText: { color: colors.text.body, fontSize: 12, marginTop: 2 },
  itemCard: { gap: spacing.sm },
  itemHeaderRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  sourceIcon: {
    width: 28, height: 28, borderRadius: radius.sm, backgroundColor: "rgba(139,92,246,0.12)",
    alignItems: "center", justifyContent: "center",
  },
  itemTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700", flex: 1 },
  itemMeta: { color: colors.text.faint, fontSize: 11 },
  subtitleBox: { backgroundColor: colors.bg.cardAlt, borderRadius: radius.md, padding: spacing.md },
  subtitleText: { color: colors.text.body, fontSize: 12 },
  actionsRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  actionButton: { flex: 1, paddingVertical: spacing.sm + 2, borderRadius: radius.md, alignItems: "center" },
  rejectButton: { backgroundColor: colors.status.dangerBg, borderWidth: 1, borderColor: "rgba(244,63,94,0.3)" },
  rejectText: { color: colors.status.danger, fontWeight: "700", fontSize: 13 },
  approveButton: { backgroundColor: colors.status.success },
  approveText: { color: "#04120C", fontWeight: "700", fontSize: 13 },
});
