import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { useFocusEffect } from "expo-router";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api, APIError } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { formatDate } from "../src/utils/format";

// Must mirror main.py's `_ALLOWED_DOCUMENT_EXTENSIONS` exactly -- the Figma
// mockup says "PDF, DOCX, XLSX, TXT" but the backend does NOT accept XLSX,
// so the UI copy here intentionally differs from the design to stay honest.
const ALLOWED_LABEL = "PDF, DOCX, CSV, MD, TXT · Maks. 20MB";

// Same 9 vertical-specific seed types web offers (frontend/app.js's
// renderKnowledge -- `seedAgents` array), each imports its own preset seed
// JSON without crawling everything at once.
const SEED_AGENTS = [
  "travel_agent", "ecommerce_agent", "clinic_agent", "school_agent", "sales_agent",
  "property_agent", "faq_agent", "customer_service_agent", "botnesia_business",
];
const STATUS_FILTERS = ["", "pending", "crawling", "indexed", "failed", "skipped"];

type Source = {
  id: string;
  title: string | null;
  url: string | null;
  category: string | null;
  status: string;
  agent_type: string | null;
  error_message: string | null;
  last_crawled_at: string | null;
  created_at: string;
};
type Doc = {
  id: string;
  filename: string;
  chunk_count: number;
  status: string;
  source_type: string | null;
  source_url: string | null;
  created_at: string;
};

const STATUS_KIND: Record<string, BadgeKind> = {
  ready: "success", completed: "success", indexed: "success",
  pending: "warning", processing: "warning", crawling: "warning", skipped: "neutral",
  failed: "danger", error: "danger",
};

