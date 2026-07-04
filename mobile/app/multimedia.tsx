import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Image, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Card } from "../src/components/Card";
import { api, API_BASE } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { formatDate } from "../src/utils/format";

function mediaUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE}${path}`;
}

const SIZES = ["1024x1024", "1536x1024", "1024x1536"];
const IMAGE_PROVIDERS = [
  { value: "", label: "Default" }, { value: "replicate", label: "Replicate" }, { value: "openai", label: "OpenAI" },
  { value: "google_imagen", label: "Google Imagen" }, { value: "stability", label: "Stability AI" }, { value: "fal", label: "Fal.ai" },
];
const ANALYZE_MODES = [
  { value: "describe", label: "Deskripsikan gambar" }, { value: "ocr", label: "Baca teks (OCR)" },
  { value: "ui_analysis", label: "Analisis UI/Dashboard" }, { value: "document", label: "Baca invoice/dokumen" },
];
const DOC_FORMATS = ["pdf", "docx", "xlsx", "pptx"];

export default function MultimediaStudio() {
  const router = useRouter();
  const [history, setHistory] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [imgPrompt, setImgPrompt] = useState("");
  const [imgStyle, setImgStyle] = useState("");
  const [imgSize, setImgSize] = useState("1024x1024");
  const [imgProvider, setImgProvider] = useState("");
  const [generatingImg, setGeneratingImg] = useState(false);
  const [lastImage, setLastImage] = useState<{ image_url: string; provider: string; generation_time: number } | null>(null);

  const [pickedImage, setPickedImage] = useState<{ uri: string; name: string; type: string } | null>(null);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("describe");
  const [analyzing, setAnalyzing] = useState(false);
  const [lastAnalysis, setLastAnalysis] = useState<{ answer: string } | null>(null);

  const [docFormat, setDocFormat] = useState("pdf");
  const [docPrompt, setDocPrompt] = useState("");
  const [generatingDoc, setGeneratingDoc] = useState(false);
  const [lastDocument, setLastDocument] = useState<{ file_url: string; format: string; title: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const res = await api.imagesHistory(null, 24);
      setHistory(res.items || []);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat riwayat multimedia.");
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function generateImage() {
    if (!imgPrompt.trim()) {
      Alert.alert("Lengkapi form", "Prompt gambar wajib diisi.");
      return;
    }
    setGeneratingImg(true);
    try {
      const result = await api.imagesGenerate({ prompt: imgPrompt.trim(), style: imgStyle.trim(), size: imgSize, provider: imgProvider });
      setLastImage(result);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa generate gambar.");
    } finally {
      setGeneratingImg(false);
    }
  }

  async function pickImage() {
    const ImagePicker = await import("expo-image-picker");
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Izin ditolak", "Aktifkan izin akses galeri untuk memilih gambar.");
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.85,
    });
    if (result.canceled || !result.assets?.[0]) return;
    const asset = result.assets[0];
    const name = asset.fileName || asset.uri.split("/").pop() || "image.jpg";
    const type = asset.mimeType || "image/jpeg";
    setPickedImage({ uri: asset.uri, name, type });
  }

  async function analyzeImage() {
    if (!pickedImage) {
      Alert.alert("Pilih gambar", "Pilih gambar dari galeri dulu.");
      return;
    }
    setAnalyzing(true);
    try {
      const result = await api.imagesAnalyze(pickedImage.uri, pickedImage.name, pickedImage.type, { question: question.trim(), mode });
      setLastAnalysis(result);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menganalisis gambar.");
    } finally {
      setAnalyzing(false);
    }
  }

  async function generateDocument() {
    if (!docPrompt.trim()) {
      Alert.alert("Lengkapi form", "Deskripsi dokumen wajib diisi.");
      return;
    }
    setGeneratingDoc(true);
    try {
      const result = await api.documentsGenerate({ format: docFormat, prompt: docPrompt.trim() });
      setLastDocument(result);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa generate dokumen.");
    } finally {
      setGeneratingDoc(false);
    }
  }

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Multimedia Studio</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        <Text style={styles.sectionLabel}>GENERATE IMAGE</Text>
        <Card style={{ gap: spacing.sm }}>
          <Text style={styles.cardHint}>OpenAI · Google Imagen · Replicate · Stability AI · Fal.ai</Text>
          <TextInput style={[styles.input, { minHeight: 70, textAlignVertical: "top" }]} value={imgPrompt} onChangeText={setImgPrompt} placeholder="Contoh: Buat logo restoran modern" placeholderTextColor={colors.text.muted} multiline />
          <TextInput style={styles.input} value={imgStyle} onChangeText={setImgStyle} placeholder="Style (opsional, mis. minimalist)" placeholderTextColor={colors.text.muted} />
          <Text style={styles.fieldLabel}>Ukuran</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
            {SIZES.map((s) => (
              <Pressable key={s} onPress={() => setImgSize(s)} style={[styles.pill, imgSize === s && styles.pillActive]}>
                <Text style={[styles.pillText, imgSize === s && styles.pillTextActive]}>{s}</Text>
              </Pressable>
            ))}
          </ScrollView>
          <Text style={styles.fieldLabel}>Provider</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
            {IMAGE_PROVIDERS.map((p) => (
              <Pressable key={p.value} onPress={() => setImgProvider(p.value)} style={[styles.pill, imgProvider === p.value && styles.pillActive]}>
                <Text style={[styles.pillText, imgProvider === p.value && styles.pillTextActive]}>{p.label}</Text>
              </Pressable>
            ))}
          </ScrollView>
          {generatingImg ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
            <Pressable style={styles.primaryBtn} onPress={generateImage}><Text style={styles.primaryBtnText}>Generate Image</Text></Pressable>
          )}
          {lastImage ? (
            <View style={{ gap: spacing.sm }}>
              <Image source={{ uri: mediaUrl(lastImage.image_url) }} style={styles.previewImage} resizeMode="cover" />
              <Text style={styles.cardHint}>Provider: {lastImage.provider} · {lastImage.generation_time}s</Text>
              <Pressable style={styles.outlineBtn} onPress={() => Linking.openURL(mediaUrl(lastImage.image_url))}>
                <Text style={styles.outlineBtnText}>Buka / Download</Text>
              </Pressable>
            </View>
          ) : null}
        </Card>

        <Text style={styles.sectionLabel}>ANALYZE IMAGE (VISION AI)</Text>
        <Card style={{ gap: spacing.sm }}>
          <Text style={styles.cardHint}>Deskripsi, OCR, analisis UI/dashboard, atau baca invoice/dokumen</Text>
          <Pressable style={styles.outlineBtn} onPress={pickImage}>
            <Text style={styles.outlineBtnText}>{pickedImage ? "Ganti Gambar" : "Pilih Gambar dari Galeri"}</Text>
          </Pressable>
          {pickedImage ? <Image source={{ uri: pickedImage.uri }} style={styles.previewImage} resizeMode="cover" /> : null}
          <TextInput style={styles.input} value={question} onChangeText={setQuestion} placeholder="Pertanyaan (opsional, mis. 'ada teks apa di gambar ini?')" placeholderTextColor={colors.text.muted} />
          <Text style={styles.fieldLabel}>Mode</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
            {ANALYZE_MODES.map((m) => (
              <Pressable key={m.value} onPress={() => setMode(m.value)} style={[styles.pill, mode === m.value && styles.pillActive]}>
                <Text style={[styles.pillText, mode === m.value && styles.pillTextActive]}>{m.label}</Text>
              </Pressable>
            ))}
          </ScrollView>
          {analyzing ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
            <Pressable style={styles.primaryBtn} onPress={analyzeImage}><Text style={styles.primaryBtnText}>Analyze Image</Text></Pressable>
          )}
          {lastAnalysis ? (
            <View style={styles.answerBox}>
              <Text style={styles.answerText}>{lastAnalysis.answer}</Text>
            </View>
          ) : null}
        </Card>

        <Text style={styles.sectionLabel}>GENERATE DOCUMENT</Text>
        <Card style={{ gap: spacing.sm }}>
          <Text style={styles.cardHint}>PDF · DOCX · XLSX · PPTX — AI menyusun outline otomatis</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
            {DOC_FORMATS.map((f) => (
              <Pressable key={f} onPress={() => setDocFormat(f)} style={[styles.pill, docFormat === f && styles.pillActive]}>
                <Text style={[styles.pillText, docFormat === f && styles.pillTextActive]}>{f.toUpperCase()}</Text>
              </Pressable>
            ))}
          </ScrollView>
          <TextInput style={[styles.input, { minHeight: 70, textAlignVertical: "top" }]} value={docPrompt} onChangeText={setDocPrompt} placeholder="Contoh: Buat laporan penjualan bulan ini dalam bentuk tabel" placeholderTextColor={colors.text.muted} multiline />
          {generatingDoc ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
            <Pressable style={styles.primaryBtn} onPress={generateDocument}><Text style={styles.primaryBtnText}>Generate Document</Text></Pressable>
          )}
          {lastDocument ? (
            <Pressable style={styles.primaryBtn} onPress={() => Linking.openURL(mediaUrl(lastDocument.file_url))}>
              <Text style={styles.primaryBtnText}>Download {lastDocument.format.toUpperCase()}: {lastDocument.title}</Text>
            </Pressable>
          ) : null}
        </Card>

        <Text style={styles.sectionLabel}>IMAGE HISTORY ({history.length})</Text>
        {history.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada riwayat. Generate atau analisis gambar untuk mulai mengisi riwayat.</Text></Card>
        ) : (
          <View style={styles.historyGrid}>
            {history.map((item) => (
              <View key={item.id} style={styles.historyItem}>
                {item.kind === "analyze" ? (
                  <View style={styles.historyAnalyzeBox}>
                    <MaterialCommunityIcons name="text-recognition" size={20} color={colors.brand.violet400} />
                  </View>
                ) : (
                  <Image source={{ uri: mediaUrl(item.image_url) }} style={styles.historyImage} resizeMode="cover" />
                )}
                <Text style={styles.historyPrompt} numberOfLines={2}>{item.prompt || (item.kind === "analyze" ? "Analyze" : "")}</Text>
                <Text style={styles.historyMeta}>{item.provider} · {formatDate(item.created_at)}</Text>
              </View>
            ))}
          </View>
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
  cardHint: { color: colors.text.faint, fontSize: 11 },
  fieldLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "600" },

  input: {
    backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, color: colors.text.primary, fontSize: 13,
  },
  pill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border },
  pillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  pillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  pillTextActive: { color: "#fff" },

  primaryBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 12, fontWeight: "700", textAlign: "center" },
  outlineBtn: { borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  outlineBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },

  previewImage: { width: "100%", aspectRatio: 1.3, borderRadius: radius.md, backgroundColor: colors.bg.cardAlt },
  answerBox: { backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md },
  answerText: { color: colors.text.body, fontSize: 12, lineHeight: 18 },

  historyGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  historyItem: { width: "31%", flexGrow: 1, gap: 4 },
  historyImage: { width: "100%", aspectRatio: 1, borderRadius: radius.sm, backgroundColor: colors.bg.cardAlt },
  historyAnalyzeBox: { width: "100%", aspectRatio: 1, borderRadius: radius.sm, backgroundColor: colors.bg.cardAlt, alignItems: "center", justifyContent: "center" },
  historyPrompt: { color: colors.text.faint, fontSize: 10 },
  historyMeta: { color: colors.text.faint, fontSize: 9 },
});
