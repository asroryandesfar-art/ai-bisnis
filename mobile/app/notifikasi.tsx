import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { idr } from "../src/utils/format";

const SECURITY_EVENT_LABEL: Record<string, { title: string; tint: string }> = {
  login_failed: { title: "Login gagal terdeteksi", tint: colors.status.danger },
  permission_denied: { title: "Akses ditolak", tint: colors.status.warning },
  security_scan: { title: "Security scan dijalankan", tint: colors.text.muted },
  login: { title: "Login baru terdeteksi", tint: colors.status.danger },
};

type Notif = {
  id: string;
  title: string;
  detail: string;
  createdAt: string;
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  tint: string;
  route?: string;
};

function timeAgo(iso: string) {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "baru saja";
  if (mins < 60) return `${mins} menit lalu`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h} jam lalu`;
  return `${Math.floor(h / 24)} hari lalu`;
}

function pick<T>(r: PromiseSettledResult<T>, fb: T): T {
  return r.status === "fulfilled" ? r.value : fb;
}

export default function Notifikasi() {
  const router = useRouter();
  const [notifs, setNotifs] = useState<Notif[]>([]);
  const [readAll, setReadAll] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // No backend notifications table -- aggregate real signals into one feed:
  // 3 approval queues (pending, always relevant) + 3 read-only recent-event
  // sources (paid invoices, security events, recently-updated KB docs) that
  // all trace to real tables. Anything without a real backend source (e.g.
  // Figma's "laporan mingguan"/"agen baru siap") is intentionally omitted.
  const load = useCallback(async () => {
    try {
      setError(null);
      const [laR, caR, cmR, invR, secR, kbR] = await Promise.allSettled([
        api.localAgentPending(),
        api.computerAgentPending(),
        api.channelMessagingPending(),
        api.invoices(),
        api.securityDashboard(),
        api.knowledgeSources(),
      ]);
      const la = pick(laR, { commands: [] } as any).commands || [];
      const ca = pick(caR, { tasks: [] } as any).tasks || [];
      const cm = pick(cmR, { tasks: [] } as any).tasks || [];
      const paidInvoices = (pick(invR, { invoices: [] } as any).invoices || []).filter((i: any) => i.status === "paid");
      const securityEvents = pick(secR, { security_events: [] } as any).security_events || [];
      const kbUpdated = (pick(kbR, { sources: [] } as any).sources || []).filter((s: any) => s.last_crawled_at);

      const items: Notif[] = [
        ...la.map((c: any) => ({
          id: `la-${c.id}`,
          title: "Local Agent butuh persetujuan",
          detail: c.tool || c.command || c.description || "Aksi menunggu izin Anda",
          createdAt: c.created_at,
          icon: "laptop" as const,
          tint: colors.status.warning,
          route: "/antrian",
        })),
        ...ca.map((t: any) => ({
          id: `ca-${t.id}`,
          title: "Computer Agent butuh persetujuan",
          detail: t.goal || t.description || "Tugas menunggu izin Anda",
          createdAt: t.created_at,
          icon: "monitor" as const,
          tint: colors.brand.violet400,
          route: "/antrian",
        })),
        ...cm.map((t: any) => ({
          id: `cm-${t.id}`,
          title: "Pesan keluar butuh persetujuan",
          detail: t.preview || t.message || t.description || "Pesan menunggu izin Anda",
          createdAt: t.created_at,
          icon: "message-outline" as const,
          tint: colors.status.success,
          route: "/antrian",
        })),
        ...paidInvoices.slice(0, 5).map((inv: any) => ({
          id: `inv-${inv.id || inv.invoice_number}`,
          title: "Pembayaran berhasil",
          detail: `${inv.description || "Invoice"} · ${idr(inv.amount_idr)} lunas`,
          createdAt: inv.paid_at || inv.updated_at || inv.created_at,
          icon: "credit-card-check-outline" as const,
          tint: colors.status.success,
          route: "/billing",
        })),
        ...securityEvents.slice(0, 5).map((ev: any) => ({
          id: `sec-${ev.id}`,
          title: SECURITY_EVENT_LABEL[ev.action]?.title || `Keamanan: ${ev.action}`,
          detail: `${ev.actor_email || "Pengguna"}${ev.ip_address ? ` · ${ev.ip_address}` : ""}`,
          createdAt: ev.created_at,
          icon: "shield-alert-outline" as const,
          tint: SECURITY_EVENT_LABEL[ev.action]?.tint || colors.status.warning,
          // No dedicated mobile security screen yet -- intentionally
          // non-interactive rather than a dead nav target.
        })),
        ...kbUpdated.slice(0, 5).map((s: any) => ({
          id: `kb-${s.id}`,
          title: "Knowledge Base diperbarui",
          detail: s.title || s.url || "Dokumen diperbarui",
          createdAt: s.last_crawled_at,
          icon: "database-outline" as const,
          tint: colors.brand.violet400,
          route: "/knowledge",
        })),
      ].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());

      setNotifs(items);
      setReadAll(false);
    } catch (e: any) {
      setError(e?.message || "Gagal memuat notifikasi.");
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

  const unread = readAll ? 0 : notifs.length;

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Notifikasi</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
      >
        <View style={styles.headRow}>
          <Text style={styles.subtitle}>{unread} belum dibaca</Text>
          {notifs.length > 0 && !readAll ? (
            <Pressable onPress={() => setReadAll(true)}>
              <Text style={styles.markAll}>Tandai semua dibaca</Text>
            </Pressable>
          ) : null}
        </View>

        {error ? (
          <Card style={{ borderColor: colors.status.danger }}>
            <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
          </Card>
        ) : null}

        {!error && notifs.length === 0 ? (
          <View style={styles.empty}>
            <MaterialCommunityIcons name="bell-check-outline" size={36} color={colors.status.success} />
            <Text style={styles.emptyText}>Tidak ada notifikasi. Semua beres! 🎉</Text>
          </View>
        ) : null}

        {notifs.map((n) => {
          const card = (
            <Card style={[styles.notifCard, readAll && { opacity: 0.6 }]}>
              <View style={[styles.notifIcon, { backgroundColor: `${n.tint}22` }]}>
                <MaterialCommunityIcons name={n.icon} size={18} color={n.tint} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.notifTitle}>{n.title}</Text>
                <Text style={styles.notifDetail} numberOfLines={2}>{n.detail}</Text>
                <Text style={styles.notifTime}>{n.createdAt ? timeAgo(n.createdAt) : ""}</Text>
              </View>
              {!readAll ? <View style={styles.unreadDot} /> : null}
            </Card>
          );
          return n.route ? (
            <Pressable key={n.id} onPress={() => router.push(n.route as any)}>
              {card}
            </Pressable>
          ) : (
            <View key={n.id}>{card}</View>
          );
        })}
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
  headRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  subtitle: { color: colors.text.muted, fontSize: 12 },
  markAll: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },
  empty: { alignItems: "center", gap: spacing.md, paddingVertical: spacing.xxl },
  emptyText: { color: colors.text.body, fontSize: 13 },
  notifCard: { flexDirection: "row", gap: spacing.md, alignItems: "flex-start" },
  notifIcon: { width: 38, height: 38, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  notifTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  notifDetail: { color: colors.text.muted, fontSize: 12, marginTop: 2, lineHeight: 16 },
  notifTime: { color: colors.text.faint, fontSize: 11, marginTop: spacing.xs },
  unreadDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brand.violet500, marginTop: 4 },
});
