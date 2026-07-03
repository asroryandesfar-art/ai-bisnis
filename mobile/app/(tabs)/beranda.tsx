import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Card } from "../../src/components/Card";
import { api } from "../../src/api/client";
import { decodeJwtPayload } from "../../src/auth/jwt";
import { tokenStore } from "../../src/auth/tokenStore";
import { colors } from "../../src/theme/colors";
import { radius, spacing } from "../../src/theme/spacing";

function greetingForNow() {
  const h = new Date().getHours();
  if (h < 11) return "Selamat pagi";
  if (h < 15) return "Selamat siang";
  if (h < 19) return "Selamat sore";
  return "Selamat malam";
}

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}
function pick<T = any>(r: PromiseSettledResult<T>, fallback: T): T {
  return r.status === "fulfilled" ? r.value : fallback;
}

type Dash = {
  userName: string;
  orgName: string;
  agentsActive: number;
  agentLimit: number; // -1 = unlimited
  tasksDone: number;
  tasksFailed: number;
  jamHemat: number;
  automationPending: number;
  approvalPending: number;
};

export default function Beranda() {
  const router = useRouter();
  const [data, setData] = useState<Dash | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const token = await tokenStore.get();
      const payload = token ? decodeJwtPayload(token) : {};

      const [botsR, orgR, teamR, overviewR, wfR] = await Promise.allSettled([
        api.bots(),
        api.org(),
        api.team(),
        api.agentCenterOverview(),
        api.workforceDashboard(),
      ]);
      const bots: any[] = pick(botsR, [] as any[]);
      const org: any = pick(orgR, {});
      const team: any = pick(teamR, {});
      const overview: any = pick(overviewR, {});
      const workforce: any = pick(wfR, {});

      const teamList: any[] = team?.team || team || [];
      const me = teamList.find((m) => String(m.id) === String(payload.sub));

      const byStatus = overview?.execution_log?.by_status || {};
      const tasksDone = Number(byStatus.success || 0);
      const tasksFailed = Number(byStatus.failed || 0);
      const agentsActive = bots.filter((b) => b.status === "active").length;

      setData({
        userName: me?.full_name || me?.email || "Workspace Admin",
        orgName: org?.name || "BotNesia",
        agentsActive,
        agentLimit: org?.limits?.bot_limit ?? -1,
        tasksDone,
        tasksFailed,
        // "Jam Hemat" — no backend metric; transparent estimate: each completed
        // automated task ≈ 10 menit kerja manual yang dihemat.
        jamHemat: Math.round((tasksDone * 10) / 60),
        automationPending:
          Number(workforce?.by_status?.pending || 0) + Number(workforce?.by_status?.in_progress || 0),
        approvalPending:
          (overview?.computer_agent_pending_approval_count || 0) +
          (overview?.local_agent_pending_approval_count || 0) +
          Number(workforce?.pending_approval_count || 0),
      });
    } catch (e: any) {
      setError(e?.message || "Gagal memuat data dashboard.");
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

  const unlimited = data?.agentLimit === -1;
  const capacityPct =
    data && !unlimited && data.agentLimit > 0 ? Math.min(100, Math.round((data.agentsActive / data.agentLimit) * 100)) : 0;
  const slotsLeft = data && !unlimited ? Math.max(0, data.agentLimit - data.agentsActive) : null;
  const efficiency =
    data && data.tasksDone + data.tasksFailed > 0
      ? Math.round((data.tasksDone / (data.tasksDone + data.tasksFailed)) * 100)
      : null;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.container}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
    >
      {/* Header */}
      <View style={styles.brandRow}>
        <View style={styles.brandLeft}>
          <View style={styles.brandLogo}>
            <MaterialCommunityIcons name="robot-outline" size={18} color="#fff" />
          </View>
          <Text style={styles.brandName}>BotNesia</Text>
        </View>
        <Pressable style={styles.bellBtn} onPress={() => router.push("/notifikasi")}>
          <Ionicons name="notifications-outline" size={18} color={colors.text.body} />
          {data && data.approvalPending > 0 ? <View style={styles.notifDot} /> : null}
        </Pressable>
      </View>

      <View style={styles.greetRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.greeting}>{greetingForNow()} 👋</Text>
          <Text style={styles.userName}>{data?.userName ?? "..."}</Text>
        </View>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{(data?.userName || "W").charAt(0).toUpperCase()}</Text>
        </View>
      </View>

      {error ? (
        <Card style={{ borderColor: colors.status.danger }}>
          <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
        </Card>
      ) : null}

      {/* Workforce card */}
      <Card style={styles.workforceCard}>
        <View style={styles.workforceHead}>
          <Text style={styles.workforceLabel}>AI Workforce Aktif</Text>
          <View style={styles.liveBadge}>
            <View style={styles.liveDot} />
            <Text style={styles.liveText}>LIVE</Text>
          </View>
        </View>
        <View style={styles.workforceValueRow}>
          <Text style={styles.workforceValue}>{data?.agentsActive ?? "–"}</Text>
          <Text style={styles.workforceTotal}> / {unlimited ? "∞" : data?.agentLimit ?? "–"} agen</Text>
        </View>
        <View style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${capacityPct}%` }]} />
        </View>
        <View style={styles.workforceFootRow}>
          <Text style={styles.workforceFoot}>{unlimited ? "Kapasitas tak terbatas" : `${capacityPct}% kapasitas terpakai`}</Text>
          <Text style={styles.workforceFoot}>{slotsLeft != null ? `${slotsLeft} slot tersisa` : "—"}</Text>
        </View>
      </Card>

      {/* 3 stats */}
      <View style={styles.statsRow}>
        <Card style={styles.statCard}>
          <View style={[styles.statIcon, { backgroundColor: colors.status.warningBgStrong }]}>
            <MaterialCommunityIcons name="lightning-bolt" size={16} color={colors.status.warning} />
          </View>
          <Text style={styles.statLabel}>Tugas Selesai</Text>
          <Text style={styles.statValue}>{data ? num(data.tasksDone) : "–"}</Text>
          <Text style={styles.statSub}>hari ini</Text>
        </Card>
        <Card style={styles.statCard}>
          <View style={[styles.statIcon, { backgroundColor: colors.status.successBgStrong }]}>
            <MaterialCommunityIcons name="trending-up" size={16} color={colors.status.success} />
          </View>
          <Text style={styles.statLabel}>Efisiensi</Text>
          <Text style={styles.statValue}>{efficiency !== null ? `${efficiency}%` : "–"}</Text>
          <Text style={styles.statSub}>rasio sukses</Text>
        </Card>
        <Card style={styles.statCard}>
          <View style={[styles.statIcon, { backgroundColor: "rgba(139,92,246,0.15)" }]}>
            <MaterialCommunityIcons name="clock-outline" size={16} color={colors.brand.violet400} />
          </View>
          <Text style={styles.statLabel}>Jam Hemat</Text>
          <Text style={styles.statValue}>{data ? `${num(data.jamHemat)}h` : "–"}</Text>
          <Text style={styles.statSub}>estimasi</Text>
        </Card>
      </View>

      {/* Akses cepat */}
      <View style={styles.sectionHead}>
        <Text style={styles.sectionLabel}>AKSES CEPAT</Text>
      </View>
      <View style={styles.quickGrid}>
        <Quick icon="robot-outline" title="Daftar Agen AI" sub={`${data?.agentsActive ?? "–"} agen aktif`} onPress={() => router.push("/agen")} />
        <Quick icon="lightning-bolt" title="Otomatisasi" sub={`${data?.automationPending ?? "–"} berjalan`} tint={colors.status.warning} bg={colors.status.warningBgStrong} onPress={() => router.push("/tugas")} />
        <Quick icon="monitor-dashboard" title="Computer Agent" sub="Siap digunakan" onPress={() => router.push("/computer")} />
        <Quick icon="book-open-variant" title="Knowledge Base" sub="Dokumen & sumber" onPress={() => router.push("/knowledge")} />
      </View>

      <Pressable style={styles.approvalRow} onPress={() => router.push("/antrian")}>
        <View style={[styles.quickIcon, { backgroundColor: "rgba(139,92,246,0.12)" }]}>
          <MaterialCommunityIcons name="clock-alert-outline" size={18} color={colors.brand.violet400} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.quickTitle}>Antrian Izin</Text>
          <Text style={styles.quickSub}>{data?.approvalPending ?? "–"} menunggu persetujuan</Text>
        </View>
        <Ionicons name="chevron-forward" size={18} color={colors.text.faint} />
      </Pressable>
    </ScrollView>
  );
}

function Quick({
  icon, title, sub, onPress, tint, bg,
}: {
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  title: string; sub: string; onPress: () => void; tint?: string; bg?: string;
}) {
  return (
    <Pressable style={styles.quickCard} onPress={onPress}>
      <View style={[styles.quickIcon, bg ? { backgroundColor: bg } : null]}>
        <MaterialCommunityIcons name={icon} size={20} color={tint || colors.brand.violet400} />
      </View>
      <Text style={styles.quickTitle}>{title}</Text>
      <Text style={styles.quickSub}>{sub}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  container: { padding: spacing.lg, paddingTop: spacing.xl, gap: spacing.lg, paddingBottom: spacing.xxl },
  brandRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  brandLeft: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  brandLogo: { width: 34, height: 34, borderRadius: radius.md, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  brandName: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  bellBtn: {
    width: 38, height: 38, borderRadius: radius.md, backgroundColor: colors.bg.card,
    alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.bg.border,
  },
  notifDot: {
    position: "absolute", top: 8, right: 8, width: 8, height: 8, borderRadius: 4,
    backgroundColor: colors.status.danger, borderWidth: 1, borderColor: colors.bg.card,
  },
  greetRow: { flexDirection: "row", alignItems: "center" },
  greeting: { color: colors.text.muted, fontSize: 13 },
  userName: { color: colors.text.primary, fontSize: 22, fontWeight: "800", marginTop: 2 },
  avatar: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#fff", fontWeight: "800", fontSize: 16 },

  workforceCard: { gap: spacing.sm },
  workforceHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  workforceLabel: { color: colors.text.muted, fontSize: 12 },
  liveBadge: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.status.successBg, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.full },
  liveDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.status.success },
  liveText: { color: colors.status.success, fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  workforceValueRow: { flexDirection: "row", alignItems: "flex-end" },
  workforceValue: { color: colors.text.primary, fontSize: 34, fontWeight: "800" },
  workforceTotal: { color: colors.text.muted, fontSize: 14, marginBottom: 6 },
  progressTrack: { height: 6, borderRadius: 3, backgroundColor: colors.bg.border, overflow: "hidden", marginTop: spacing.xs },
  progressFill: { height: "100%", backgroundColor: colors.brand.violet500, borderRadius: 3 },
  workforceFootRow: { flexDirection: "row", justifyContent: "space-between" },
  workforceFoot: { color: colors.text.faint, fontSize: 11 },

  statsRow: { flexDirection: "row", gap: spacing.sm },
  statCard: { flex: 1, padding: spacing.md, gap: 2 },
  statIcon: { width: 28, height: 28, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  statLabel: { color: colors.text.muted, fontSize: 10, marginTop: 6 },
  statValue: { color: colors.text.primary, fontSize: 18, fontWeight: "800" },
  statSub: { color: colors.text.faint, fontSize: 9 },

  sectionHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  quickGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  quickCard: {
    width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.bg.border,
    padding: spacing.lg, gap: 4,
  },
  quickIcon: {
    width: 40, height: 40, borderRadius: radius.md, backgroundColor: "rgba(139,92,246,0.12)",
    alignItems: "center", justifyContent: "center", marginBottom: spacing.sm,
  },
  quickTitle: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  quickSub: { color: colors.text.muted, fontSize: 11 },
  approvalRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.bg.card,
    borderRadius: radius.lg, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.lg,
  },
});
