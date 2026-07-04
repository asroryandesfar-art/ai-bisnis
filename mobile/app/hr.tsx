import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

const STATUS_KIND: Record<string, BadgeKind> = {
  new: "warning", screened: "success", rejected: "danger", hired: "success", active: "success", inactive: "neutral",
};

export default function HRCenter() {
  const router = useRouter();
  const [dash, setDash] = useState<any>({});
  const [candidates, setCandidates] = useState<any[]>([]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [candFormOpen, setCandFormOpen] = useState(false);
  const [candName, setCandName] = useState("");
  const [candPosition, setCandPosition] = useState("");
  const [empFormOpen, setEmpFormOpen] = useState(false);
  const [empName, setEmpName] = useState("");
  const [empPosition, setEmpPosition] = useState("");
  const [scoreOpenId, setScoreOpenId] = useState<string | null>(null);
  const [scorePosition, setScorePosition] = useState("");
  const [evalOpenId, setEvalOpenId] = useState<string | null>(null);
  const [evalRole, setEvalRole] = useState("");
  const [evalNotes, setEvalNotes] = useState("");

  const load = useCallback(async () => {
    try {
      setError(null);
      const [dashRes, candRes, empRes] = await Promise.allSettled([
        api.hrDashboard(), api.hrCandidates(50), api.hrEmployees(50),
      ]);
      setDash(dashRes.status === "fulfilled" ? dashRes.value : {});
      setCandidates(candRes.status === "fulfilled" ? candRes.value.candidates || [] : []);
      setEmployees(empRes.status === "fulfilled" ? empRes.value.employees || [] : []);
      if (dashRes.status === "rejected") setError((dashRes as any).reason?.message || "Gagal memuat HR Center.");
    } catch (e: any) {
      setError(e?.message || "Gagal memuat HR Center.");
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function createCandidate() {
    if (!candName.trim()) {
      Alert.alert("Lengkapi form", "Nama kandidat wajib diisi.");
      return;
    }
    setBusy("new-candidate");
    try {
      await api.hrCreateCandidate({ name: candName.trim(), position_applied: candPosition.trim() || null });
      setCandFormOpen(false); setCandName(""); setCandPosition("");
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menambahkan kandidat.");
    } finally {
      setBusy(null);
    }
  }

  async function scoreCandidate(id: string) {
    if (!scorePosition.trim()) {
      Alert.alert("Lengkapi form", "Posisi yang dilamar wajib diisi untuk scoring AI.");
      return;
    }
    setBusy(id);
    try {
      await api.hrScoreCandidate(id, { position: scorePosition.trim() });
      setScoreOpenId(null); setScorePosition("");
      await load();
      Alert.alert("Berhasil", "Kandidat berhasil di-score AI.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa scoring kandidat ini.");
    } finally {
      setBusy(null);
    }
  }

  function deleteCandidate(id: string, name: string) {
    Alert.alert("Hapus kandidat?", name, [
      { text: "Batal", style: "cancel" },
      {
        text: "Hapus", style: "destructive",
        onPress: async () => {
          setBusy(id);
          try {
            await api.hrDeleteCandidate(id);
            await load();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa menghapus kandidat ini.");
          } finally {
            setBusy(null);
          }
        },
      },
    ]);
  }

  async function createEmployee() {
    if (!empName.trim()) {
      Alert.alert("Lengkapi form", "Nama karyawan wajib diisi.");
      return;
    }
    setBusy("new-employee");
    try {
      await api.hrCreateEmployee({ full_name: empName.trim(), position: empPosition.trim() || null });
      setEmpFormOpen(false); setEmpName(""); setEmpPosition("");
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menambahkan karyawan.");
    } finally {
      setBusy(null);
    }
  }

  async function generateEvaluation(id: string) {
    if (!evalRole.trim() || !evalNotes.trim()) {
      Alert.alert("Lengkapi form", "Role dan catatan performa wajib diisi.");
      return;
    }
    setBusy(id);
    try {
      await api.hrGenerateEvaluation(id, { role: evalRole.trim(), notes: evalNotes.trim() });
      setEvalOpenId(null); setEvalRole(""); setEvalNotes("");
      Alert.alert("Berhasil", "Draft evaluasi berhasil digenerate AI (belum final).");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa generate evaluasi.");
    } finally {
      setBusy(null);
    }
  }

  const candidatesActive = Object.values(dash.candidates_by_status || {}).reduce((a: number, b: any) => a + Number(b || 0), 0);

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>HR Center</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        <View style={styles.kpiGrid}>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Kandidat Baru</Text><Text style={styles.kpiValue}>{dash.candidates_by_status?.new ?? 0}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Screened</Text><Text style={styles.kpiValue}>{dash.candidates_by_status?.screened ?? 0}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Karyawan Aktif</Text><Text style={styles.kpiValue}>{dash.employees_by_status?.active ?? 0}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Avg Evaluasi 90d</Text><Text style={styles.kpiValue}>{dash.avg_evaluation_score_90d ?? "—"}</Text></View>
        </View>

        <Text style={styles.sectionLabel}>KANDIDAT ({candidates.length})</Text>
        <Pressable style={styles.outlineBtn} onPress={() => setCandFormOpen((v) => !v)}>
          <Text style={styles.outlineBtnText}>{candFormOpen ? "Batal" : "+ Kandidat Baru"}</Text>
        </Pressable>
        {candFormOpen ? (
          <Card style={{ gap: spacing.sm }}>
            <TextInput style={styles.input} value={candName} onChangeText={setCandName} placeholder="Nama kandidat" placeholderTextColor={colors.text.muted} />
            <TextInput style={styles.input} value={candPosition} onChangeText={setCandPosition} placeholder="Posisi yang dilamar" placeholderTextColor={colors.text.muted} />
            {busy === "new-candidate" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
              <Pressable style={styles.primaryBtn} onPress={createCandidate}><Text style={styles.primaryBtnText}>Tambah Kandidat</Text></Pressable>
            )}
          </Card>
        ) : null}
        {candidates.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada kandidat.</Text></Card>
        ) : (
          candidates.map((c) => (
            <Card key={c.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Text style={styles.itemTitle} numberOfLines={1}>{c.name}</Text>
                <Badge label={c.status.toUpperCase()} kind={STATUS_KIND[c.status] || "neutral"} />
              </View>
              <Text style={styles.itemMeta}>{c.position_applied || "—"}{c.score != null ? ` · Skor AI: ${c.score}` : ""}</Text>
              {busy === c.id ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                <View style={{ gap: spacing.sm }}>
                  <View style={styles.actionRow}>
                    <ActionBtn label="Score AI" onPress={() => setScoreOpenId(scoreOpenId === c.id ? null : c.id)} />
                    <ActionBtn label="Hapus" danger onPress={() => deleteCandidate(c.id, c.name)} />
                  </View>
                  {scoreOpenId === c.id ? (
                    <View style={{ gap: spacing.sm }}>
                      <TextInput style={styles.input} value={scorePosition} onChangeText={setScorePosition} placeholder="Posisi (untuk scoring AI)" placeholderTextColor={colors.text.muted} />
                      <Pressable style={styles.primaryBtn} onPress={() => scoreCandidate(c.id)}><Text style={styles.primaryBtnText}>Jalankan Scoring</Text></Pressable>
                    </View>
                  ) : null}
                </View>
              )}
            </Card>
          ))
        )}

        <Text style={styles.sectionLabel}>KARYAWAN ({employees.length})</Text>
        <Pressable style={styles.outlineBtn} onPress={() => setEmpFormOpen((v) => !v)}>
          <Text style={styles.outlineBtnText}>{empFormOpen ? "Batal" : "+ Karyawan Baru"}</Text>
        </Pressable>
        {empFormOpen ? (
          <Card style={{ gap: spacing.sm }}>
            <TextInput style={styles.input} value={empName} onChangeText={setEmpName} placeholder="Nama karyawan" placeholderTextColor={colors.text.muted} />
            <TextInput style={styles.input} value={empPosition} onChangeText={setEmpPosition} placeholder="Posisi/jabatan" placeholderTextColor={colors.text.muted} />
            {busy === "new-employee" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
              <Pressable style={styles.primaryBtn} onPress={createEmployee}><Text style={styles.primaryBtnText}>Tambah Karyawan</Text></Pressable>
            )}
          </Card>
        ) : null}
        {employees.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada karyawan.</Text></Card>
        ) : (
          employees.map((e) => (
            <Card key={e.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Text style={styles.itemTitle} numberOfLines={1}>{e.full_name}</Text>
                <Badge label={(e.status || "active").toUpperCase()} kind={STATUS_KIND[e.status] || "success"} />
              </View>
              <Text style={styles.itemMeta}>{e.position || "—"}{e.department ? ` · ${e.department}` : ""}</Text>
              {busy === e.id ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                <View style={{ gap: spacing.sm }}>
                  <ActionBtn label="Generate Evaluasi (AI)" onPress={() => setEvalOpenId(evalOpenId === e.id ? null : e.id)} />
                  {evalOpenId === e.id ? (
                    <View style={{ gap: spacing.sm }}>
                      <TextInput style={styles.input} value={evalRole} onChangeText={setEvalRole} placeholder="Role/jabatan saat ini" placeholderTextColor={colors.text.muted} />
                      <TextInput style={[styles.input, { minHeight: 60, textAlignVertical: "top" }]} value={evalNotes} onChangeText={setEvalNotes} placeholder="Catatan performa karyawan" placeholderTextColor={colors.text.muted} multiline />
                      <Pressable style={styles.primaryBtn} onPress={() => generateEvaluation(e.id)}><Text style={styles.primaryBtnText}>Generate Evaluasi</Text></Pressable>
                    </View>
                  ) : null}
                </View>
              )}
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
  actionRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  actionBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt },
  actionBtnPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  actionBtnDanger: { backgroundColor: colors.status.dangerBg, borderColor: colors.status.danger },
  actionBtnText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },
});
