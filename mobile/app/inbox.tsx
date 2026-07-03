import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

type Conversation = {
  id: string;
  end_user_name: string | null;
  end_user_email: string | null;
  msg_count: number;
  resolved: boolean;
  handoff_needed: boolean;
  rating: number | null;
  started_at: string;
  last_msg_at: string | null;
};

function initials(name: string) {
  return name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "AN";
}

function timeAgo(iso: string | null) {
  if (!iso) return "";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "baru saja";
  if (mins < 60) return `${mins} menit lalu`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h} jam lalu`;
  return `${Math.floor(h / 24)} hari lalu`;
}

export default function Inbox() {
  const router = useRouter();
  const [bots, setBots] = useState<{ id: string; name: string }[]>([]);
  const [botId, setBotId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<"all" | "handoff">("all");
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (targetBotId?: string | null) => {
    try {
      setError(null);
      const botsRes = await api.bots();
      const list = (botsRes as any[]).map((b) => ({ id: b.id, name: b.name }));
      setBots(list);
      const activeBotId = targetBotId ?? list[0]?.id ?? null;
      setBotId(activeBotId);
      if (!activeBotId) {
        setConversations([]);
        return;
      }
      const convs = await api.botConversations(activeBotId, { limit: 50 });
      setConversations(convs as Conversation[]);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat percakapan.");
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load(botId);
    }, [load, botId])
  );

  async function onRefresh() {
    setRefreshing(true);
    await load(botId);
    setRefreshing(false);
  }

  function switchBot(id: string) {
    setBotId(id);
    load(id);
  }

  const handoffCount = useMemo(() => conversations.filter((c) => c.handoff_needed).length, [conversations]);

  const filtered = useMemo(() => {
    return conversations.filter((c) => {
      if (tab === "handoff" && !c.handoff_needed) return false;
      if (query) {
        const name = (c.end_user_name || c.end_user_email || "").toLowerCase();
        if (!name.includes(query.toLowerCase())) return false;
      }
      return true;
    });
  }, [conversations, tab, query]);

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Inbox Percakapan</Text>
        <View style={{ width: 32 }} />
      </View>

      {bots.length > 1 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.botRow}>
          {bots.map((b) => (
            <Pressable key={b.id} onPress={() => switchBot(b.id)} style={[styles.botPill, botId === b.id && styles.botPillActive]}>
              <Text style={[styles.botPillText, botId === b.id && styles.botPillTextActive]} numberOfLines={1}>{b.name}</Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : null}

      <View style={styles.searchWrap}>
        <Ionicons name="search-outline" size={16} color={colors.text.muted} style={{ marginRight: spacing.sm }} />
        <TextInput
          placeholder="Cari nama/email pelanggan…"
          placeholderTextColor={colors.text.muted}
          value={query}
          onChangeText={setQuery}
          style={styles.searchInput}
        />
      </View>

      <View style={styles.tabRow}>
        <Pressable onPress={() => setTab("all")} style={[styles.tabPill, tab === "all" && styles.tabPillActive]}>
          <Text style={[styles.tabLabel, tab === "all" && styles.tabLabelActive]}>Semua ({conversations.length})</Text>
        </Pressable>
        {handoffCount > 0 ? (
          <Pressable onPress={() => setTab("handoff")} style={[styles.tabPill, tab === "handoff" && styles.tabPillActive]}>
            <Text style={[styles.tabLabel, tab === "handoff" && styles.tabLabelActive, tab !== "handoff" && { color: colors.status.warning }]}>
              Butuh Handoff ({handoffCount})
            </Text>
          </Pressable>
        ) : null}
      </View>

      <ScrollView
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
      >
        {error ? (
          <Card style={{ borderColor: colors.status.danger }}>
            <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
          </Card>
        ) : null}

        {!error && filtered.length === 0 ? (
          <Card>
            <Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>
              {conversations.length === 0 ? "Belum ada percakapan." : "Tidak ada percakapan yang cocok."}
            </Text>
          </Card>
        ) : null}

        {filtered.map((c) => {
          const name = c.end_user_name || c.end_user_email || "Anonim";
          return (
            <Pressable key={c.id} onPress={() => router.push({ pathname: "/conversation", params: { id: c.id, name } })}>
              <Card style={styles.convCard}>
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>{initials(name)}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.convName} numberOfLines={1}>{name}</Text>
                  <Text style={[styles.convState, c.handoff_needed && { color: colors.status.warning }]} numberOfLines={1}>
                    {c.handoff_needed ? "Butuh handoff" : "Ditangani AI"} · {c.msg_count} pesan
                  </Text>
                </View>
                <Text style={styles.convTime}>{timeAgo(c.last_msg_at || c.started_at)}</Text>
              </Card>
            </Pressable>
          );
        })}
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

  botRow: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  botPill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  botPillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  botPillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  botPillTextActive: { color: "#fff" },

  searchWrap: {
    flexDirection: "row", alignItems: "center", backgroundColor: colors.bg.card, marginHorizontal: spacing.lg,
    marginTop: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, paddingHorizontal: spacing.md,
  },
  searchInput: { flex: 1, color: colors.text.primary, fontSize: 13, paddingVertical: spacing.md },

  tabRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, marginTop: spacing.md },
  tabPill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  tabPillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  tabLabel: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  tabLabelActive: { color: "#fff" },

  list: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  convCard: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  avatar: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#fff", fontWeight: "800", fontSize: 13 },
  convName: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  convState: { color: colors.text.muted, fontSize: 12, marginTop: 2 },
  convTime: { color: colors.text.faint, fontSize: 11 },
});
