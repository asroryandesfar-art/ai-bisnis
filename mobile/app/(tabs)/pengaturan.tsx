import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import Constants from "expo-constants";
import { useRouter } from "expo-router";
import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge, BadgeKind } from "../../src/components/Badge";
import { Card } from "../../src/components/Card";
import { ScreenHeader } from "../../src/components/ScreenHeader";
import { api } from "../../src/api/client";
import { decodeJwtPayload } from "../../src/auth/jwt";
import { tokenStore } from "../../src/auth/tokenStore";
import { colors } from "../../src/theme/colors";
import { radius, spacing } from "../../src/theme/spacing";

const API_BASE = process.env.EXPO_PUBLIC_API_BASE || "https://api.botnesia.uk";

// Same 5 system roles as bn_platform/rbac.py's SYSTEM_ROLE_PERMISSIONS --
// mapped to human Indonesian labels + a badge tone. `roles` on a team member
// is an array of these keys; we show the highest-privilege one it contains.
const ROLE_LABEL: Record<string, { label: string; kind: BadgeKind }> = {
  owner: { label: "Pemilik", kind: "success" },
  admin: { label: "Admin", kind: "warning" },
  manager: { label: "Manajer", kind: "neutral" },
  agent: { label: "Agen", kind: "neutral" },
  viewer: { label: "Pengamat", kind: "neutral" },
};
const ROLE_PRIORITY = ["owner", "admin", "manager", "agent", "viewer"];

const PLAN_LABEL: Record<string, string> = {
  free: "Free", starter: "Starter", growth: "Growth", pro: "Pro",
  business: "Business", scale: "Scale", enterprise: "Enterprise",
};

function primaryRole(roles: string[] | undefined): string | null {
  if (!roles || !roles.length) return null;
  for (const key of ROLE_PRIORITY) if (roles.includes(key)) return key;
  return roles[0];
}

type Profile = {
  userName: string;
  email: string;
  roleKey: string | null;
  orgName: string;
  plan: string;
  billingStatus: string;
  memberCount: number;
  aiMode: string;
  aiModel: string | null;
  kbDocCount: number | null;
};

type Health = { db: boolean; schema: boolean; aiConfigured: boolean; aiModel: string | null };
type GmailStatus = { connected: boolean; email: string | null };

