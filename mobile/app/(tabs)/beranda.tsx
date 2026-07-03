import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Image, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge, BadgeKind } from "../../src/components/Badge";
import { Card } from "../../src/components/Card";
import { api } from "../../src/api/client";
import { decodeJwtPayload } from "../../src/auth/jwt";
import { tokenStore } from "../../src/auth/tokenStore";
import { colors } from "../../src/theme/colors";
import { radius, spacing } from "../../src/theme/spacing";
import { idr } from "../../src/utils/format";

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

// Mirrors web's renderDashboard() (frontend/app.js) business-health section
// -- same 6 endpoints, same field names, same opportunity/workforce-status
// derivation logic, just rendered with mobile's own Card/typography instead
// of copying the web's HTML/CSS. Kept as a separate state object from `Dash`
// above so this addition can't affect the existing (already stable) upper
// section of Beranda.
const HEALTH_LABEL: Record<string, { label: string; kind: BadgeKind }> = {
  healthy: { label: "SEHAT", kind: "success" },
  warning: { label: "PERLU PERHATIAN", kind: "warning" },
  critical: { label: "KRITIS", kind: "danger" },
};
const DOMAIN_STATUS_KIND: Record<string, BadgeKind> = {
  Healthy: "success", "Needs Attention": "warning",
};

type WorkforceDomain = { name: string; icon: keyof typeof MaterialCommunityIcons.glyphMap; status: string; line1: string; line2: string };
type Opportunity = { title: string; detail: string; owner: string };

type BizHealth = {
  overall: number | null;
  label: string | null;
  description: string;
  revenue30d: number;
  pendingInvoices: number;
  convs30d: number;
  handoffQueueLen: number;
  opsScore: number | null;
  opsLabel: string | null;
  workforce: WorkforceDomain[];
  opportunities: Opportunity[];
};

