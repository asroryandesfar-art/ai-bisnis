import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { formatDate } from "../src/utils/format";

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}

const ACTION_TYPES = ["general", "hire", "price_change", "marketing", "finance", "hr", "sales", "operations", "security", "customer_support"];
const CASPER_STATUS_KIND: Record<string, BadgeKind> = { confirmed: "success", pending: "warning", failed: "danger", demo: "neutral" };

export default function CasperWorkflow() {
  const router = useRouter();
  const [stats, setStats] = useState<any>({});
  const [actions, setActions] = useState<any[]>([]);
  const [config, setConfig] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [actionType, setActionType] = useState("general");

  const load = useCallback(async () => {
    const [statsRes, actionsRes, cfgRes] = await Promise.allSettled([
      api.casperStats(), api.casperActions(20), api.casperConfig(),
    ]);
    setStats(statsRes.status === "fulfilled" ? statsRes.value : {});
    setActions(actionsRes.status === "fulfilled" ? actionsRes.value || [] : []);
    setConfig(cfgRes.status === "fulfilled" ? cfgRes.value : null);
    setLoading(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function runDemo() {
    setBusy("demo");
    try {
      await api.casperDemo();
      await load();
      Alert.alert("Berhasil", "Demo action berhasil di-anchor.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menjalankan demo.");
    } finally {
      setBusy(null);
    }
  }

  async function createAction() {
    if (!message.trim()) {
      Alert.alert("Lengkapi form", "Deskripsikan skenario/keputusan bisnisnya dulu.");
      return;
    }
    setBusy("create");
    try {
      const result = await api.casperCreateAction({ user_message: message.trim(), action_type: actionType, agent_name: "BotNesia Supervisor" });
      setFormOpen(false);
      setMessage("");
      await load();
      Alert.alert("Berhasil", result.casper_status === "confirmed" ? "Action ter-anchor di Casper Testnet." : "Action tercatat (demo mode).");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa membuat action.");
    } finally {
      setBusy(null);
    }
  }

  const demoMode = config?.env?.missing?.length > 0;

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Casper Workflow</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {loading ? <ActivityIndicator color={colors.brand.violet400} /> : (
          <>
            {config ? (
              <Card style={{ borderColor: demoMode ? colors.status.warning : colors.status.success, gap: 2 }}>
                <Text style={{ color: demoMode ? colors.status.warning : colors.status.success, fontSize: 12, fontWeight: "700" }}>
                  {demoMode ? "◎ Demo Mode Aktif" : "✓ Real Mode Aktif"}
                </Text>
                <Text style={styles.hint}>
                  {demoMode
                    ? "Proof berupa hash deterministik (bukan transaksi Casper sungguhan). Isi env CASPER_* di server untuk mode nyata."
                    : "Transaksi Casper Testnet aktif."}
                </Text>
              </Card>
            ) : null}

            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Total Actions</Text><Text style={styles.kpiValue}>{num(stats.total_actions)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Anchored On-Chain</Text><Text style={[styles.kpiValue, { color: colors.status.success }]}>{num(stats.anchored_on_chain)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Pending</Text><Text style={styles.kpiValue}>{num(stats.pending)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Failed</Text><Text style={[styles.kpiValue, (stats.failed || 0) > 0 && { color: colors.status.danger }]}>{num(stats.failed)}</Text></View>
            </View>

            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Pressable style={[styles.outlineBtnFlex, busy === "demo" && { opacity: 0.6 }]} onPress={runDemo} disabled={busy === "demo"}>
                {busy === "demo" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : <Text style={styles.outlineBtnText}>⚡ One-Click Demo</Text>}
              </Pressable>
              <Pressable style={styles.primaryBtnFlex} onPress={() => setFormOpen((v) => !v)}>
                <Text style={styles.primaryBtnText}>{formOpen ? "Batal" : "+ New Action"}</Text>
              </Pressable>
            </View>

            {formOpen ? (
              <Card style={{ gap: spacing.sm }}>
                <TextInput
                  style={[styles.input, { minHeight: 70, textAlignVertical: "top" }]}
                  value={message}
                  onChangeText={setMessage}
                  placeholder="Deskripsikan skenario/keputusan bisnis, mis. 'Saya perlu merekrut 3 sales executive baru...'"
                  placeholderTextColor={colors.text.muted}
                  multiline
                />
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
                  {ACTION_TYPES.map((t) => (
                    <Pressable key={t} onPress={() => setActionType(t)} style={[styles.pill, actionType === t && styles.pillActive]}>
                      <Text style={[styles.pillText, actionType === t && styles.pillTextActive]}>{t.replace(/_/g, " ")}</Text>
                    </Pressable>
                  ))}
                </ScrollView>
                {busy === "create" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                  <Pressable style={styles.primaryBtn} onPress={createAction}>
                    <Text style={styles.primaryBtnText}>Anchor to Casper</Text>
                  </Pressable>
                )}
              </Card>
            ) : null}

            <Text style={styles.sectionLabel}>RECENT AI ACTIONS ({actions.length})</Text>
            {actions.length === 0 ? (
              <Card><Text style={styles.emptyText}>Belum ada action. Jalankan One-Click Demo untuk mencatat keputusan bisnis AI pertama di Casper Testnet.</Text></Card>
            ) : (
              actions.map((a: any) => {
                const isDemoHash = String(a.deploy_hash || "").startsWith("demo-");
                return (
                  <Card key={a.action_id} style={{ gap: spacing.xs }}>
                    <View style={styles.rowBetween}>
                      <Badge label={(a.action_type || "").replace(/_/g, " ").toUpperCase()} kind="neutral" />
                      <Badge label={(a.casper_status || "").toUpperCase()} kind={CASPER_STATUS_KIND[a.casper_status] || "neutral"} />
                    </View>
                    <Text style={styles.itemTitle} numberOfLines={3}>{a.action_summary}</Text>
                    {a.deploy_hash ? (
                      <Text style={styles.hashText} numberOfLines={1}>
                        {isDemoHash ? `${a.deploy_hash.slice(0, 28)}…(demo)` : `${a.deploy_hash.slice(0, 32)}…`}
                      </Text>
                    ) : null}
                    <View style={styles.rowBetween}>
                      <Text style={styles.hint}>{formatDate(a.created_at)}</Text>
                      {a.explorer_url && !isDemoHash ? (
                        <Pressable onPress={() => Linking.openURL(a.explorer_url)}>
                          <Text style={styles.linkText}>View on cspr.live ↗</Text>
                        </Pressable>
                      ) : null}
                    </View>
                  </Card>
                );
              })
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

  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpiCard: { width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 2 },
  kpiLabel: { color: colors.text.faint, fontSize: 10 },
  kpiValue: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },

  pill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border },
  pillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  pillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700", textTransform: "capitalize" },
  pillTextActive: { color: "#fff" },

  input: {
    backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, color: colors.text.primary, fontSize: 13,
  },
  primaryBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  primaryBtnFlex: { flex: 1, backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  outlineBtnFlex: { flex: 1, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  outlineBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },

  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  itemTitle: { color: colors.text.primary, fontSize: 13, fontWeight: "700", lineHeight: 18 },
  hint: { color: colors.text.faint, fontSize: 10 },
  hashText: { color: colors.text.muted, fontSize: 10, fontFamily: "monospace" },
  linkText: { color: colors.brand.violet400, fontSize: 11, fontWeight: "700" },
  emptyText: { color: colors.text.muted, fontSize: 13, textAlign: "center" },
});
