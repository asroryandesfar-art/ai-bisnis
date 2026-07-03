import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge } from "../../src/components/Badge";
import { Card } from "../../src/components/Card";
import { ScreenHeader } from "../../src/components/ScreenHeader";
import { api } from "../../src/api/client";
import { colors } from "../../src/theme/colors";
import { radius, spacing } from "../../src/theme/spacing";
import { formatDate, idr } from "../../src/utils/format";

// Flip to true (or delete the banner) once Midtrans finishes the merchant
// business review and real payment channels are live -- mirrors the web's
// MIDTRANS_GATEWAY_APPROVED honesty flag.
const MIDTRANS_GATEWAY_APPROVED = false;

const PLAN_ORDER = ["free", "starter", "pro", "business", "enterprise"];

const USAGE_DIMS: { key: string; label: string; icon: keyof typeof MaterialCommunityIcons.glyphMap }[] = [
  { key: "agents", label: "Agen AI", icon: "robot-outline" },
  { key: "conversations", label: "Percakapan", icon: "chat-outline" },
  { key: "knowledge", label: "Knowledge Base", icon: "book-outline" },
  { key: "channels", label: "Channel", icon: "connection" },
  { key: "users", label: "Pengguna Tim", icon: "account-group-outline" },
  { key: "image_generations", label: "Generate Gambar", icon: "image-outline" },
];

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}
function limitText(v: any): string {
  return v === -1 ? "Tak terbatas" : num(v);
}

function planFeatures(plan: any): string[] {
  return [
    `${plan.max_agents === -1 ? "Tak terbatas" : plan.max_agents} Agen AI`,
    `${limitText(plan.max_conversations_per_month)} percakapan/bln`,
    plan.max_knowledge_docs != null ? `${limitText(plan.max_knowledge_docs)} dokumen knowledge` : null,
    plan.max_channels != null ? `${limitText(plan.max_channels)} channel` : null,
  ].filter(Boolean) as string[];
}

