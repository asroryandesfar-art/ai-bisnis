import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import Constants from "expo-constants";
import { useRouter } from "expo-router";
import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { Alert, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge, BadgeKind } from "../../src/components/Badge";
import { Card } from "../../src/components/Card";
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

export default function Pengaturan() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const token = await tokenStore.get();
      const payload = token ? decodeJwtPayload(token) : {};

      const [orgRes, teamRes, kbRes] = await Promise.allSettled([api.org(), api.team(), api.knowledgeSources()]);
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
    } catch (e: any) {
      setError(e?.message || "Gagal memuat pengaturan.");
    }
  }, []);

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
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.container}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
    >
      <Text style={styles.screenTitle}>Pengaturan</Text>

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
        <Row icon="account-group-outline" label="Kelola Tim" value={`${profile?.memberCount ?? 0} anggota`} />
        <Divider />
        <Row icon="shield-lock-outline" label="Keamanan & Password" comingSoon />
      </Card>

      {/* Preferensi -- no backend support yet (no push-notification infra, no
          biometric-auth wiring, no auto-approve-threshold setting), shown
          disabled with a "Segera hadir" badge rather than faking a working
          toggle -- per explicit user direction 2026-07-03. */}
      <Text style={styles.sectionLabel}>PREFERENSI</Text>
      <Card style={styles.groupCard}>
        <Row icon="bell-outline" label="Notifikasi Push" comingSoon />
        <Divider />
        <Row icon="fingerprint" label="Biometrik / Face ID" comingSoon />
        <Divider />
        <Row icon="check-circle-outline" label="Auto-Approve Transaksi Kecil" comingSoon />
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
  );
}

function Row({
  icon,
  label,
  value,
  valueNode,
  onPress,
  chevron,
  comingSoon,
}: {
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  label: string;
  value?: string;
  valueNode?: ReactNode;
  onPress?: () => void;
  chevron?: boolean;
  comingSoon?: boolean;
}) {
  const content = (
    <View style={[styles.row, comingSoon && styles.rowDisabled]}>
      <View style={styles.rowIcon}>
        <MaterialCommunityIcons name={icon} size={18} color={comingSoon ? colors.text.faint : colors.brand.violet400} />
      </View>
      <Text style={styles.rowLabel}>{label}</Text>
      <View style={styles.rowRight}>
        {comingSoon ? (
          <Badge label="SEGERA" kind="neutral" />
        ) : valueNode ? (
          valueNode
        ) : value ? (
          <Text style={styles.rowValue} numberOfLines={1}>{value}</Text>
        ) : null}
        {chevron && !comingSoon ? <Ionicons name="chevron-forward" size={16} color={colors.text.faint} /> : null}
      </View>
    </View>
  );
  return onPress && !comingSoon ? <Pressable onPress={onPress}>{content}</Pressable> : content;
}

function Divider() {
  return <View style={styles.divider} />;
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  container: { padding: spacing.lg, paddingTop: spacing.xl, gap: spacing.md, paddingBottom: spacing.xxl },
  screenTitle: { color: colors.text.primary, fontSize: 22, fontWeight: "800", marginBottom: spacing.xs },
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
  groupCard: { padding: 0 },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingVertical: spacing.md + 2, paddingHorizontal: spacing.lg,
  },
  rowIcon: {
    width: 32, height: 32, borderRadius: radius.sm, backgroundColor: "rgba(139,92,246,0.12)",
    alignItems: "center", justifyContent: "center",
  },
  rowDisabled: { opacity: 0.55 },
  rowLabel: { color: colors.text.body, fontSize: 14, fontWeight: "600", flex: 1 },
  rowRight: { flexDirection: "row", alignItems: "center", gap: spacing.sm, maxWidth: "55%" },
  rowValue: { color: colors.text.muted, fontSize: 13 },
  planRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  divider: { height: 1, backgroundColor: colors.bg.border, marginLeft: spacing.lg + 32 + spacing.md },
  signOut: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    marginTop: spacing.xl, paddingVertical: spacing.lg, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.status.danger, backgroundColor: colors.status.dangerBg,
  },
  signOutText: { color: colors.status.danger, fontSize: 14, fontWeight: "700" },
  footer: { color: colors.text.faint, fontSize: 11, textAlign: "center", marginTop: spacing.lg },
});
