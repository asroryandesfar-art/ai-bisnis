import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { formatDate } from "../src/utils/format";

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}

type Template = {
  key: string; name: string; category: string; description: string; icon: string;
  primary_color: string | null; rating: number; install_count: number; version: string;
  tools: string[]; starter_questions: string[]; featured: boolean;
};
type Install = { id: string; template_key: string; template_name: string; template_category: string; template_version: string; bot_id: string; bot_name: string; bot_status: string; installed_at: string };

export default function Marketplace() {
  const router = useRouter();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [installs, setInstalls] = useState<Install[]>([]);
  const [categories, setCategories] = useState<any[]>([]);
  const [analytics, setAnalytics] = useState<any>({});
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("");
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [installOpenKey, setInstallOpenKey] = useState<string | null>(null);
  const [installBotName, setInstallBotName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [tRes, iRes, cRes, aRes] = await Promise.allSettled([
        api.marketplaceTemplates(), api.marketplaceInstalls(), api.marketplaceCategories(), api.marketplaceAnalytics(),
      ]);
      setTemplates(tRes.status === "fulfilled" ? tRes.value.templates || [] : []);
      setInstalls(iRes.status === "fulfilled" ? iRes.value.installs || [] : []);
      setCategories(cRes.status === "fulfilled" ? cRes.value.categories || [] : []);
      setAnalytics(aRes.status === "fulfilled" ? aRes.value : {});
      if (tRes.status === "rejected") setError((tRes as any).reason?.message || "Gagal memuat marketplace.");
    } catch (e: any) {
      setError(e?.message || "Gagal memuat marketplace.");
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

  const installedByKey = useMemo(() => new Map(installs.map((i) => [i.template_key, i])), [installs]);

  const featured = useMemo(() => templates.filter((t) => t.featured).slice(0, 8), [templates]);

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    return templates.filter((t) => {
      if (category && t.category !== category) return false;
      if (!q) return true;
      return `${t.name} ${t.category} ${t.description}`.toLowerCase().includes(q);
    });
  }, [templates, query, category]);

  async function install(key: string) {
    setBusy(key);
    try {
      await api.installMarketplaceTemplate(key, installBotName.trim() || null);
      setInstallOpenKey(null);
      setInstallBotName("");
      await load();
      Alert.alert("Berhasil", "Agent berhasil diinstall.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menginstall agent ini (mungkin limit paket tercapai).");
    } finally {
      setBusy(null);
    }
  }

  function uninstall(inst: Install) {
    Alert.alert("Uninstall agent?", inst.template_name, [
      { text: "Batal", style: "cancel" },
      {
        text: "Uninstall", style: "destructive",
        onPress: async () => {
          setBusy(inst.id);
          try {
            await api.uninstallMarketplaceInstall(inst.id);
            await load();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa uninstall agent ini.");
          } finally {
            setBusy(null);
          }
        },
      },
    ]);
  }

  function TemplateCard({ t }: { t: Template }) {
    const inst = installedByKey.get(t.key);
    const installOpen = installOpenKey === t.key;
    return (
      <Card style={[styles.tplCard, { borderColor: t.primary_color || colors.bg.border }]}>
        <View style={styles.tplHead}>
          <View style={[styles.tplIcon, { backgroundColor: (t.primary_color || colors.brand.violet600) + "22" }]}>
            <MaterialCommunityIcons name="robot-outline" size={18} color={t.primary_color || colors.brand.violet400} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.tplName} numberOfLines={1}>{t.name}</Text>
            <Text style={styles.tplCategory}>{t.category}</Text>
          </View>
        </View>
        <Text style={styles.tplDesc} numberOfLines={3}>{t.description}</Text>
        <View style={styles.tplMetaRow}>
          <View style={styles.tplRatingRow}>
            <Ionicons name="star-outline" size={11} color={colors.text.faint} />
            <Text style={styles.tplMeta}>{t.rating.toFixed(1)}</Text>
          </View>
          <Text style={styles.tplMeta}>{num(t.install_count)} installs</Text>
          <Text style={styles.tplMeta}>v{t.version}</Text>
        </View>
        {inst ? (
          <View style={{ gap: spacing.sm }}>
            <Badge label={`TERPASANG · ${inst.bot_name}`} kind="success" />
            {busy === inst.id ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
              <Pressable style={styles.dangerBtn} onPress={() => uninstall(inst)}>
                <Text style={styles.dangerBtnText}>Uninstall</Text>
              </Pressable>
            )}
          </View>
        ) : (
          <View style={{ gap: spacing.sm }}>
            <Pressable style={styles.primaryBtn} onPress={() => { setInstallOpenKey(installOpen ? null : t.key); setInstallBotName(t.name); }}>
              <Text style={styles.primaryBtnText}>{installOpen ? "Batal" : "Install"}</Text>
            </Pressable>
            {installOpen ? (
              <View style={{ gap: spacing.sm }}>
                <TextInput style={styles.input} value={installBotName} onChangeText={setInstallBotName} placeholder="Nama agen" placeholderTextColor={colors.text.muted} />
                {busy === t.key ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                  <Pressable style={styles.primaryBtn} onPress={() => install(t.key)}>
                    <Text style={styles.primaryBtnText}>Konfirmasi Install</Text>
                  </Pressable>
                )}
              </View>
            ) : null}
          </View>
        )}
      </Card>
    );
  }

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Agent Marketplace</Text>
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
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Templates</Text><Text style={styles.kpiValue}>{num(analytics.template_count ?? templates.length)}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Terpasang</Text><Text style={styles.kpiValue}>{num(analytics.installed_count ?? installs.length)}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Avg Rating</Text><Text style={styles.kpiValue}>{Number(analytics.average_rating || 0).toFixed(2)}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Total Installs</Text><Text style={styles.kpiValue}>{num(analytics.total_install_count)}</Text></View>
        </View>

        <View style={styles.searchWrap}>
          <Ionicons name="search-outline" size={16} color={colors.text.muted} style={{ marginRight: spacing.sm }} />
          <TextInput
            placeholder="Cari agent…"
            placeholderTextColor={colors.text.muted}
            value={query}
            onChangeText={setQuery}
            style={styles.searchInput}
          />
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterRow}>
          <Pressable onPress={() => setCategory("")} style={[styles.pill, category === "" && styles.pillActive]}>
            <Text style={[styles.pillText, category === "" && styles.pillTextActive]}>Semua ({templates.length})</Text>
          </Pressable>
          {categories.map((c) => (
            <Pressable key={c.key || c.name} onPress={() => setCategory(c.name)} style={[styles.pill, category === c.name && styles.pillActive]}>
              <Text style={[styles.pillText, category === c.name && styles.pillTextActive]}>{c.name} ({c.template_count})</Text>
            </Pressable>
          ))}
        </ScrollView>

        {featured.length > 0 && !category && !query ? (
          <>
            <Text style={styles.sectionLabel}>FEATURED</Text>
            {featured.map((t) => <TemplateCard key={t.key} t={t} />)}
          </>
        ) : null}

        <Text style={styles.sectionLabel}>KATALOG ({filtered.length})</Text>
        {filtered.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Tidak ada agent yang cocok.</Text></Card>
        ) : (
          filtered.map((t) => <TemplateCard key={t.key} t={t} />)
        )}

        <Text style={styles.sectionLabel}>AGENT TERPASANG ({installs.length})</Text>
        {installs.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada agent terpasang.</Text></Card>
        ) : (
          installs.map((inst) => (
            <Card key={inst.id} style={styles.installCard}>
              <View style={{ flex: 1 }}>
                <Text style={styles.tplName} numberOfLines={1}>{inst.template_name}</Text>
                <Text style={styles.tplCategory}>{inst.bot_name} · {formatDate(inst.installed_at)}</Text>
              </View>
              <Badge label={(inst.bot_status || "inactive").toUpperCase()} kind={inst.bot_status === "active" ? "success" : "neutral"} />
            </Card>
          ))
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

  searchWrap: {
    flexDirection: "row", alignItems: "center", backgroundColor: colors.bg.card,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, paddingHorizontal: spacing.md,
  },
  searchInput: { flex: 1, color: colors.text.primary, fontSize: 13, paddingVertical: spacing.md },
  filterRow: { gap: spacing.sm, paddingVertical: spacing.xs },
  pill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  pillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  pillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  pillTextActive: { color: "#fff" },

  tplCard: { gap: spacing.sm, borderWidth: 1 },
  tplHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  tplIcon: { width: 36, height: 36, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  tplName: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  tplCategory: { color: colors.text.faint, fontSize: 11, marginTop: 1 },
  tplDesc: { color: colors.text.muted, fontSize: 12, lineHeight: 17 },
  tplMetaRow: { flexDirection: "row", gap: spacing.md },
  tplRatingRow: { flexDirection: "row", alignItems: "center", gap: 3 },
  tplMeta: { color: colors.text.faint, fontSize: 11 },

  input: {
    backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, color: colors.text.primary, fontSize: 13,
  },
  primaryBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  dangerBtn: { borderWidth: 1, borderColor: colors.status.danger, backgroundColor: colors.status.dangerBg, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  dangerBtnText: { color: colors.status.danger, fontSize: 12, fontWeight: "700" },

  installCard: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
});