export default function Beranda() {
  const router = useRouter();
  const [data, setData] = useState<Dash | null>(null);
  const [biz, setBiz] = useState<BizHealth | null>(null);
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

      // Business-health section (mirrors web's renderDashboard) -- each of
      // these is permission-gated per-domain (e.g. finance.read), so some
      // may legitimately fail for lower-privilege roles; settle + degrade
      // gracefully, same pattern web's settle() helper uses.
      const [execR, financeR, marketingR, hrR, opsR, securityR, handoffR, analyticsR] = await Promise.allSettled([
        api.executiveDashboard(),
        api.financeDashboard(),
        api.marketingDashboard(),
        api.hrDashboard(),
        api.opsDashboard(),
        api.securityDashboard(),
        api.handoffQueue({ limit: 8 }),
        bots[0] ? api.botAnalytics(bots[0].id, 30) : Promise.resolve(null),
      ]);
      const health = pick(execR, {} as any).health || {};
      const finance = pick(financeR, {} as any);
      const marketing = pick(marketingR, {} as any);
      const hr = pick(hrR, {} as any);
      const ops = pick(opsR, {} as any);
      const security = pick(securityR, {} as any);
      const handoffQueue: any[] = pick(handoffR, { queue: [] } as any).queue || [];
      const analytics: any = pick(analyticsR, null);

      const overdueInvoices = finance.overdue_invoices_count || 0;
      const openOpsAlerts = Object.values(ops.open_alerts_by_severity || {}).reduce((s: number, n) => s + Number(n || 0), 0);
      const openSecurityAlerts = Object.values(security.open_security_alerts_by_severity || {}).reduce((s: number, n) => s + Number(n || 0), 0);
      const contentDueNow = marketing.content_due_now || 0;
      const pendingTraining = hr.pending_training_recommendations || 0;
      const pendingApproval = workforce?.pending_approval_count || 0;

      const descParts: string[] = [];
      if (overdueInvoices) descParts.push(`${num(overdueInvoices)} invoice overdue`);
      if (openOpsAlerts) descParts.push(`${num(openOpsAlerts)} alert operasional`);
      if (openSecurityAlerts) descParts.push(`${num(openSecurityAlerts)} sinyal security`);

      const opportunities: Opportunity[] = [
        overdueInvoices ? { title: "Invoice overdue", detail: `${num(overdueInvoices)} invoice melewati jatuh tempo, total ${idr(finance.pending_invoices_amount_idr || 0)}`, owner: "Finance Agent" } : null,
        contentDueNow ? { title: "Konten terlambat publish", detail: `${num(contentDueNow)} konten terjadwal sudah lewat waktu publish`, owner: "Marketing Agent" } : null,
        openOpsAlerts ? { title: "Alert operasional terbuka", detail: `${num(openOpsAlerts)} alert operations perlu ditindaklanjuti`, owner: "Operations Agent" } : null,
        openSecurityAlerts ? { title: "Sinyal risiko keamanan", detail: `${num(openSecurityAlerts)} alert security terbuka`, owner: "Security Agent" } : null,
        pendingTraining ? { title: "Rekomendasi training tertunda", detail: `${num(pendingTraining)} rekomendasi training menunggu review`, owner: "HR Agent" } : null,
        pendingApproval ? { title: "Task menunggu approval", detail: `${num(pendingApproval)} workforce task butuh human approval`, owner: "Workforce Orchestrator" } : null,
      ].filter((o): o is Opportunity => o !== null);

      setBiz({
        overall: health.overall ?? null,
        label: health.label ?? null,
        description: descParts.length ? `Perlu perhatian: ${descParts.join(", ")}.` : "Tidak ada sinyal kritis lintas domain saat ini.",
        revenue30d: finance.revenue_30d_idr || 0,
        pendingInvoices: finance.pending_invoices_count || 0,
        convs30d: analytics?.summary?.total_convs ?? 0,
        handoffQueueLen: handoffQueue.length,
        opsScore: ops?.health?.score ?? null,
        opsLabel: ops?.health?.label ?? null,
        workforce: [
          { name: "Finance Agent", icon: "cash-multiple", status: overdueInvoices ? "Needs Attention" : "Healthy", line1: `${num(finance.pending_invoices_count || 0)} invoice pending`, line2: `${idr(finance.revenue_30d_idr || 0)} revenue 30 hari` },
          { name: "Marketing Agent", icon: "bullhorn-outline", status: contentDueNow ? "Needs Attention" : "Healthy", line1: `${num(marketing.active_campaigns || 0)} campaign aktif`, line2: `${num(marketing.content_published || 0)} konten published` },
          { name: "HR Agent", icon: "account-group-outline", status: pendingTraining ? "Needs Attention" : "Healthy", line1: `${num(Object.values(hr.candidates_by_status || {}).reduce((s: number, n) => s + Number(n || 0), 0))} kandidat aktif`, line2: `${num(pendingTraining)} rekomendasi training` },
          { name: "Executive Agent", icon: "briefcase-outline", status: health.label === "healthy" ? "Healthy" : "Needs Attention", line1: `Company health ${health.overall ?? "—"}/100`, line2: `${num(Object.keys(health.by_domain || {}).length)} domain dipantau` },
          { name: "Security Agent", icon: "shield-outline", status: openSecurityAlerts ? "Needs Attention" : "Healthy", line1: `Risk level: ${security.risk_level || "—"}`, line2: `${num(security.suspicious_sessions_count || 0)} sesi mencurigakan` },
        ],
        opportunities,
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
          <Image source={require("../../assets/brand-logo.png")} style={styles.brandLogo} />
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
        <Quick icon="inbox-outline" title="Inbox Percakapan" sub="Chat pelanggan" tint={colors.status.success} bg={colors.status.successBgStrong} onPress={() => router.push("/inbox")} />
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

      {/* Kesehatan Bisnis (parity dengan web renderDashboard) */}
      <View style={styles.sectionHead}>
        <Text style={styles.sectionLabel}>KESEHATAN BISNIS</Text>
      </View>

      <Pressable onPress={() => router.push("/notifikasi")}>
        <Card style={styles.healthCard}>
          <View style={styles.healthHead}>
            <Text style={styles.workforceLabel}>Skor Kesehatan Bisnis</Text>
            {biz?.label && HEALTH_LABEL[biz.label] ? <Badge label={HEALTH_LABEL[biz.label].label} kind={HEALTH_LABEL[biz.label].kind} /> : null}
          </View>
          <View style={styles.workforceValueRow}>
            <Text style={styles.workforceValue}>{biz?.overall ?? "–"}</Text>
            <Text style={styles.workforceTotal}> /100</Text>
          </View>
          <Text style={styles.healthDesc}>{biz?.description ?? "Memuat data lintas domain…"}</Text>
        </Card>
      </Pressable>

      <View style={styles.kpiGrid}>
        <View style={styles.kpiCard}>
          <Text style={styles.statLabel}>Revenue 30 hari</Text>
          <Text style={styles.kpiValue}>{biz ? idr(biz.revenue30d) : "–"}</Text>
          <Text style={styles.statSub}>{biz ? `${num(biz.pendingInvoices)} invoice pending` : ""}</Text>
        </View>
        <Pressable style={styles.kpiCard} onPress={() => router.push("/inbox")}>
          <Text style={styles.statLabel}>Percakapan Aktif</Text>
          <Text style={styles.kpiValue}>{biz ? num(biz.convs30d) : "–"}</Text>
          <Text style={styles.statSub}>30 hari terakhir</Text>
        </Pressable>
        <Pressable style={styles.kpiCard} onPress={() => router.push("/handoff")}>
          <Text style={styles.statLabel}>Antrian Handoff</Text>
          <Text style={styles.kpiValue}>{biz ? num(biz.handoffQueueLen) : "–"}</Text>
          <Text style={styles.statSub}>menunggu agen manusia</Text>
        </Pressable>
        <View style={styles.kpiCard}>
          <Text style={styles.statLabel}>Ops Health</Text>
          <Text style={styles.kpiValue}>{biz?.opsScore ?? "–"}</Text>
          <Text style={styles.statSub}>{biz?.opsLabel ?? ""}</Text>
        </View>
      </View>

      <View style={styles.sectionHead}>
        <Text style={styles.sectionLabel}>STATUS AI WORKFORCE</Text>
      </View>
      {(biz?.workforce ?? []).map((w) => (
        <Card key={w.name} style={styles.domainCard}>
          <View style={styles.domainHead}>
            <View style={styles.quickIcon}>
              <MaterialCommunityIcons name={w.icon} size={18} color={colors.brand.violet400} />
            </View>
            <Text style={styles.domainName}>{w.name}</Text>
            <Badge label={w.status === "Healthy" ? "SEHAT" : "PERLU PERHATIAN"} kind={DOMAIN_STATUS_KIND[w.status] || "neutral"} />
          </View>
          <Text style={styles.domainLine}>{w.line1}</Text>
          <Text style={styles.domainLine}>{w.line2}</Text>
        </Card>
      ))}

      <View style={styles.sectionHead}>
        <Text style={styles.sectionLabel}>PERLU PERHATIAN</Text>
      </View>
      <Card style={{ gap: spacing.md }}>
        {(biz?.opportunities ?? []).length === 0 ? (
          <Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>
            {biz ? "Tidak ada yang perlu perhatian saat ini. Semua normal." : "Memuat…"}
          </Text>
        ) : (
          biz!.opportunities.map((o, i) => (
            <View key={i} style={styles.oppRow}>
              <View style={styles.oppDot} />
              <View style={{ flex: 1 }}>
                <Text style={styles.oppTitle}>{o.title}</Text>
                <Text style={styles.oppDetail}>{o.detail}</Text>
              </View>
              <Text style={styles.oppOwner}>{o.owner}</Text>
            </View>
          ))
        )}
      </Card>
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
  brandLogo: { width: 34, height: 34, borderRadius: radius.md, resizeMode: "cover" },
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

  healthCard: { gap: spacing.sm },
  healthHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  healthDesc: { color: colors.text.muted, fontSize: 12, lineHeight: 17, marginTop: 2 },

  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpiCard: {
    width: "47.5%", flexGrow: 1, backgroundColor: colors.bg.card, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 2,
  },
  kpiValue: { color: colors.text.primary, fontSize: 16, fontWeight: "800", marginTop: 2 },

  domainCard: { gap: spacing.xs },
  domainHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  domainName: { flex: 1, color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  domainLine: { color: colors.text.muted, fontSize: 12 },

  oppRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  oppDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.brand.violet400, marginTop: 6 },
  oppTitle: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  oppDetail: { color: colors.text.muted, fontSize: 12, marginTop: 2 },
  oppOwner: { color: colors.text.faint, fontSize: 10, alignSelf: "flex-start" },
});