export default function Billing() {
  const [subscription, setSubscription] = useState<any>(null);
  const [usage, setUsage] = useState<Record<string, number>>({});
  const [limits, setLimits] = useState<Record<string, number>>({});
  const [plans, setPlans] = useState<any[]>([]);
  const [invoices, setInvoices] = useState<any[]>([]);
  const [credits, setCredits] = useState<any>({ addon_conversation_balance: 0, topup_packages: [], history: [] });
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [subRes, plansRes, invRes, credRes] = await Promise.allSettled([
        api.billingSubscription(),
        api.billingPlans(),
        api.invoices(),
        api.credits(),
      ]);
      if (subRes.status === "fulfilled") {
        setSubscription((subRes.value as any).subscription);
        setUsage((subRes.value as any).usage || {});
        setLimits((subRes.value as any).limits || {});
      }
      if (plansRes.status === "fulfilled") setPlans((plansRes.value as any).plans || []);
      if (invRes.status === "fulfilled") setInvoices((invRes.value as any).invoices || []);
      if (credRes.status === "fulfilled") setCredits(credRes.value);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat data billing.");
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

  async function openRedirect(fn: () => Promise<{ redirect_url?: string }>, key: string, okMsg: string) {
    setBusy(key);
    try {
      const result = await fn();
      if (result.redirect_url) {
        await Linking.openURL(result.redirect_url);
      } else {
        Alert.alert("Berhasil", okMsg);
        await load();
      }
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Transaksi gagal, coba lagi.");
    } finally {
      setBusy(null);
    }
  }

  function checkout(planKey: string, planName: string, useTrial: boolean) {
    if (planKey === "enterprise") {
      Alert.alert("Enterprise", "Paket Enterprise memakai harga khusus. Hubungi tim sales BotNesia untuk penawaran.");
      return;
    }
    Alert.alert(
      useTrial ? `Coba gratis ${planName}?` : `Pilih paket ${planName}?`,
      "Anda akan diarahkan ke pembayaran Midtrans di browser (jika perlu bayar).",
      [
        { text: "Batal", style: "cancel" },
        {
          text: "Lanjutkan",
          onPress: () => openRedirect(() => api.billingCheckout(planKey, "monthly", useTrial), `plan:${planKey}`, "Paket aktif tanpa pembayaran tambahan."),
        },
      ]
    );
  }

  function topup(amountIdr: number) {
    Alert.alert("Top Up Kredit", `Beli kredit percakapan senilai ${idr(amountIdr)}?`, [
      { text: "Batal", style: "cancel" },
      { text: "Lanjutkan", onPress: () => openRedirect(() => api.topupCredits(amountIdr), `topup:${amountIdr}`, "Kredit berhasil ditambahkan.") },
    ]);
  }

  const currentKey = subscription?.plan_key || "free";
  const isTrial = subscription?.is_free_trial || subscription?.status === "trialing";
  const sortedPlans = [...plans].sort((a, b) => PLAN_ORDER.indexOf(a.key) - PLAN_ORDER.indexOf(b.key));
  const addonBalance = Number(credits?.addon_conversation_balance ?? credits?.balance ?? 0);
  const topupPackages: any[] = credits?.topup_packages?.length
    ? credits.topup_packages
    : [
        { amount_idr: 25000, conversations: 1000, label: "Rp25.000" },
        { amount_idr: 50000, conversations: 2500, label: "Rp50.000" },
        { amount_idr: 100000, conversations: 5000, label: "Rp100.000" },
        { amount_idr: 250000, conversations: 15000, label: "Rp250.000" },
      ];

  return (
    <View style={styles.flex}>
      <ScreenHeader title="Billing & Langganan" subtitle="Kelola paket, kredit, dan pembayaran" />
      <ScrollView
        style={styles.flex}
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
      >
      {error ? (
        <Card style={{ borderColor: colors.status.danger }}>
          <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
        </Card>
      ) : null}

      {!MIDTRANS_GATEWAY_APPROVED ? (
        <Card style={styles.gatewayBanner}>
          <Text style={styles.gatewayIcon}>⏳</Text>
          <View style={{ flex: 1 }}>
            <Text style={styles.gatewayTitle}>Pembayaran menunggu approval</Text>
            <Text style={styles.gatewaySub}>Channel pembayaran Midtrans masih dalam proses review bisnis. Checkout mungkin belum bisa diproses.</Text>
          </View>
        </Card>
      ) : null}

      {subscription ? (
        <Card style={styles.planCard}>
          <View style={styles.planHeaderRow}>
            <Text style={styles.planLabel}>Paket Aktif</Text>
            <Badge label={(isTrial ? "TRIAL" : subscription.status || "active").toUpperCase()} kind={isTrial ? "warning" : subscription.status === "active" ? "success" : "warning"} />
          </View>
          <Text style={styles.planName}>{subscription.plan_name}</Text>
          <Text style={styles.planPrice}>
            {idr(subscription.billing_cycle === "yearly" ? subscription.price_yearly_idr : subscription.price_monthly_idr)}
            <Text style={styles.planPricePer}> /{subscription.billing_cycle === "yearly" ? "tahun" : "bulan"}</Text>
          </Text>
          <View style={styles.planStatsRow}>
            <View style={styles.planStatItem}>
              <Text style={styles.planStatValue}>{limitText(limits.agents)}</Text>
              <Text style={styles.planStatLabel}>Agen AI</Text>
            </View>
            <View style={styles.planStatItem}>
              <Text style={styles.planStatValue}>{limitText(limits.conversations)}</Text>
              <Text style={styles.planStatLabel}>Percakapan/bln</Text>
            </View>
            <View style={styles.planStatItem}>
              <Text style={styles.planStatValue}>{limitText(limits.knowledge)}</Text>
              <Text style={styles.planStatLabel}>Knowledge Base</Text>
            </View>
          </View>
          {subscription.current_period_end ? (
            <Text style={styles.renewText}>Perpanjang otomatis: {formatDate(subscription.current_period_end)}</Text>
          ) : null}
        </Card>
      ) : null}

      {/* Usage */}
      <Text style={styles.sectionLabel}>PENGGUNAAN BULAN INI</Text>
      <Card style={{ gap: spacing.lg }}>
        {USAGE_DIMS.map((dim) => {
          const used = usage[dim.key] ?? 0;
          const limit = limits[dim.key] ?? 0;
          const unlimited = limit === -1;
          const pct = unlimited || limit === 0 ? 0 : Math.min(100, (used / limit) * 100);
          const over = !unlimited && limit > 0 && used >= limit;
          return (
            <View key={dim.key} style={{ gap: spacing.xs }}>
              <View style={styles.usageRow}>
                <Text style={styles.usageLabel}>{dim.label}</Text>
                <Text style={[styles.usageValue, over && { color: colors.status.danger }]}>{used} / {unlimited ? "∞" : limit}</Text>
              </View>
              <View style={styles.progressTrack}>
                <View style={[styles.progressFill, over && { backgroundColor: colors.status.danger }, { width: `${pct}%` }]} />
              </View>
            </View>
          );
        })}
      </Card>

      {/* Plan comparison */}
      <Text style={styles.sectionLabel}>PILIH PAKET</Text>
      <View style={{ gap: spacing.md }}>
        {sortedPlans.map((plan) => {
          const isCurrent = plan.key === currentKey;
          const isPopular = plan.key === "pro";
          const isEnterprise = plan.key === "enterprise";
          const hasTrial = !!plan.free_trial_eligible && !isCurrent && !isEnterprise;
          const key = `plan:${plan.key}`;
          return (
            <Card key={plan.key} style={[styles.optCard, isCurrent && styles.optCardCurrent, isPopular && !isCurrent && styles.optCardPopular]}>
              <View style={styles.optHead}>
                <View style={{ flex: 1 }}>
                  <View style={styles.optNameRow}>
                    <Text style={styles.optName}>{plan.name}</Text>
                    {isCurrent ? <Badge label="AKTIF" kind="success" /> : isPopular ? <Badge label="POPULER" kind="warning" /> : null}
                  </View>
                  <Text style={styles.optPrice}>
                    {isEnterprise ? "Harga khusus" : idr(plan.price_monthly_idr)}
                    {!isEnterprise ? <Text style={styles.optPricePer}> /bln</Text> : null}
                  </Text>
                </View>
              </View>
              <View style={styles.featureList}>
                {planFeatures(plan).map((f) => (
                  <View key={f} style={styles.featureRow}>
                    <MaterialCommunityIcons name="check" size={14} color={colors.status.success} />
                    <Text style={styles.featureText}>{f}</Text>
                  </View>
                ))}
              </View>
              {isCurrent ? (
                <View style={[styles.optBtn, styles.optBtnDisabled]}>
                  <Text style={styles.optBtnDisabledText}>Paket Aktif</Text>
                </View>
              ) : (
                <Pressable
                  style={[styles.optBtn, hasTrial ? styles.optBtnTrial : styles.optBtnPrimary]}
                  disabled={busy === key}
                  onPress={() => checkout(plan.key, plan.name, hasTrial)}
                >
                  <Text style={styles.optBtnText}>
                    {busy === key ? "..." : isEnterprise ? "Hubungi Sales" : hasTrial ? "Coba Gratis" : "Pilih Paket"}
                  </Text>
                </Pressable>
              )}
            </Card>
          );
        })}
      </View>

      {/* Credits & top-up */}
      <Text style={styles.sectionLabel}>KREDIT PERCAKAPAN</Text>
      <Card style={{ gap: spacing.md }}>
        <View>
          <Text style={styles.creditBalance}>{num(addonBalance)}</Text>
          <Text style={styles.creditUnit}>kredit percakapan tersisa</Text>
        </View>
        <Text style={styles.creditHint}>Kredit tambahan dipakai otomatis saat kuota paket bulanan habis.</Text>
        <View style={styles.topupGrid}>
          {topupPackages.map((pkg) => (
            <Pressable key={pkg.amount_idr} style={styles.topupBtn} disabled={busy === `topup:${pkg.amount_idr}`} onPress={() => topup(pkg.amount_idr)}>
              <Text style={styles.topupLabel}>{pkg.label || idr(pkg.amount_idr)}</Text>
              <Text style={styles.topupConv}>+{num(pkg.conversations)} percakapan</Text>
            </Pressable>
          ))}
        </View>
      </Card>

      {/* Invoices */}
      <Text style={styles.sectionLabel}>RIWAYAT INVOICE</Text>
      <Card style={{ padding: invoices.length ? 0 : spacing.lg }}>
        {invoices.length === 0 ? (
          <Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada invoice.</Text>
        ) : (
          invoices.map((inv, i) => (
            <View key={inv.id || inv.invoice_number || i} style={[styles.invRow, i > 0 && styles.invRowBorder]}>
              <View style={{ flex: 1 }}>
                <Text style={styles.invNumber}>{inv.invoice_number}</Text>
                <Text style={styles.invDesc} numberOfLines={1}>{inv.description || "Subscription"} · {formatDate(inv.created_at)}</Text>
              </View>
              <View style={{ alignItems: "flex-end", gap: 4 }}>
                <Text style={styles.invAmount}>{idr(inv.amount_idr)}</Text>
                <Badge
                  label={(inv.status || "").toUpperCase()}
                  kind={inv.status === "paid" ? "success" : inv.status === "open" || inv.status === "draft" ? "warning" : "danger"}
                />
              </View>
            </View>
          ))
        )}
      </Card>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  container: { padding: spacing.lg, paddingTop: 0, gap: spacing.lg, paddingBottom: spacing.xxl },

  gatewayBanner: { flexDirection: "row", gap: spacing.md, alignItems: "flex-start", backgroundColor: colors.status.warningBg, borderColor: colors.status.warning },
  gatewayIcon: { fontSize: 18 },
  gatewayTitle: { color: colors.status.warning, fontSize: 13, fontWeight: "800" },
  gatewaySub: { color: colors.text.body, fontSize: 11, marginTop: 2, lineHeight: 16 },

  planCard: { gap: spacing.xs },
  planHeaderRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  planLabel: { color: colors.text.muted, fontSize: 12 },
  planName: { color: colors.text.primary, fontSize: 22, fontWeight: "800", marginTop: 2 },
  planPrice: { color: colors.brand.violet400, fontSize: 20, fontWeight: "800", marginTop: spacing.xs },
  planPricePer: { color: colors.text.muted, fontSize: 12, fontWeight: "500" },
  planStatsRow: { flexDirection: "row", gap: spacing.lg, marginTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.bg.border, paddingTop: spacing.md },
  planStatItem: { gap: 1 },
  planStatValue: { color: colors.text.primary, fontSize: 15, fontWeight: "800" },
  planStatLabel: { color: colors.text.faint, fontSize: 10 },
  renewText: { color: colors.text.faint, fontSize: 11, marginTop: spacing.sm },

  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  usageRow: { flexDirection: "row", justifyContent: "space-between" },
  usageLabel: { color: colors.text.body, fontSize: 13 },
  usageValue: { color: colors.text.muted, fontSize: 12 },
  progressTrack: { height: 6, borderRadius: 3, backgroundColor: colors.bg.border, overflow: "hidden" },
  progressFill: { height: "100%", backgroundColor: colors.brand.violet500, borderRadius: 3 },

  optCard: { gap: spacing.md },
  optCardCurrent: { borderColor: colors.status.success },
  optCardPopular: { borderColor: colors.brand.violet500 },
  optHead: { flexDirection: "row", alignItems: "center" },
  optNameRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  optName: { color: colors.text.primary, fontSize: 17, fontWeight: "800" },
  optPrice: { color: colors.brand.violet400, fontSize: 18, fontWeight: "800", marginTop: 2 },
  optPricePer: { color: colors.text.muted, fontSize: 12, fontWeight: "500" },
  featureList: { gap: spacing.sm },
  featureRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  featureText: { color: colors.text.body, fontSize: 13 },
  optBtn: { paddingVertical: spacing.md, borderRadius: radius.md, alignItems: "center" },
  optBtnPrimary: { backgroundColor: colors.brand.violet600 },
  optBtnTrial: { backgroundColor: colors.brand.indigo600 },
  optBtnText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  optBtnDisabled: { backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border },
  optBtnDisabledText: { color: colors.text.muted, fontWeight: "700", fontSize: 13 },

  creditBalance: { color: colors.status.success, fontSize: 34, fontWeight: "800" },
  creditUnit: { color: colors.text.muted, fontSize: 12 },
  creditHint: { color: colors.text.muted, fontSize: 11, lineHeight: 16 },
  topupGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  topupBtn: {
    width: "48.5%", backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border,
    borderRadius: radius.md, padding: spacing.md, alignItems: "center", gap: 2,
  },
  topupLabel: { color: colors.text.primary, fontSize: 14, fontWeight: "800" },
  topupConv: { color: colors.status.success, fontSize: 11 },

  invRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md },
  invRowBorder: { borderTopWidth: 1, borderTopColor: colors.bg.border },
  invNumber: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  invDesc: { color: colors.text.muted, fontSize: 11, marginTop: 2 },
  invAmount: { color: colors.text.body, fontSize: 13, fontWeight: "700" },
});