export default function Knowledge() {
  const router = useRouter();
  const [bots, setBots] = useState<{ id: string; name: string }[]>([]);
  const [targetBotId, setTargetBotId] = useState<string | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [stats, setStats] = useState<any>({});
  const [documents, setDocuments] = useState<Doc[]>([]);
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [bulkUrls, setBulkUrls] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [bulkImporting, setBulkImporting] = useState(false);
  const [seeding, setSeeding] = useState<string | null>(null);
  const [busySourceId, setBusySourceId] = useState<string | null>(null);
  const [busyDocId, setBusyDocId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadBotScoped = useCallback(async (botId: string) => {
    const [srcRes, docsRes] = await Promise.allSettled([
      api.knowledgeSources({ botId, status: statusFilter || undefined, search: query || undefined }),
      api.documents(botId),
    ]);
    setSources(srcRes.status === "fulfilled" ? ((srcRes.value.sources || []) as Source[]) : []);
    setStats(srcRes.status === "fulfilled" ? srcRes.value.stats || {} : {});
    setDocuments(docsRes.status === "fulfilled" ? (docsRes.value as Doc[]) : []);
  }, [statusFilter, query]);

  const load = useCallback(async () => {
    try {
      setError(null);
      const botsRes = await api.bots();
      const botList = (botsRes as any[]).map((b) => ({ id: b.id, name: b.name }));
      setBots(botList);
      const activeBotId = targetBotId || botList[0]?.id || null;
      setTargetBotId(activeBotId);
      if (!activeBotId) {
        setSources([]); setDocuments([]); setStats({});
        return;
      }
      await loadBotScoped(activeBotId);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat knowledge base.");
    }
  }, [targetBotId, loadBotScoped]);

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
    setTargetBotId(id);
    loadBotScoped(id);
  }

  async function pickAndUpload() {
    if (!targetBotId) {
      Alert.alert("Belum ada agen", "Buat agen dulu di tab Agen sebelum upload dokumen.");
      return;
    }
    let result: any;
    try {
      // Loaded lazily (not as a top-level import) so a native-module issue
      // with this specific package can only ever fail this one action --
      // never crash the whole app at boot, since Expo Router eagerly
      // imports every file under app/ to build its route table.
      const DocumentPicker = await import("expo-document-picker");
      result = await DocumentPicker.getDocumentAsync({
        type: ["application/pdf", "text/*", "text/csv", "text/markdown", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
        copyToCacheDirectory: true,
        multiple: false,
      });
    } catch (e: any) {
      Alert.alert("Gagal membuka file picker", e?.message || "Fitur pilih file tidak tersedia di perangkat ini.");
      return;
    }
    if (result.canceled || !result.assets?.[0]) return;
    const asset = result.assets[0];
    setUploading(true);
    try {
      await api.uploadDocument(targetBotId, { uri: asset.uri, name: asset.name, mimeType: asset.mimeType });
      await loadBotScoped(targetBotId);
      Alert.alert("Berhasil", `"${asset.name}" sedang diproses ke knowledge base.`);
    } catch (e: any) {
      const msg = e instanceof APIError ? e.message : e?.message || "Gagal upload dokumen.";
      Alert.alert("Gagal upload", msg);
    } finally {
      setUploading(false);
    }
  }

  async function importBulkUrls() {
    if (!targetBotId) return;
    const urls = bulkUrls.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    if (urls.length === 0) {
      Alert.alert("Kosong", "Masukkan minimal satu URL, satu per baris.");
      return;
    }
    setBulkImporting(true);
    try {
      const entries = urls.map((url) => ({ url, category: "custom", priority: "normal", agent: "custom", language: "id", trusted: false }));
      const res = await api.bulkKnowledgeUrls(targetBotId, entries, true);
      setBulkUrls("");
      await loadBotScoped(targetBotId);
      Alert.alert("Berhasil", `${res.imported} URL masuk queue, ${res.skipped_duplicate} duplikat dilewati.`);
    } catch (e: any) {
      Alert.alert("Gagal import", e?.message || "Tidak bisa mengimpor URL.");
    } finally {
      setBulkImporting(false);
    }
  }

  async function runSeed(kind: string) {
    if (!targetBotId) return;
    setSeeding(kind);
    try {
      let res: any;
      if (kind === "marketplace") res = await api.seedMarketplaceKnowledge(targetBotId, false, false);
      else if (kind === "retry_failed") res = await api.retryFailedKnowledgeSources({ bot_id: targetBotId, crawl: false });
      else if (kind === "general") res = await api.seedKnowledgeGeneral(targetBotId, true);
      else if (kind === "all_agents") res = await api.seedKnowledgeAgents(targetBotId, true);
      else res = await api.seedKnowledgeAgent(kind, targetBotId, true);
      await loadBotScoped(targetBotId);
      const count = res?.imported ?? res?.retried ?? res?.total ?? 0;
      Alert.alert("Selesai", `Seed "${kind.replace(/_/g, " ")}" selesai (${count} item).`);
    } catch (e: any) {
      Alert.alert("Gagal seed", e?.message || "Tidak bisa menjalankan seeder.");
    } finally {
      setSeeding(null);
    }
  }

  async function retrySource(s: Source) {
    setBusySourceId(s.id);
    try {
      await api.retryKnowledgeSource(s.id);
      if (targetBotId) await loadBotScoped(targetBotId);
    } catch (e: any) {
      Alert.alert("Gagal retry", e?.message || "Tidak bisa retry source ini.");
    } finally {
      setBusySourceId(null);
    }
  }

  function deleteSource(s: Source) {
    Alert.alert("Hapus source?", s.title || s.url || "Source ini akan dihapus.", [
      { text: "Batal", style: "cancel" },
      {
        text: "Hapus", style: "destructive",
        onPress: async () => {
          setBusySourceId(s.id);
          try {
            await api.deleteKnowledgeSource(s.id);
            if (targetBotId) await loadBotScoped(targetBotId);
          } catch (e: any) {
            Alert.alert("Gagal hapus", e?.message || "Tidak bisa menghapus source ini.");
          } finally {
            setBusySourceId(null);
          }
        },
      },
    ]);
  }

  function deleteDoc(d: Doc) {
    if (!targetBotId) return;
    Alert.alert("Hapus dokumen?", d.filename, [
      { text: "Batal", style: "cancel" },
      {
        text: "Hapus", style: "destructive",
        onPress: async () => {
          setBusyDocId(d.id);
          try {
            await api.deleteDocument(targetBotId, d.id);
            await loadBotScoped(targetBotId);
          } catch (e: any) {
            Alert.alert("Gagal hapus", e?.message || "Tidak bisa menghapus dokumen ini.");
          } finally {
            setBusyDocId(null);
          }
        },
      },
    ]);
  }

  const categories = useMemo(() => {
    const set = new Set<string>();
    sources.forEach((s) => s.category && set.add(s.category));
    return ["all", ...Array.from(set)];
  }, [sources]);

  const filtered = useMemo(() => {
    return sources.filter((s) => (cat === "all" ? true : s.category === cat));
  }, [sources, cat]);

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Knowledge Base</Text>
        <Pressable style={styles.uploadIconBtn} onPress={pickAndUpload} disabled={uploading}>
          {uploading ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="cloud-upload-outline" size={18} color="#fff" />}
        </Pressable>
      </View>

      {bots.length > 1 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.botRow}>
          {bots.map((b) => (
            <Pressable key={b.id} onPress={() => switchBot(b.id)} style={[styles.filterPill, targetBotId === b.id && styles.filterPillActive]}>
              <Text style={[styles.filterLabel, targetBotId === b.id && styles.filterLabelActive]} numberOfLines={1}>{b.name}</Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : null}

      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
      >
        {error ? (
          <Card style={{ borderColor: colors.status.danger }}>
            <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
          </Card>
        ) : null}

        {!targetBotId ? (
          <Card>
            <Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada agen. Buat agen dulu di tab Agen.</Text>
          </Card>
        ) : (
          <>
            {/* 4 metric tiles */}
            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Total URL</Text><Text style={styles.kpiValue}>{stats.total ?? 0}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Pending</Text><Text style={styles.kpiValue}>{stats.pending ?? 0}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Crawling</Text><Text style={styles.kpiValue}>{stats.crawling ?? 0}</Text></View>
              <View style={styles.kpiCard}><Text style={[styles.kpiValue, (stats.failed ?? 0) > 0 && { color: colors.status.danger }]}>{stats.failed ?? 0}</Text><Text style={styles.kpiLabel}>Failed</Text></View>
            </View>

            <Pressable style={styles.kbLink} onPress={() => router.push("/faq")}>
              <MaterialCommunityIcons name="auto-fix" size={16} color={colors.brand.violet400} />
              <Text style={styles.kbLinkText}>Buka Knowledge Builder — FAQ & SOP otomatis dari dokumen ini</Text>
              <Ionicons name="chevron-forward" size={16} color={colors.text.faint} />
            </Pressable>

            {/* Dokumen Terunggah (document library -- distinct from URL source tracking below) */}
            <Text style={styles.sectionLabel}>DOKUMEN TERUNGGAH ({documents.length})</Text>
            {documents.length === 0 ? (
              <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada dokumen diunggah.</Text></Card>
            ) : (
              documents.map((d) => (
                <Card key={d.id} style={styles.docCard}>
                  <View style={styles.docIcon}>
                    <MaterialCommunityIcons name="file-document-outline" size={20} color={colors.brand.violet400} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.docTitle} numberOfLines={2}>{d.filename}</Text>
                    <View style={styles.docMetaRow}>
                      <Badge label={`${d.chunk_count} chunk`} kind="neutral" />
                      <Badge label={(d.status || "").toUpperCase()} kind={STATUS_KIND[d.status] || "neutral"} />
                    </View>
                    <Text style={styles.docDate}>{formatDate(d.created_at)}</Text>
                  </View>
                  {busyDocId === d.id ? (
                    <ActivityIndicator size="small" color={colors.status.danger} />
                  ) : (
                    <Pressable onPress={() => deleteDoc(d)} hitSlop={8}>
                      <MaterialCommunityIcons name="trash-can-outline" size={18} color={colors.status.danger} />
                    </Pressable>
                  )}
                </Card>
              ))
            )}

            {/* Import massal URL */}
            <Text style={styles.sectionLabel}>IMPOR URL MASSAL</Text>
            <Card style={{ gap: spacing.sm }}>
              <Text style={styles.hint}>Satu URL per baris. Kategori otomatis "custom".</Text>
              <TextInput
                value={bulkUrls}
                onChangeText={setBulkUrls}
                placeholder={"https://contoh.com/panduan\nhttps://contoh.com/faq"}
                placeholderTextColor={colors.text.muted}
                multiline
                style={styles.bulkInput}
              />
              <Pressable style={[styles.primaryBtn, bulkImporting && styles.btnDisabled]} onPress={importBulkUrls} disabled={bulkImporting}>
                {bulkImporting ? <ActivityIndicator size="small" color="#fff" /> : <Text style={styles.primaryBtnText}>Import URL</Text>}
              </Pressable>
            </Card>

            {/* Agent Knowledge Seeder */}
            <Text style={styles.sectionLabel}>AGENT KNOWLEDGE SEEDER</Text>
            <View style={styles.seedGrid}>
              <SeedBtn label="Seed Marketplace 1000" primary busy={seeding === "marketplace"} onPress={() => runSeed("marketplace")} />
              <SeedBtn label="Retry Failed" busy={seeding === "retry_failed"} onPress={() => runSeed("retry_failed")} />
              <SeedBtn label="General AI" busy={seeding === "general"} onPress={() => runSeed("general")} />
              <SeedBtn label="Semua Agent" busy={seeding === "all_agents"} onPress={() => runSeed("all_agents")} />
              {SEED_AGENTS.map((a) => (
                <SeedBtn key={a} label={a.replace(/_/g, " ")} busy={seeding === a} onPress={() => runSeed(a)} />
              ))}
            </View>

            {/* Source tracking */}
            <Text style={styles.sectionLabel}>SOURCE TRACKING ({filtered.length})</Text>

            <View style={styles.searchWrap}>
              <Ionicons name="search-outline" size={16} color={colors.text.muted} style={{ marginRight: spacing.sm }} />
              <TextInput
                placeholder="Cari URL/judul…"
                placeholderTextColor={colors.text.muted}
                value={query}
                onChangeText={setQuery}
                onSubmitEditing={() => targetBotId && loadBotScoped(targetBotId)}
                style={styles.searchInput}
              />
            </View>

            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterRow}>
              {STATUS_FILTERS.map((s) => (
                <Pressable
                  key={s || "semua"}
                  onPress={() => { setStatusFilter(s); if (targetBotId) loadBotScoped(targetBotId); }}
                  style={[styles.filterPill, statusFilter === s && styles.filterPillActive]}
                >
                  <Text style={[styles.filterLabel, statusFilter === s && styles.filterLabelActive]}>{s ? s : "Semua status"}</Text>
                </Pressable>
              ))}
            </ScrollView>

            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterRow}>
              {categories.map((c) => (
                <Pressable key={c} onPress={() => setCat(c)} style={[styles.filterPill, cat === c && styles.filterPillActive]}>
                  <Text style={[styles.filterLabel, cat === c && styles.filterLabelActive]}>{c === "all" ? "Semua kategori" : c}</Text>
                </Pressable>
              ))}
            </ScrollView>

            {filtered.length === 0 ? (
              <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Tidak ada source yang cocok.</Text></Card>
            ) : (
              filtered.map((s) => (
                <Card key={s.id} style={styles.sourceCard}>
                  <View style={styles.docIcon}>
                    <MaterialCommunityIcons name="link-variant" size={18} color={colors.brand.violet400} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.docTitle} numberOfLines={2}>{s.title || s.url}</Text>
                    <Text style={styles.sourceUrl} numberOfLines={1}>{s.url}</Text>
                    {s.error_message ? <Text style={styles.sourceError} numberOfLines={2}>{s.error_message}</Text> : null}
                    <View style={styles.docMetaRow}>
                      {s.category ? <Badge label={s.category} kind="neutral" /> : null}
                      <Badge label={(s.status || "").toUpperCase()} kind={STATUS_KIND[s.status] || "neutral"} />
                    </View>
                  </View>
                  {busySourceId === s.id ? (
                    <ActivityIndicator size="small" color={colors.brand.violet400} />
                  ) : (
                    <View style={{ gap: spacing.sm, alignItems: "flex-end" }}>
                      {s.status === "failed" ? (
                        <Pressable onPress={() => retrySource(s)} hitSlop={8}>
                          <MaterialCommunityIcons name="refresh" size={18} color={colors.brand.violet400} />
                        </Pressable>
                      ) : null}
                      <Pressable onPress={() => deleteSource(s)} hitSlop={8}>
                        <MaterialCommunityIcons name="trash-can-outline" size={18} color={colors.status.danger} />
                      </Pressable>
                    </View>
                  )}
                </Card>
              ))
            )}

            <Pressable style={styles.uploadCard} onPress={pickAndUpload} disabled={uploading}>
              {uploading ? (
                <ActivityIndicator size="small" color={colors.brand.violet400} />
              ) : (
                <View style={styles.uploadCardIcon}>
                  <Ionicons name="cloud-upload-outline" size={22} color={colors.brand.violet400} />
                </View>
              )}
              <Text style={styles.uploadCardTitle}>Tambah Dokumen Baru</Text>
              <Text style={styles.uploadCardHint}>{ALLOWED_LABEL}</Text>
              <View style={styles.uploadCardBtn}>
                <Text style={styles.uploadCardBtnText}>Pilih File</Text>
              </View>
            </Pressable>
          </>
        )}
      </ScrollView>
    </View>
  );
}

