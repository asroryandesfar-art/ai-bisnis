import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { formatDate } from "../src/utils/format";

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}

const CONTENT_STATUS_KIND: Record<string, BadgeKind> = {
  draft: "neutral", ready_to_publish: "warning", scheduled: "warning", published: "success", cancelled: "neutral",
};
const PLATFORMS = ["instagram", "tiktok", "facebook", "blog", "email", "whatsapp"];

export default function MarketingCenter() {
  const router = useRouter();
  const [dash, setDash] = useState<any>({});
  const [content, setContent] = useState<any[]>([]);
  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [campaignFormOpen, setCampaignFormOpen] = useState(false);
  const [campaignName, setCampaignName] = useState("");
  const [campaignGoal, setCampaignGoal] = useState("");
  const [contentFormOpen, setContentFormOpen] = useState(false);
  const [platform, setPlatform] = useState("instagram");
  const [brief, setBrief] = useState("");

  const load = useCallback(async () => {
    try {
      setError(null);
      const [dashRes, contentRes, campRes] = await Promise.allSettled([
        api.marketingDashboard(), api.marketingContent(50), api.marketingCampaigns(50),
      ]);
      setDash(dashRes.status === "fulfilled" ? dashRes.value : {});
      setContent(contentRes.status === "fulfilled" ? contentRes.value.content || [] : []);
      setCampaigns(campRes.status === "fulfilled" ? campRes.value.campaigns || [] : []);
      if (dashRes.status === "rejected") setError((dashRes as any).reason?.message || "Gagal memuat Marketing Center.");
    } catch (e: any) {
      setError(e?.message || "Gagal memuat Marketing Center.");
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function createCampaign() {
    if (!campaignName.trim()) {
      Alert.alert("Lengkapi form", "Nama campaign wajib diisi.");
      return;
    }
    setBusy("new-campaign");
    try {
      await api.marketingCreateCampaign({ name: campaignName.trim(), goal: campaignGoal.trim() || null });
      setCampaignFormOpen(false); setCampaignName(""); setCampaignGoal("");
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa membuat campaign.");
    } finally {
      setBusy(null);
    }
  }

  async function generateContent() {
    if (!brief.trim()) {
      Alert.alert("Lengkapi form", "Brief konten wajib diisi.");
      return;
    }
    setBusy("gen-content");
    try {
      await api.marketingGenerateContent({ platform, brief: brief.trim() });
      setContentFormOpen(false); setBrief("");
      await load();
      Alert.alert("Berhasil", "Konten berhasil digenerate AI.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa generate konten.");
    } finally {
      setBusy(null);
    }
  }

  async function approveContent(id: string) {
    setBusy(id);
    try {
      await api.marketingApproveContent(id);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa approve konten ini.");
    } finally {
      setBusy(null);
    }
  }

  async function publishContent(id: string) {
    setBusy(id);
    try {
      await api.marketingPublishContent(id);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menandai published.");
    } finally {
      setBusy(null);
    }
  }

  function cancelContent(id: string) {
    Alert.alert("Batalkan konten?", "", [
      { text: "Batal", style: "cancel" },
      {
        text: "Ya, batalkan", style: "destructive",
        onPress: async () => {
          setBusy(id);
          try {
            await api.marketingCancelContent(id);
            await load();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa membatalkan konten ini.");
          } finally {
            setBusy(null);
          }
        },
      },
    ]);
  }

  const totalEngagement = Object.values(dash.engagement_30d || {}).reduce((a: number, b: any) => a + Number(b || 0), 0);

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Marketing Center</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        <View style={styles.kpiGrid}>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Campaign Aktif</Text><Text style={styles.kpiValue}>{dash.active_campaigns ?? 0}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Draft</Text><Text style={styles.kpiValue}>{dash.content_draft ?? 0}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Published</Text><Text style={styles.kpiValue}>{dash.content_published ?? 0}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Engagement 30d</Text><Text style={styles.kpiValue}>{num(totalEngagement)}</Text></View>
        </View>

        <Text style={styles.sectionLabel}>CONTENT CALENDAR ({content.length})</Text>
        <Pressable style={styles.outlineBtn} onPress={() => setContentFormOpen((v) => !v)}>
          <Text style={styles.outlineBtnText}>{contentFormOpen ? "Batal" : "+ Generate Konten (AI)"}</Text>
        </Pressable>
        {contentFormOpen ? (
          <Card style={{ gap: spacing.sm }}>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
              {PLATFORMS.map((p) => (
                <Pressable key={p} onPress={() => setPlatform(p)} style={[styles.pill, platform === p && styles.pillActive]}>
                  <Text style={[styles.pillText, platform === p && styles.pillTextActive]}>{p}</Text>
                </Pressable>
              ))}
            </ScrollView>
            <TextInput style={[styles.input, { minHeight: 70, textAlignVertical: "top" }]} value={brief} onChangeText={setBrief} placeholder="Brief konten (mis. 'Promo akhir bulan diskon 20%')" placeholderTextColor={colors.text.muted} multiline />
            {busy === "gen-content" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
              <Pressable style={styles.primaryBtn} onPress={generateContent}><Text style={styles.primaryBtnText}>Generate</Text></Pressable>
            )}
          </Card>
        ) : null}
        {content.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada konten.</Text></Card>
        ) : (
          content.map((item) => (
            <Card key={item.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Text style={styles.itemTitle} numberOfLines={1}>{item.title || item.platform}</Text>
                <Badge label={item.status.toUpperCase()} kind={CONTENT_STATUS_KIND[item.status] || "neutral"} />
              </View>
              <Text style={styles.itemMeta} numberOfLines={2}>{item.body}</Text>
              <Text style={styles.itemMeta}>{item.platform} · {item.scheduled_at ? formatDate(item.scheduled_at) : "belum dijadwalkan"}</Text>
              {busy === item.id ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                <View style={styles.actionRow}>
                  {item.status === "draft" ? <ActionBtn label="Approve" primary onPress={() => approveContent(item.id)} /> : null}
                  {(item.status === "ready_to_publish" || item.status === "scheduled") ? <ActionBtn label="Tandai Published" primary onPress={() => publishContent(item.id)} /> : null}
                  {item.status !== "published" && item.status !== "cancelled" ? <ActionBtn label="Batalkan" danger onPress={() => cancelContent(item.id)} /> : null}
                </View>
              )}
            </Card>
          ))
        )}

        <Text style={styles.sectionLabel}>CAMPAIGNS ({campaigns.length})</Text>
        <Pressable style={styles.outlineBtn} onPress={() => setCampaignFormOpen((v) => !v)}>
          <Text style={styles.outlineBtnText}>{campaignFormOpen ? "Batal" : "+ Campaign Baru"}</Text>
        </Pressable>
        {campaignFormOpen ? (
          <Card style={{ gap: spacing.sm }}>
            <TextInput style={styles.input} value={campaignName} onChangeText={setCampaignName} placeholder="Nama campaign" placeholderTextColor={colors.text.muted} />
            <TextInput style={styles.input} value={campaignGoal} onChangeText={setCampaignGoal} placeholder="Goal (opsional)" placeholderTextColor={colors.text.muted} />
            {busy === "new-campaign" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
              <Pressable style={styles.primaryBtn} onPress={createCampaign}><Text style={styles.primaryBtnText}>Buat Campaign</Text></Pressable>
            )}
          </Card>
        ) : null}
        {campaigns.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada campaign.</Text></Card>
        ) : (
          campaigns.map((c) => (
            <Card key={c.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Text style={styles.itemTitle} numberOfLines={1}>{c.name}</Text>
                <Badge label={c.status.toUpperCase()} kind="neutral" />
              </View>
              {c.goal ? <Text style={styles.itemMeta}>{c.goal}</Text> : null}
              <Text style={styles.itemMeta}>{c.start_date ? formatDate(c.start_date) : "belum ada tanggal mulai"}</Text>
            </Card>
          ))
        )}
      </ScrollView>
    </View>
  );
}

function ActionBtn({ label, onPress, primary, danger }: { label: string; onPress: () => void; primary?: boolean; danger?: boolean }) {
  return (
    <Pressable onPress={onPress} style={[styles.actionBtn, primary && styles.actionBtnPrimary, danger && styles.actionBtnDanger]}>
      <Text style={[styles.actionBtnText, primary && { color: "#fff" }, danger && { color: colors.status.danger }]}>{label}</Text>
    </Pressable>
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
  primaryBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  outlineBtn: { borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  outlineBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },

  itemCard: { gap: spacing.xs },
  itemHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  itemTitle: { flex: 1, color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  itemMeta: { color: colors.text.faint, fontSize: 11 },
  actionRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap", marginTop: spacing.xs },
  actionBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt },
  actionBtnPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  actionBtnDanger: { backgroundColor: colors.status.dangerBg, borderColor: colors.status.danger },
  actionBtnText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },
});
