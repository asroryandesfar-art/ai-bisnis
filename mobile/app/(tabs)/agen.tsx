import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge } from "../../src/components/Badge";
import { Card } from "../../src/components/Card";
import { api } from "../../src/api/client";
import { colors } from "../../src/theme/colors";
import { radius, spacing } from "../../src/theme/spacing";

type Bot = {
  id: string;
  name: string;
  status: "active" | "inactive" | "training";
  primary_color: string | null;
  greeting: string | null;
  total_convs: number;
  total_msgs: number;
};

// "Error" has no real backend equivalent (bots only have active/inactive/
// training) -- kept as a filter pill to match the reference design, but it
// honestly always shows empty rather than being mapped to a fake status.
const FILTERS = [
  { key: "all", label: "Semua" },
  { key: "active", label: "Aktif" },
  { key: "inactive", label: "Jeda" },
  { key: "error", label: "Error" },
] as const;

function initials(name: string) {
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export default function Agen() {
  const router = useRouter();
  const [bots, setBots] = useState<Bot[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await api.bots();
      setBots(data as Bot[]);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat daftar agen.");
    }
  }, []);

  // Reload every time the screen regains focus -- so returning from the agent
  // editor (create/edit) shows fresh data without a manual pull-to-refresh.
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

  const filtered = useMemo(() => {
    return bots.filter((b) => {
      if (filter === "error") return false; // no real error status -- see note above
      if (filter !== "all" && b.status !== filter) return false;
      if (query && !b.name.toLowerCase().includes(query.toLowerCase())) return false;
      return true;
    });
  }, [bots, filter, query]);

  const activeCount = bots.filter((b) => b.status === "active").length;

  return (
    <View style={styles.flex}>
      <View style={styles.header}>
        <View>
          <Text style={styles.title}>Agen AI</Text>
          <Text style={styles.subtitle}>
            {bots.length} agen terdaftar · {activeCount} aktif
          </Text>
        </View>
        <Pressable style={styles.addButton} onPress={() => router.push("/agent-editor")}>
          <Ionicons name="add" size={22} color="#fff" />
        </Pressable>
      </View>

      <View style={styles.searchWrap}>
        <Ionicons name="search-outline" size={16} color={colors.text.muted} style={{ marginRight: spacing.sm }} />
        <TextInput
          placeholder="Cari agen AI..."
          placeholderTextColor={colors.text.muted}
          value={query}
          onChangeText={setQuery}
          style={styles.searchInput}
        />
      </View>

      <View style={styles.filterRow}>
        {FILTERS.map((f) => (
          <Pressable
            key={f.key}
            onPress={() => setFilter(f.key)}
            style={[styles.filterPill, filter === f.key && styles.filterPillActive]}
          >
            <Text style={[styles.filterLabel, filter === f.key && styles.filterLabelActive]}>{f.label}</Text>
          </Pressable>
        ))}
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
              {bots.length === 0 ? "Belum ada agen." : "Tidak ada agen yang cocok."}
            </Text>
          </Card>
        ) : null}

        {filtered.map((bot) => (
          <Pressable key={bot.id} onPress={() => router.push({ pathname: "/agent-editor", params: { id: bot.id } })}>
          <Card style={styles.agentCard}>
            <View style={styles.agentRow}>
              <View style={[styles.avatar, { backgroundColor: bot.primary_color || colors.brand.violet600 }]}>
                <Text style={styles.avatarText}>{initials(bot.name)}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <View style={styles.agentNameRow}>
                  <Text style={styles.agentName} numberOfLines={1}>
                    {bot.name}
                  </Text>
                  <Badge
                    label={bot.status === "active" ? "AKTIF" : bot.status === "training" ? "TRAINING" : "JEDA"}
                    kind={bot.status === "active" ? "success" : bot.status === "training" ? "warning" : "neutral"}
                  />
                </View>
                {bot.greeting ? (
                  <Text style={styles.agentGreeting} numberOfLines={1}>
                    {bot.greeting}
                  </Text>
                ) : null}
              </View>
            </View>
            <View style={styles.statsRow}>
              <View style={styles.statItem}>
                <Text style={styles.statLabel}>Percakapan</Text>
                <Text style={styles.statValue}>{bot.total_convs}</Text>
              </View>
              <View style={styles.statItem}>
                <Text style={styles.statLabel}>Pesan</Text>
                <Text style={styles.statValue}>{bot.total_msgs}</Text>
              </View>
              <Pressable
                style={styles.chatBtn}
                onPress={() => router.push({ pathname: "/chat", params: { botId: bot.id } })}
                hitSlop={8}
              >
                <MaterialCommunityIcons name="chat-outline" size={16} color={colors.brand.violet400} />
                <Text style={styles.chatBtnText}>Chat</Text>
              </Pressable>
              <MaterialCommunityIcons name="chevron-right" size={20} color={colors.text.faint} />
            </View>
          </Card>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  header: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start",
    padding: spacing.lg, paddingTop: spacing.xl,
  },
  title: { color: colors.text.primary, fontSize: 22, fontWeight: "800" },
  subtitle: { color: colors.text.muted, fontSize: 12, marginTop: 2 },
  addButton: {
    width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brand.violet600,
    alignItems: "center", justifyContent: "center",
  },
  searchWrap: {
    flexDirection: "row", alignItems: "center", backgroundColor: colors.bg.card, marginHorizontal: spacing.lg,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, paddingHorizontal: spacing.md,
  },
  searchInput: { flex: 1, color: colors.text.primary, fontSize: 13, paddingVertical: spacing.md },
  filterRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, marginTop: spacing.md },
  filterPill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  filterPillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  filterLabel: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  filterLabelActive: { color: "#fff" },
  list: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  agentCard: { gap: spacing.md },
  agentRow: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  avatar: { width: 44, height: 44, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  agentNameRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  agentName: { color: colors.text.primary, fontSize: 15, fontWeight: "700", flexShrink: 1 },
  agentGreeting: { color: colors.text.muted, fontSize: 12, marginTop: 2 },
  statsRow: { flexDirection: "row", alignItems: "center", gap: spacing.xl, borderTopWidth: 1, borderTopColor: colors.bg.border, paddingTop: spacing.md },
  chatBtn: { flexDirection: "row", alignItems: "center", gap: 4, marginLeft: "auto", paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, borderWidth: 1, borderColor: colors.bg.border },
  chatBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },
  statItem: { gap: 2 },
  statLabel: { color: colors.text.faint, fontSize: 10 },
  statValue: { color: colors.text.body, fontSize: 13, fontWeight: "700" },
});
