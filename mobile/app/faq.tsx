import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

type Faq = { id: string; question: string; answer: string; category: string | null; status: string };
type Sop = { id: string; title: string; steps: string[]; category: string | null; status: string };
type Doc = { id: string; filename: string; summary: string | null; categories: string[]; tags: string[]; kb_status: string; status: string; created_at: string };

const STATUS_KIND: Record<string, BadgeKind> = {
  suggested: "warning", approved: "success", rejected: "danger",
  ready: "success", pending: "warning", processing: "warning", failed: "danger",
};

export default function KnowledgeBuilder() {
  const router = useRouter();
  const [bots, setBots] = useState<{ id: string; name: string }[]>([]);
  const [botId, setBotId] = useState<string | null>(null);
  const [overview, setOverview] = useState<any>(null);
  const [faqs, setFaqs] = useState<Faq[]>([]);
  const [sops, setSops] = useState<Sop[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const loadBotScoped = useCallback(async (id: string) => {
    const [ovR, faqR, sopR] = await Promise.allSettled([
      api.kbOverview(id), api.kbFaqs(id), api.kbSops(id),
    ]);
    setOverview(ovR.status === "fulfilled" ? ovR.value : null);
    setFaqs(faqR.status === "fulfilled" ? faqR.value.faqs || [] : []);
    setSops(sopR.status === "fulfilled" ? sopR.value.sops || [] : []);
    if (ovR.status === "rejected") setError((ovR as any).reason?.message || "Gagal memuat Knowledge Builder.");
  }, []);

  const load = useCallback(async () => {
    try {
      setError(null);
      const botsRes = await api.bots();
      const list = (botsRes as any[]).map((b) => ({ id: b.id, name: b.name }));
      setBots(list);
      const activeBotId = botId || list[0]?.id || null;
      setBotId(activeBotId);
      if (!activeBotId) return;
      await loadBotScoped(activeBotId);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat Knowledge Builder.");
    }
  }, [botId, loadBotScoped]);

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

  function switchBot(id: string) {
    setBotId(id);
    loadBotScoped(id);
  }

  async function regenerate(doc: Doc) {
    if (!botId) return;
    setBusyId(doc.id);
    try {
      await api.kbRegenerate(botId, doc.id);
      Alert.alert("Dijadwalkan", `Knowledge Builder dijadwalkan ulang untuk "${doc.filename}".`);
      await loadBotScoped(botId);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa regenerate dokumen ini.");
    } finally {
      setBusyId(null);
    }
  }

  async function setFaqStatus(faq: Faq, status: string) {
    setBusyId(faq.id);
    try {
      await api.kbUpdateFaq(faq.id, { status });
      setFaqs((prev) => prev.map((f) => (f.id === faq.id ? { ...f, status } : f)));
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa mengubah status FAQ.");
    } finally {
      setBusyId(null);
    }
  }

  async function setSopStatus(sop: Sop, status: string) {
    setBusyId(sop.id);
    try {
      await api.kbUpdateSop(sop.id, { status });
      setSops((prev) => prev.map((s) => (s.id === sop.id ? { ...s, status } : s)));
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa mengubah status SOP.");
    } finally {
      setBusyId(null);
    }
  }

  async function importCsv() {
    if (!botId) return;
    let result: any;
    try {
      const DocumentPicker = await import("expo-document-picker");
      result = await DocumentPicker.getDocumentAsync({ type: "text/csv", copyToCacheDirectory: true, multiple: false });
    } catch (e: any) {
      Alert.alert("Gagal membuka file picker", e?.message || "Fitur pilih file tidak tersedia.");
      return;
    }
    if (result.canceled || !result.assets?.[0]) return;
    const asset = result.assets[0];
    setImporting(true);
    try {
      const res = await api.importFaqCsv(botId, { uri: asset.uri, name: asset.name, mimeType: asset.mimeType });
      await loadBotScoped(botId);
      Alert.alert("Berhasil", res?.message || "FAQ CSV berhasil diimpor.");
    } catch (e: any) {
      Alert.alert("Gagal import", e?.message || "Tidak bisa mengimpor FAQ CSV.");
    } finally {
      setImporting(false);
    }
  }

  const quality = overview?.quality || {};
  const documents: Doc[] = overview?.documents || [];
  const missingTopics: { topic: string; document_count: number }[] = overview?.missing_topics || [];

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Knowledge Builder</Text>
        <Pressable style={styles.uploadIconBtn} onPress={importCsv} disabled={importing}>
          {importing ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="cloud-upload-outline" size={18} color="#fff" />}
        </Pressable>
      </View>

      {bots.length > 1 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.botRow}>
          {bots.map((b) => (
            <Pressable key={b.id} onPress={() => switchBot(b.id)} style={[styles.pill, botId === b.id && styles.pillActive]}>
              <Text style={[styles.pillText, botId === b.id && styles.pillTextActive]} numberOfLines={1}>{b.name}</Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : null}

      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
      >
        <Text style={styles.subtitle}>Dokumen otomatis dianalisis menjadi ringkasan, kategori, FAQ, SOP, dan skor kualitas.</Text>

        {error ? (
          <Card style={{ borderColor: colors.status.danger }}>
            <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
          </Card>
        ) : null}

        {!botId ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada agen.</Text></Card>
        ) : (
          <>
            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Overall</Text><Text style={styles.kpiValue}>{quality.overall_score ?? 0}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Completeness</Text><Text style={styles.kpiValue}>{quality.completeness_score ?? 0}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Coverage</Text><Text style={styles.kpiValue}>{quality.coverage_score ?? 0}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Redundancy</Text><Text style={styles.kpiValue}>{quality.redundancy_score ?? 0}</Text></View>
            </View>

            <Text style={styles.sectionLabel}>DOKUMEN ({documents.length})</Text>
            {documents.length === 0 ? (
              <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada dokumen. Upload di Knowledge Base.</Text></Card>
            ) : (
              documents.map((d) => (
                <Card key={d.id} style={styles.itemCard}>
                  <View style={styles.itemHead}>
                    <Text style={styles.itemTitle} numberOfLines={1}>{d.filename}</Text>
                    <Badge label={(d.kb_status || "pending").toUpperCase()} kind={STATUS_KIND[d.kb_status] || "neutral"} />
                  </View>
                  {d.summary ? <Text style={styles.itemDesc} numberOfLines={2}>{d.summary}</Text> : null}
                  <View style={styles.chipRow}>
                    {(d.categories || []).map((c) => <Badge key={c} label={c} kind="neutral" />)}
                    {(d.tags || []).map((t) => <Badge key={t} label={t} kind="neutral" />)}
                  </View>
                  {busyId === d.id ? (
                    <ActivityIndicator size="small" color={colors.brand.violet400} />
                  ) : (
                    <Pressable
                      style={[styles.smallBtn, d.status !== "ready" && styles.btnDisabled]}
                      onPress={() => regenerate(d)}
                      disabled={d.status !== "ready"}
                    >
                      <MaterialCommunityIcons name="refresh" size={14} color={colors.brand.violet400} />
                      <Text style={styles.smallBtnText}>Regenerate</Text>
                    </Pressable>
                  )}
                </Card>
              ))
            )}

            <Text style={styles.sectionLabel}>
              GENERATED FAQ · {overview?.faqs?.suggested || 0} suggested · {overview?.faqs?.approved || 0} approved · {overview?.faqs?.rejected || 0} rejected
            </Text>
            {faqs.length === 0 ? (
              <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada FAQ. Akan muncul setelah dokumen diproses.</Text></Card>
            ) : (
              faqs.map((f) => (
                <Card key={f.id} style={styles.itemCard}>
                  <View style={styles.itemHead}>
                    <Text style={styles.itemTitle} numberOfLines={2}>{f.question}</Text>
                    <Badge label={f.status.toUpperCase()} kind={STATUS_KIND[f.status] || "neutral"} />
                  </View>
                  <Text style={styles.itemDesc}>{f.answer}</Text>
                  {f.category ? <Text style={styles.itemMeta}>{f.category}</Text> : null}
                  {busyId === f.id ? (
                    <ActivityIndicator size="small" color={colors.brand.violet400} />
                  ) : (
                    <View style={styles.actionRow}>
                      {f.status !== "approved" ? <ActionBtn label="Approve" primary onPress={() => setFaqStatus(f, "approved")} /> : null}
                      {f.status !== "rejected" ? <ActionBtn label="Reject" danger onPress={() => setFaqStatus(f, "rejected")} /> : null}
                      {f.status !== "suggested" ? <ActionBtn label="Reset" onPress={() => setFaqStatus(f, "suggested")} /> : null}
                    </View>
                  )}
                </Card>
              ))
            )}

            <Text style={styles.sectionLabel}>
              GENERATED SOP · {overview?.sops?.suggested || 0} suggested · {overview?.sops?.approved || 0} approved · {overview?.sops?.rejected || 0} rejected
            </Text>
            {sops.length === 0 ? (
              <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada SOP. Akan muncul setelah dokumen diproses.</Text></Card>
            ) : (
              sops.map((s) => (
                <Card key={s.id} style={styles.itemCard}>
                  <View style={styles.itemHead}>
                    <Text style={styles.itemTitle} numberOfLines={2}>{s.title}</Text>
                    <Badge label={s.status.toUpperCase()} kind={STATUS_KIND[s.status] || "neutral"} />
                  </View>
                  {(s.steps || []).slice(0, 5).map((step, i) => (
                    <Text key={i} style={styles.itemDesc}>{i + 1}. {step}</Text>
                  ))}
                  {s.category ? <Text style={styles.itemMeta}>{s.category}</Text> : null}
                  {busyId === s.id ? (
                    <ActivityIndicator size="small" color={colors.brand.violet400} />
                  ) : (
                    <View style={styles.actionRow}>
                      {s.status !== "approved" ? <ActionBtn label="Approve" primary onPress={() => setSopStatus(s, "approved")} /> : null}
                      {s.status !== "rejected" ? <ActionBtn label="Reject" danger onPress={() => setSopStatus(s, "rejected")} /> : null}
                      {s.status !== "suggested" ? <ActionBtn label="Reset" onPress={() => setSopStatus(s, "suggested")} /> : null}
                    </View>
                  )}
                </Card>
              ))
            )}

            <Text style={styles.sectionLabel}>MISSING TOPICS</Text>
            <Card style={styles.chipRow}>
              {missingTopics.length === 0 ? (
                <Text style={{ color: colors.text.muted, fontSize: 13 }}>Tidak ada topik penting yang terdeteksi hilang.</Text>
              ) : (
                missingTopics.map((m) => <Badge key={m.topic} label={`${m.topic} (${m.document_count})`} kind="danger" />)
              )}
            </Card>
          </>
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
  uploadIconBtn: { width: 32, height: 32, borderRadius: radius.full, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  topTitle: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  botRow: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  pill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  pillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  pillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  pillTextActive: { color: "#fff" },
  container: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  subtitle: { color: colors.text.muted, fontSize: 12, lineHeight: 17 },
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },

  kpiGrid: { flexDirection: "row", gap: spacing.sm },
  kpiCard: { flex: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, paddingVertical: spacing.md, alignItems: "center" },
  kpiLabel: { color: colors.text.faint, fontSize: 10, marginTop: 2 },
  kpiValue: { color: colors.text.primary, fontSize: 18, fontWeight: "800" },

  itemCard: { gap: spacing.sm },
  itemHead: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm, justifyContent: "space-between" },
  itemTitle: { flex: 1, color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  itemDesc: { color: colors.text.muted, fontSize: 12, lineHeight: 17 },
  itemMeta: { color: colors.text.faint, fontSize: 11 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },

  smallBtn: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border },
  smallBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },
  btnDisabled: { opacity: 0.4 },

  actionRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  actionBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt },
  actionBtnPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  actionBtnDanger: { backgroundColor: colors.status.dangerBg, borderColor: colors.status.danger },
  actionBtnText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },
});
