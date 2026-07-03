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

type Source = {
  id: string;
  title: string | null;
  url: string | null;
  category: string | null;
  status: string;
  agent_type: string | null;
  last_crawled_at: string | null;
  created_at: string;
};

const STATUS_KIND: Record<string, BadgeKind> = {
  ready: "success", completed: "success", indexed: "success",
  pending: "warning", processing: "warning", crawling: "warning",
  failed: "danger", error: "danger",
};

export default function Knowledge() {
  const router = useRouter();
  const [sources, setSources] = useState<Source[]>([]);
  const [bots, setBots] = useState<{ id: string; name: string }[]>([]);
  const [targetBotId, setTargetBotId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState<string>("all");
  const [refreshing, setRefreshing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [srcRes, botsRes] = await Promise.allSettled([api.knowledgeSources(), api.bots()]);
      setSources(srcRes.status === "fulfilled" ? ((srcRes.value.sources || []) as Source[]) : []);
      const botList: any[] = botsRes.status === "fulfilled" ? (botsRes.value as any[]) : [];
      setBots(botList.map((b) => ({ id: b.id, name: b.name })));
      setTargetBotId((prev) => prev || botList[0]?.id || null);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat knowledge base.");
    }
  }, []);

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
      await load();
      Alert.alert("Berhasil", `"${asset.name}" sedang diproses ke knowledge base.`);
    } catch (e: any) {
      const msg = e instanceof APIError ? e.message : e?.message || "Gagal upload dokumen.";
      Alert.alert("Gagal upload", msg);
    } finally {
      setUploading(false);
    }
  }

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

  const categories = useMemo(() => {
    const set = new Set<string>();
    sources.forEach((s) => s.category && set.add(s.category));
    return ["all", ...Array.from(set)];
  }, [sources]);

  const filtered = useMemo(() => {
    return sources.filter((s) => {
      if (cat !== "all" && s.category !== cat) return false;
      if (query && !(s.title || s.url || "").toLowerCase().includes(query.toLowerCase())) return false;
      return true;
    });
  }, [sources, cat, query]);

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

      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
      >
        <Text style={styles.subtitle}>{sources.length} dokumen tersimpan</Text>

        <View style={styles.searchWrap}>
          <Ionicons name="search-outline" size={16} color={colors.text.muted} style={{ marginRight: spacing.sm }} />
          <TextInput
            placeholder="Cari dokumen…"
            placeholderTextColor={colors.text.muted}
            value={query}
            onChangeText={setQuery}
            style={styles.searchInput}
          />
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterRow}>
          {categories.map((c) => (
            <Pressable key={c} onPress={() => setCat(c)} style={[styles.filterPill, cat === c && styles.filterPillActive]}>
              <Text style={[styles.filterLabel, cat === c && styles.filterLabelActive]}>{c === "all" ? "Semua" : c}</Text>
            </Pressable>
          ))}
        </ScrollView>

        {error ? (
          <Card style={{ borderColor: colors.status.danger }}>
            <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
          </Card>
        ) : null}

        {!error && filtered.length === 0 ? (
          <Card>
            <Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>
              {sources.length === 0 ? "Belum ada dokumen knowledge." : "Tidak ada dokumen yang cocok."}
            </Text>
          </Card>
        ) : null}

        {filtered.map((s) => (
          <Card key={s.id} style={styles.docCard}>
            <View style={styles.docIcon}>
              <MaterialCommunityIcons name="file-document-outline" size={20} color={colors.brand.violet400} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.docTitle} numberOfLines={2}>{s.title || s.url || "Dokumen"}</Text>
              <View style={styles.docMetaRow}>
                {s.category ? <Badge label={s.category.toUpperCase()} kind="neutral" /> : null}
                <Badge label={(s.status || "").toUpperCase()} kind={STATUS_KIND[s.status] || "neutral"} />
              </View>
              <Text style={styles.docDate}>Diperbarui {formatDate(s.last_crawled_at || s.created_at)}</Text>
            </View>
          </Card>
        ))}

        {bots.length > 1 ? (
          <>
            <Text style={styles.sectionLabel}>UNGGAH KE AGEN</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterRow}>
              {bots.map((b) => (
                <Pressable
                  key={b.id}
                  onPress={() => setTargetBotId(b.id)}
                  style={[styles.filterPill, targetBotId === b.id && styles.filterPillActive]}
                >
                  <Text style={[styles.filterLabel, targetBotId === b.id && styles.filterLabelActive]} numberOfLines={1}>
                    {b.name}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
          </>
        ) : null}

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
  uploadIconBtn: { width: 32, height: 32, borderRadius: radius.full, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  topTitle: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  container: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  subtitle: { color: colors.text.muted, fontSize: 12 },
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },
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
  docIcon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: "rgba(139,92,246,0.12)", alignItems: "center", justifyContent: "center" },
  docTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  docMetaRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm, flexWrap: "wrap" },
  docDate: { color: colors.text.faint, fontSize: 11, marginTop: spacing.sm },
});
