import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
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
function timeAgo(iso: string | null) {
  if (!iso) return "—";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "baru saja";
  if (mins < 60) return `${mins} menit lalu`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h} jam lalu`;
  return `${Math.floor(h / 24)} hari lalu`;
}

const SEVERITY_KIND: Record<string, BadgeKind> = {
  critical: "danger", high: "danger", medium: "warning", low: "neutral",
};

export default function SecurityDashboard() {
  const router = useRouter();
  const [dash, setDash] = useState<any>(null);
  const [riskAlerts, setRiskAlerts] = useState<any[]>([]);
  const [reports, setReports] = useState<any[]>([]);
  const [lastScan, setLastScan] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showApiKeyForm, setShowApiKeyForm] = useState(false);
  const [apiKeyName, setApiKeyName] = useState("");

  const load = useCallback(async () => {
    try {
      setError(null);
      const [dashRes, alertsRes, reportsRes] = await Promise.allSettled([
        api.securityDashboard(), api.securityRiskAlerts({ status_filter: "open", limit: 50 }), api.securityReports({ limit: 10 }),
      ]);
      if (dashRes.status === "fulfilled") setDash(dashRes.value);
      else setError((dashRes as any).reason?.message || "Gagal memuat security dashboard (perlu izin audit.read).");
      setRiskAlerts(alertsRes.status === "fulfilled" ? alertsRes.value.alerts || [] : []);
      setReports(reportsRes.status === "fulfilled" ? reportsRes.value.reports || [] : []);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat security dashboard.");
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

  async function runScan() {
    setBusy("scan");
    try {
      const res = await api.securityScan();
      setLastScan(res);
      Alert.alert("Scan selesai", `Skor: ${res.score}/100 · ${res.findings_count} temuan.`);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menjalankan scan.");
    } finally {
      setBusy(null);
    }
  }

  async function scanAndAlert() {
    setBusy("scan-alert");
    try {
      const res = await api.securityScanAndAlert();
      Alert.alert("Scan & Alert selesai", `${res.alerts_created?.length ?? 0} alert baru dibuat.`);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menjalankan scan & alert.");
    } finally {
      setBusy(null);
    }
  }

  async function generateReport(type: "weekly" | "monthly") {
    setBusy(`report-${type}`);
    try {
      await api.generateSecurityReport(type);
      await load();
      Alert.alert("Berhasil", `Laporan ${type === "weekly" ? "mingguan" : "bulanan"} dibuat.`);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa membuat laporan.");
    } finally {
      setBusy(null);
    }
  }

  async function updateAlert(id: string, status: string) {
    setBusy(id);
    try {
      await api.updateSecurityRiskAlert(id, status);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memperbarui alert.");
    } finally {
      setBusy(null);
    }
  }

  function revokeSession(id: string) {
    Alert.alert("Cabut sesi?", "Pengguna ini akan otomatis logout.", [
      { text: "Batal", style: "cancel" },
      {
        text: "Cabut", style: "destructive",
        onPress: async () => {
          setBusy(id);
          try {
            await api.revokeSecuritySession(id);
            await load();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa mencabut sesi ini.");
          } finally {
            setBusy(null);
          }
        },
      },
    ]);
  }

  async function createApiKey() {
    if (!apiKeyName.trim()) {
      Alert.alert("Lengkapi form", "Isi nama API key.");
      return;
    }
    setBusy("create-key");
    try {
      const res = await api.createApiKey({ name: apiKeyName.trim() });
      setApiKeyName("");
      setShowApiKeyForm(false);
      await load();
      Alert.alert("API key dibuat", `Simpan sekarang, hanya ditampilkan sekali:\n\n${res.key}`);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa membuat API key (mungkin butuh plan Scale).");
    } finally {
      setBusy(null);
    }
  }

  function rotateKey(id: string) {
    Alert.alert("Rotasi API key?", "Key lama langsung tidak berlaku.", [
      { text: "Batal", style: "cancel" },
      {
        text: "Rotasi",
        onPress: async () => {
          setBusy(id);
          try {
            const res = await api.rotateApiKey(id);
            await load();
            Alert.alert("Key baru dibuat", `Simpan sekarang, hanya ditampilkan sekali:\n\n${res.key}`);
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa rotasi key ini.");
          } finally {
            setBusy(null);
          }
        },
      },
    ]);
  }

  function revokeKey(id: string) {
    Alert.alert("Cabut API key?", "Key ini akan langsung tidak berlaku.", [
      { text: "Batal", style: "cancel" },
      {
        text: "Cabut", style: "destructive",
        onPress: async () => {
          setBusy(id);
          try {
            await api.revokeApiKey(id);
            await load();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa mencabut key ini.");
          } finally {
            setBusy(null);
          }
        },
      },
    ]);
  }

  if (error && !dash) {
    return (
      <View style={styles.flex}>
        <View style={styles.topBar}>
          <Pressable style={styles.iconBtn} onPress={() => router.back()}>
            <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
          </Pressable>
          <Text style={styles.topTitle}>Security Dashboard</Text>
          <View style={{ width: 32 }} />
        </View>
        <View style={{ padding: spacing.lg }}>
          <Card style={{ borderColor: colors.status.danger }}>
            <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
          </Card>
        </View>
      </View>
    );
  }

  const riskLevel = dash?.risk_level || "—";
  const riskKind: BadgeKind = riskLevel === "low" ? "success" : riskLevel === "medium" ? "warning" : "danger";
  const criticalOpen = dash?.open_security_alerts_by_severity?.critical || 0;

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Security Dashboard</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
      >
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.actionRow}>
          <ActionChip label="Run Scan" busy={busy === "scan"} onPress={runScan} primary />
          <ActionChip label="Scan & Alert" busy={busy === "scan-alert"} onPress={scanAndAlert} />
          <ActionChip label="Laporan Mingguan" busy={busy === "report-weekly"} onPress={() => generateReport("weekly")} />
          <ActionChip label="Laporan Bulanan" busy={busy === "report-monthly"} onPress={() => generateReport("monthly")} />
        </ScrollView>

        <View style={styles.kpiGrid}>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Security Score</Text>
            <Text style={styles.kpiValue}>{lastScan ? `${lastScan.score}/100` : dash?.score != null ? `${dash.score}/100` : "—"}</Text>
          </View>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Risk Level</Text>
            <Badge label={riskLevel.toUpperCase()} kind={riskKind} />
          </View>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Open Alerts</Text>
            <Text style={styles.kpiValue}>{riskAlerts.length}</Text>
            <Text style={styles.kpiSub}>{criticalOpen} critical</Text>
          </View>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Login Mencurigakan</Text>
            <Text style={styles.kpiValue}>{dash?.suspicious_sessions_count ?? 0}</Text>
            <Text style={styles.kpiSub}>30 hari</Text>
          </View>
        </View>

        {lastScan?.findings?.length ? (
          <>
            <Text style={styles.sectionLabel}>TEMUAN SCAN TERBARU</Text>
            <Card style={{ gap: spacing.sm }}>
              {lastScan.findings.map((f: any, i: number) => (
                <View key={i} style={styles.findingRow}>
                  <Badge label={f.severity.toUpperCase()} kind={SEVERITY_KIND[f.severity] || "neutral"} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.itemTitle}>{f.title}</Text>
                    <Text style={styles.itemDesc}>{f.recommendation}</Text>
                  </View>
                </View>
              ))}
            </Card>
          </>
        ) : null}

        <Text style={styles.sectionLabel}>RISK ALERTS ({riskAlerts.length})</Text>
        {riskAlerts.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Tidak ada alert terbuka.</Text></Card>
        ) : (
          riskAlerts.map((a) => (
            <Card key={a.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Badge label={a.severity.toUpperCase()} kind={SEVERITY_KIND[a.severity] || "neutral"} />
                <Text style={styles.itemMeta}>{timeAgo(a.created_at)}</Text>
              </View>
              <Text style={styles.itemTitle}>{(a.category || "").replace(/_/g, " ")}</Text>
              <Text style={styles.itemDesc}>{a.message}</Text>
              {busy === a.id ? (
                <ActivityIndicator size="small" color={colors.brand.violet400} />
              ) : (
                <View style={styles.actionRowInline}>
                  <Pressable style={styles.outlineBtn} onPress={() => updateAlert(a.id, "acknowledged")}>
                    <Text style={styles.outlineBtnText}>Acknowledge</Text>
                  </Pressable>
                  <Pressable style={styles.primaryBtnSm} onPress={() => updateAlert(a.id, "resolved")}>
                    <Text style={styles.primaryBtnText}>Resolve</Text>
                  </Pressable>
                </View>
              )}
            </Card>
          ))
        )}

        <Text style={styles.sectionLabel}>LAPORAN KEAMANAN ({reports.length})</Text>
        {reports.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada laporan.</Text></Card>
        ) : (
          reports.map((r) => (
            <Card key={r.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Badge label={r.report_type} kind="neutral" />
                <Text style={styles.itemMeta}>{timeAgo(r.created_at)}</Text>
              </View>
              <Text style={styles.itemDesc} numberOfLines={3}>{r.summary}</Text>
            </Card>
          ))
        )}

        <Text style={styles.sectionLabel}>SESI AKTIF ({dash?.active_sessions?.length ?? 0})</Text>
        {(dash?.active_sessions || []).length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Tidak ada sesi aktif.</Text></Card>
        ) : (
          (dash.active_sessions || []).map((s: any) => (
            <Card key={s.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Text style={styles.itemTitle} numberOfLines={1}>{s.user_email}</Text>
                <Badge label={s.is_suspicious ? "MENCURIGAKAN" : "NORMAL"} kind={s.is_suspicious ? "danger" : "success"} />
              </View>
              <Text style={styles.itemMeta}>{s.ip_address || "—"} · Terlihat {timeAgo(s.last_seen_at)}</Text>
              {busy === s.id ? (
                <ActivityIndicator size="small" color={colors.status.danger} />
              ) : (
                <Pressable style={styles.dangerBtn} onPress={() => revokeSession(s.id)}>
                  <Text style={styles.dangerBtnText}>Cabut Sesi</Text>
                </Pressable>
              )}
            </Card>
          ))
        )}

        <Text style={styles.sectionLabel}>API KEYS ({dash?.api_keys?.length ?? 0})</Text>
        <Pressable style={styles.outlineBtn} onPress={() => setShowApiKeyForm((v) => !v)}>
          <Text style={styles.outlineBtnText}>{showApiKeyForm ? "Batal" : "+ Buat API Key Baru"}</Text>
        </Pressable>
        {showApiKeyForm ? (
          <Card style={{ gap: spacing.sm }}>
            <TextInput style={styles.input} value={apiKeyName} onChangeText={setApiKeyName} placeholder="Nama key (mis. Integration server)" placeholderTextColor={colors.text.muted} />
            {busy === "create-key" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
              <Pressable style={styles.primaryBtnSm} onPress={createApiKey}>
                <Text style={styles.primaryBtnText}>Buat Key</Text>
              </Pressable>
            )}
            <Text style={styles.itemMeta}>Catatan: API key hanya tersedia untuk paket Scale.</Text>
          </Card>
        ) : null}
        {(dash?.api_keys || []).map((k: any) => (
          <Card key={k.id} style={styles.itemCard}>
            <View style={styles.itemHead}>
              <Text style={styles.itemTitle} numberOfLines={1}>{k.name}</Text>
              <Badge label={k.is_active ? "AKTIF" : "DICABUT"} kind={k.is_active ? "success" : "neutral"} />
            </View>
            <Text style={styles.itemMeta}>{k.key_prefix}… · {num(k.usage_count)} pemakaian · {k.expires_at ? formatDate(k.expires_at) : "Tidak pernah kedaluwarsa"}</Text>
            {k.is_active ? (
              busy === k.id ? (
                <ActivityIndicator size="small" color={colors.brand.violet400} />
              ) : (
                <View style={styles.actionRowInline}>
                  <Pressable style={styles.outlineBtn} onPress={() => rotateKey(k.id)}>
                    <Text style={styles.outlineBtnText}>Rotasi</Text>
                  </Pressable>
                  <Pressable style={styles.dangerBtnFlex} onPress={() => revokeKey(k.id)}>
                    <Text style={styles.dangerBtnText}>Cabut</Text>
                  </Pressable>
                </View>
              )
            ) : null}
          </Card>
        ))}

        <Text style={styles.sectionLabel}>SECURITY EVENTS</Text>
        {(dash?.security_events || []).length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Tidak ada event keamanan.</Text></Card>
        ) : (
          <Card style={{ padding: 0 }}>
            {dash.security_events.map((ev: any, i: number) => (
              <View key={ev.id} style={[styles.logRow, i > 0 && styles.logRowBorder]}>
                <MaterialCommunityIcons name="alert-circle-outline" size={16} color={colors.status.danger} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.logAction}>{ev.action}</Text>
                  <Text style={styles.itemMeta}>{ev.actor_email || "system"} · {ev.ip_address || "—"}</Text>
                </View>
                <Text style={styles.itemMeta}>{formatDate(ev.created_at)}</Text>
              </View>
            ))}
          </Card>
        )}

        <Text style={styles.sectionLabel}>AUDIT LOG</Text>
        {(dash?.audit_logs || []).length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada entri audit.</Text></Card>
        ) : (
          <Card style={{ padding: 0 }}>
            {dash.audit_logs.map((log: any, i: number) => (
              <View key={log.id} style={[styles.logRow, i > 0 && styles.logRowBorder]}>
                <MaterialCommunityIcons name="clipboard-text-outline" size={16} color={colors.brand.violet400} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.logAction}>{log.action} · {log.resource_type}</Text>
                  <Text style={styles.itemMeta}>{log.actor_email || "system"} · {log.ip_address || "—"}</Text>
                </View>
                <Text style={styles.itemMeta}>{formatDate(log.created_at)}</Text>
              </View>
            ))}
          </Card>
        )}
      </ScrollView>
    </View>
  );
}

function ActionChip({ label, onPress, busy, primary }: { label: string; onPress: () => void; busy?: boolean; primary?: boolean }) {
  return (
    <Pressable style={[styles.chip, primary && styles.chipPrimary, busy && { opacity: 0.6 }]} onPress={onPress} disabled={busy}>
      {busy ? <ActivityIndicator size="small" color={primary ? "#fff" : colors.brand.violet400} /> : (
        <Text style={[styles.chipText, primary && { color: "#fff" }]}>{label}</Text>
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
  topTitle: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  container: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },

  actionRow: { gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, borderRadius: radius.full, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border },
  chipPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  chipText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },

  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpiCard: { width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 4 },
  kpiLabel: { color: colors.text.faint, fontSize: 10 },
  kpiValue: { color: colors.text.primary, fontSize: 18, fontWeight: "800" },
  kpiSub: { color: colors.text.muted, fontSize: 10 },

  findingRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  itemCard: { gap: spacing.xs },
  itemHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  itemTitle: { color: colors.text.primary, fontSize: 13, fontWeight: "700", flex: 1, textTransform: "capitalize" },
  itemDesc: { color: colors.text.muted, fontSize: 12, lineHeight: 17 },
  itemMeta: { color: colors.text.faint, fontSize: 11 },

  actionRowInline: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  primaryBtnSm: { flex: 1, backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  outlineBtn: { flex: 1, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  outlineBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },
  dangerBtn: { borderWidth: 1, borderColor: colors.status.danger, backgroundColor: colors.status.dangerBg, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center", marginTop: spacing.xs },
  dangerBtnFlex: { flex: 1, borderWidth: 1, borderColor: colors.status.danger, backgroundColor: colors.status.dangerBg, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  dangerBtnText: { color: colors.status.danger, fontSize: 12, fontWeight: "700" },

  input: {
    backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, color: colors.text.primary, fontSize: 13,
  },

  logRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md },
  logRowBorder: { borderTopWidth: 1, borderTopColor: colors.bg.border },
  logAction: { color: colors.text.primary, fontSize: 12, fontWeight: "700", textTransform: "capitalize" },
});