function SeedBtn({ label, onPress, busy, primary }: { label: string; onPress: () => void; busy?: boolean; primary?: boolean }) {
  return (
    <Pressable style={[styles.seedBtn, primary && styles.seedBtnPrimary, busy && styles.btnDisabled]} onPress={onPress} disabled={busy}>
      {busy ? (
        <ActivityIndicator size="small" color={primary ? "#fff" : colors.brand.violet400} />
      ) : (
        <Text style={[styles.seedBtnText, primary && { color: "#fff" }]} numberOfLines={1}>{label}</Text>
      )}
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
  container: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  hint: { color: colors.text.faint, fontSize: 11 },
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },

  kpiGrid: { flexDirection: "row", gap: spacing.sm },
  kpiCard: { flex: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, paddingVertical: spacing.md, alignItems: "center" },
  kpiLabel: { color: colors.text.faint, fontSize: 10, marginTop: 2 },
  kpiValue: { color: colors.text.primary, fontSize: 18, fontWeight: "800" },

  kbLink: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: "rgba(139,92,246,0.08)",
    borderWidth: 1, borderColor: colors.brand.violet500, borderRadius: radius.md, padding: spacing.md,
  },
  kbLinkText: { flex: 1, color: colors.text.body, fontSize: 12, fontWeight: "600" },

  bulkInput: {
    backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.md,
    padding: spacing.md, color: colors.text.primary, fontSize: 12, minHeight: 90, textAlignVertical: "top",
  },
  primaryBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 13, fontWeight: "700" },
  btnDisabled: { opacity: 0.6 },

  seedGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  seedBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  seedBtnPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  seedBtnText: { color: colors.text.body, fontSize: 12, fontWeight: "600", textTransform: "capitalize" },

  uploadCard: {
    borderWidth: 1, borderColor: colors.bg.border, borderStyle: "dashed", borderRadius: radius.lg,
    alignItems: "center", justifyContent: "center", gap: spacing.xs, padding: spacing.xl, marginTop: spacing.sm,
  },
  uploadCardIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: "rgba(139,92,246,0.12)", alignItems: "center", justifyContent: "center", marginBottom: spacing.xs },
  uploadCardTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  uploadCardHint: { color: colors.text.faint, fontSize: 11 },
  uploadCardBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.full, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, marginTop: spacing.sm },
  uploadCardBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  searchWrap: {
    flexDirection: "row", alignItems: "center", backgroundColor: colors.bg.card,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, paddingHorizontal: spacing.md,
  },
  searchInput: { flex: 1, color: colors.text.primary, fontSize: 13, paddingVertical: spacing.md },
  filterRow: { gap: spacing.sm, paddingVertical: spacing.xs },
  filterPill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  filterPillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  filterLabel: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  filterLabelActive: { color: "#fff" },
  docCard: { flexDirection: "row", gap: spacing.md, alignItems: "flex-start" },
  sourceCard: { flexDirection: "row", gap: spacing.md, alignItems: "flex-start" },
  docIcon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: "rgba(139,92,246,0.12)", alignItems: "center", justifyContent: "center" },
  docTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  docMetaRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm, flexWrap: "wrap" },
  docDate: { color: colors.text.faint, fontSize: 11, marginTop: spacing.sm },
  sourceUrl: { color: colors.text.faint, fontSize: 10, marginTop: 2 },
  sourceError: { color: colors.status.danger, fontSize: 11, marginTop: spacing.xs },
});