export default function Pengaturan() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [gmail, setGmail] = useState<GmailStatus | null>(null);
  const [defaultBotId, setDefaultBotId] = useState<string | null>(null);
  const [settingsBusy, setSettingsBusy] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const token = await tokenStore.get();
      const payload = token ? decodeJwtPayload(token) : {};

      const [orgRes, teamRes, kbRes, healthRes, integrationsRes, botsRes] = await Promise.allSettled([
        api.org(), api.team(), api.knowledgeSources(), api.health(), api.integrations(), api.bots(),
      ]);
      const org: any = orgRes.status === "fulfilled" ? orgRes.value : {};
      const team: any = teamRes.status === "fulfilled" ? teamRes.value : {};
      const teamList: any[] = team?.team || team || [];
      const me = teamList.find((m) => String(m.id) === String(payload.sub));
      const kb: any = kbRes.status === "fulfilled" ? kbRes.value : null;

      setProfile({
        userName: me?.full_name || me?.email || "Workspace Admin",
        email: me?.email || "-",
        roleKey: primaryRole(me?.roles),
        orgName: org?.name || "BotNesia",
        plan: org?.plan || "free",
        billingStatus: org?.billing_status || "active",
        memberCount: teamList.length,
        aiMode: org?.ai?.effective_mode || "cloud",
        aiModel: org?.ai?.cloud_model || null,
        kbDocCount: kb ? (kb.sources?.length ?? null) : null,
      });

      if (healthRes.status === "fulfilled") {
        const h: any = healthRes.value;
        setHealth({ db: !!h.db, schema: !!h.schema, aiConfigured: !!h.ai?.configured, aiModel: h.ai?.model ?? null });
      }
      if (integrationsRes.status === "fulfilled") {
        const g = (integrationsRes.value as any).gmail || {};
        setGmail({ connected: !!g.connected, email: g.email ?? null });
      }
      if (botsRes.status === "fulfilled") {
        setDefaultBotId((botsRes.value as any[])[0]?.id ?? null);
      }
    } catch (e: any) {
      setError(e?.message || "Gagal memuat pengaturan.");
    }
  }, []);

  async function connectGmail() {
    setSettingsBusy("start");
    try {
      const res = await api.gmailStart();
      await Linking.openURL(res.auth_url);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memulai koneksi Gmail. Pastikan GMAIL_CLIENT_ID sudah dikonfigurasi.");
    } finally {
      setSettingsBusy(null);
    }
  }

  async function mapGmail() {
    if (!defaultBotId) {
      Alert.alert("Belum ada agen", "Buat agen dulu di tab Agen sebelum memetakan Gmail.");
      return;
    }
    setSettingsBusy("map");
    try {
      await api.gmailMapBot(defaultBotId);
      Alert.alert("Berhasil", "Gmail dipetakan ke agen pertama Anda.");
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memetakan Gmail ke agen.");
    } finally {
      setSettingsBusy(null);
    }
  }

  async function pollGmail() {
    setSettingsBusy("poll");
    try {
      const res = await api.gmailPoll();
      Alert.alert("Selesai", `Gmail poll selesai: ${res?.processed || 0} pesan diproses.`);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa polling Gmail sekarang.");
    } finally {
      setSettingsBusy(null);
    }
  }

  async function runSecurityScan() {
    setSettingsBusy("security-scan");
    try {
      const res = await api.securityScan();
      Alert.alert("Scan selesai", `Skor keamanan: ${res.score}/100 · ${res.findings_count} temuan.`);
    } catch (e: any) {
      Alert.alert("Gagal scan", e?.message || "Tidak bisa menjalankan security scan (perlu izin audit.read).");
    } finally {
      setSettingsBusy(null);
    }
  }

  function disconnectGmail() {
    Alert.alert("Putuskan Gmail?", "Koneksi Gmail akan diputus dari workspace ini.", [
      { text: "Batal", style: "cancel" },
      {
        text: "Putuskan", style: "destructive",
        onPress: async () => {
          setSettingsBusy("disconnect");
          try {
            await api.deleteIntegration("gmail");
            await load();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa memutuskan koneksi Gmail.");
          } finally {
            setSettingsBusy(null);
          }
        },
      },
    ]);
  }

  useEffect(() => {
    load();
  }, [load]);

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  function confirmSignOut() {
    Alert.alert("Keluar", "Anda yakin ingin keluar dari akun ini?", [
      { text: "Batal", style: "cancel" },
      {
        text: "Keluar",
        style: "destructive",
        onPress: async () => {
          await tokenStore.clear();
          router.replace("/login");
        },
      },
    ]);
  }

  const role = profile?.roleKey ? ROLE_LABEL[profile.roleKey] : null;
  const appVersion = (Constants.expoConfig as any)?.version || "1.0.0";

  return (
    <View style={styles.flex}>
      <ScreenHeader title="Pengaturan" />
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

      {/* Profil */}
      <Card style={styles.profileCard}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{(profile?.userName || "W").charAt(0).toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.profileName} numberOfLines={1}>{profile?.userName ?? "..."}</Text>
          <Text style={styles.profileEmail} numberOfLines={1}>{profile?.email ?? ""}</Text>
        </View>
        {role ? <Badge label={role.label} kind={role.kind} /> : null}
      </Card>

      {/* Akun / Organisasi */}
      <Text style={styles.sectionLabel}>AKUN</Text>
      <Card style={styles.groupCard}>
        <Row icon="office-building-outline" label="Profil Perusahaan" value={profile?.orgName ?? "–"} />
        <Divider />
        <Row
          icon="star-outline"
          label="Paket"
          valueNode={
            <View style={styles.planRow}>
              <Text style={styles.rowValue}>{PLAN_LABEL[profile?.plan || "free"] || profile?.plan}</Text>
              {profile?.billingStatus && profile.billingStatus !== "active" ? (
                <Badge label={profile.billingStatus.toUpperCase()} kind="warning" />
              ) : null}
            </View>
          }
          onPress={() => router.push("/billing")}
          chevron
        />
        <Divider />
        <Row
          icon="account-group-outline"
          label="Kelola Tim"
          value={`${profile?.memberCount ?? 0} anggota`}
          onPress={() => router.push("/team")}
          chevron
        />
        <Divider />
        <Row
          icon="shield-lock-outline"
          label="Security Dashboard"
          onPress={() => router.push("/security")}
          chevron
        />
      </Card>

      {/* Mesin AI */}
      <Text style={styles.sectionLabel}>MESIN AI</Text>
      <Card style={styles.groupCard}>
        <Row
          icon="brain"
          label="Mode"
          valueNode={
            <Badge
              label={profile?.aiMode === "cloud" ? "CLOUD" : "OFFLINE"}
              kind={profile?.aiMode === "cloud" ? "success" : "neutral"}
            />
          }
        />
        {profile?.aiModel ? (
          <>
            <Divider />
            <Row icon="chip" label="Model" value={profile.aiModel} />
          </>
        ) : null}
      </Card>

      {/* Sistem */}
      <View style={styles.sectionHeadRow}>
        <Text style={styles.sectionLabel}>STATUS SISTEM</Text>
        <Pressable style={styles.scanBtn} onPress={runSecurityScan} disabled={settingsBusy === "security-scan"}>
          {settingsBusy === "security-scan" ? (
            <ActivityIndicator size="small" color={colors.brand.violet400} />
          ) : (
            <>
              <MaterialCommunityIcons name="radar" size={13} color={colors.brand.violet400} />
              <Text style={styles.scanBtnText}>Security Scan</Text>
            </>
          )}
        </Pressable>
      </View>
      <Card style={styles.groupCard}>
        <Row
          icon="server-outline"
          label="Backend"
          valueNode={<Badge label={health?.db ? "TERHUBUNG" : "TIDAK TERSEDIA"} kind={health?.db ? "success" : "danger"} />}
        />
        <Divider />
        <Row
          icon="database-check-outline"
          label="Postgres"
          valueNode={<Badge label={health?.schema ? "SCHEMA SIAP" : "MASALAH SCHEMA"} kind={health?.schema ? "success" : "danger"} />}
        />
        <Divider />
        <Row
          icon="creation"
          label="AI Provider"
          value={health?.aiModel || undefined}
          valueNode={!health?.aiModel ? <Badge label={health?.aiConfigured ? "SIAP" : "BELUM DIKONFIGURASI"} kind={health?.aiConfigured ? "success" : "danger"} /> : undefined}
        />
      </Card>

      {/* Integrasi */}
      <Text style={styles.sectionLabel}>INTEGRASI</Text>
      <Card style={styles.groupCard}>
        <Row
          icon="chat-processing-outline"
          label="Channels"
          value="WhatsApp, Telegram, IG, FB, Website"
          onPress={() => router.push("/channels")}
          chevron
        />
        <Divider />
        <Row
          icon="gmail"
          label="Gmail"
          value={gmail?.connected ? (gmail.email || "Terhubung") : "Belum terhubung"}
          valueNode={<Badge label={gmail?.connected ? "TERHUBUNG" : "TERPUTUS"} kind={gmail?.connected ? "success" : "neutral"} />}
        />
      </Card>
      <View style={styles.gmailActions}>
        <Pressable style={styles.gmailBtn} onPress={connectGmail} disabled={settingsBusy === "start"}>
          {settingsBusy === "start" ? <ActivityIndicator size="small" color="#fff" /> : <Text style={styles.gmailBtnTextPrimary}>{gmail?.connected ? "Sambungkan Ulang" : "Sambungkan Gmail"}</Text>}
        </Pressable>
        {gmail?.connected ? (
          <>
            <Pressable style={styles.gmailBtnOutline} onPress={mapGmail} disabled={settingsBusy === "map"}>
              {settingsBusy === "map" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : <Text style={styles.gmailBtnText}>Petakan Agen</Text>}
            </Pressable>
            <Pressable style={styles.gmailBtnOutline} onPress={pollGmail} disabled={settingsBusy === "poll"}>
              {settingsBusy === "poll" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : <Text style={styles.gmailBtnText}>Poll Sekarang</Text>}
            </Pressable>
            <Pressable style={styles.gmailBtnDanger} onPress={disconnectGmail} disabled={settingsBusy === "disconnect"}>
              {settingsBusy === "disconnect" ? <ActivityIndicator size="small" color={colors.status.danger} /> : <Text style={styles.gmailBtnTextDanger}>Putuskan</Text>}
            </Pressable>
          </>
        ) : null}
      </View>

      {/* Platform */}
      <Text style={styles.sectionLabel}>PLATFORM</Text>
      <Card style={styles.groupCard}>
        <Row
          icon="database-outline"
          label="Knowledge Base"
          value={profile?.kbDocCount != null ? `${profile.kbDocCount} dokumen` : "–"}
          onPress={() => router.push("/knowledge")}
          chevron
        />
      </Card>

      {/* Aplikasi */}
      <Text style={styles.sectionLabel}>APLIKASI</Text>
      <Card style={styles.groupCard}>
        <Row icon="server-network" label="Server API" value={API_BASE.replace(/^https?:\/\//, "")} />
        <Divider />
        <Row
          icon="shield-lock-outline"
          label="Kebijakan Privasi"
          onPress={() => Linking.openURL("https://botnesia.uk")}
          chevron
        />
        <Divider />
        <Row icon="information-outline" label="Versi Aplikasi" value={`v${appVersion}`} />
      </Card>

      <Pressable style={styles.signOut} onPress={confirmSignOut}>
        <Ionicons name="log-out-outline" size={18} color={colors.status.danger} />
        <Text style={styles.signOutText}>Keluar</Text>
      </Pressable>

      <Text style={styles.footer}>BotNesia v{appVersion} · © {new Date().getFullYear()} BotNesia Technologies</Text>
      </ScrollView>
    </View>
  );
}

function Row({
  icon,
  label,
  value,
  valueNode,
  onPress,
  chevron,
}: {
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  label: string;
  value?: string;
  valueNode?: ReactNode;
  onPress?: () => void;
  chevron?: boolean;
}) {
  const content = (
    <View style={styles.row}>
      <View style={styles.rowIcon}>
        <MaterialCommunityIcons name={icon} size={18} color={colors.brand.violet400} />
      </View>
      <Text style={styles.rowLabel}>{label}</Text>
      <View style={styles.rowRight}>
        {valueNode ? valueNode : value ? <Text style={styles.rowValue} numberOfLines={1}>{value}</Text> : null}
        {chevron ? <Ionicons name="chevron-forward" size={16} color={colors.text.faint} /> : null}
      </View>
    </View>
  );
  return onPress ? <Pressable onPress={onPress}>{content}</Pressable> : content;
}

function Divider() {
  return <View style={styles.divider} />;
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  container: { padding: spacing.lg, paddingTop: 0, gap: spacing.md, paddingBottom: spacing.xxl },
  profileCard: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  avatar: {
    width: 52, height: 52, borderRadius: radius.md, backgroundColor: colors.brand.violet600,
    alignItems: "center", justifyContent: "center",
  },
  avatarText: { color: "#fff", fontWeight: "800", fontSize: 20 },
  profileName: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  profileEmail: { color: colors.text.muted, fontSize: 12, marginTop: 2 },
  sectionLabel: {
    color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5,
    marginTop: spacing.md, marginBottom: spacing.xs,
  },
  sectionHeadRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.md },
  scanBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: spacing.sm, paddingVertical: 4 },
  scanBtnText: { color: colors.brand.violet400, fontSize: 11, fontWeight: "700" },
  groupCard: { padding: 0 },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingVertical: spacing.md + 2, paddingHorizontal: spacing.lg,
  },
  rowIcon: {
    width: 32, height: 32, borderRadius: radius.sm, backgroundColor: "rgba(139,92,246,0.12)",
    alignItems: "center", justifyContent: "center",
  },
  rowLabel: { color: colors.text.body, fontSize: 14, fontWeight: "600", flex: 1 },
  rowRight: { flexDirection: "row", alignItems: "center", gap: spacing.sm, maxWidth: "55%" },
  rowValue: { color: colors.text.muted, fontSize: 13 },
  planRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  divider: { height: 1, backgroundColor: colors.bg.border, marginLeft: spacing.lg + 32 + spacing.md },
  gmailActions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  gmailBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, alignItems: "center", justifyContent: "center" },
  gmailBtnTextPrimary: { color: "#fff", fontSize: 12, fontWeight: "700" },
  gmailBtnOutline: { borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.card, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, alignItems: "center", justifyContent: "center" },
  gmailBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },
  gmailBtnDanger: { borderWidth: 1, borderColor: colors.status.danger, backgroundColor: colors.status.dangerBg, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, alignItems: "center", justifyContent: "center" },
  gmailBtnTextDanger: { color: colors.status.danger, fontSize: 12, fontWeight: "700" },
  signOut: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    marginTop: spacing.xl, paddingVertical: spacing.lg, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.status.danger, backgroundColor: colors.status.dangerBg,
  },
  signOutText: { color: colors.status.danger, fontSize: 14, fontWeight: "700" },
  footer: { color: colors.text.faint, fontSize: 11, textAlign: "center", marginTop: spacing.lg },
});
