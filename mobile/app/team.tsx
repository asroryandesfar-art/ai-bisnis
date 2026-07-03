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

type Member = {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  last_login_at: string | null;
  roles: string[];
};
type Role = { id: string; key: string; name: string; description: string | null; is_system: boolean; permissions: string[] };

function initials(name: string) {
  return name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";
}

export default function Team() {
  const router = useRouter();
  const [org, setOrg] = useState<any>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [myPerms, setMyPerms] = useState<string[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [addRoleKey, setAddRoleKey] = useState<Record<string, string>>({});

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [invitePassword, setInvitePassword] = useState("");
  const [inviteRole, setInviteRole] = useState("agent");

  const load = useCallback(async () => {
    try {
      setError(null);
      const [orgRes, teamRes, rolesRes, meRes] = await Promise.allSettled([
        api.org(), api.team(), api.rbacRoles(), api.rbacMe(),
      ]);
      setOrg(orgRes.status === "fulfilled" ? orgRes.value : null);
      setMembers(teamRes.status === "fulfilled" ? (teamRes.value as any).team || [] : []);
      setRoles(rolesRes.status === "fulfilled" ? rolesRes.value.roles || [] : []);
      setMyPerms(meRes.status === "fulfilled" ? meRes.value.permissions || [] : []);
      if (teamRes.status === "rejected") setError((teamRes as any).reason?.message || "Gagal memuat tim.");
    } catch (e: any) {
      setError(e?.message || "Gagal memuat tim.");
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

  function roleLabel(key: string) {
    return roles.find((r) => r.key === key)?.name || key;
  }

  async function submitInvite() {
    if (!inviteEmail.trim() || !inviteName.trim() || invitePassword.length < 8) {
      Alert.alert("Lengkapi form", "Nama, email, dan password (min. 8 karakter) wajib diisi.");
      return;
    }
    setBusy(true);
    try {
      await api.inviteMember({ email: inviteEmail.trim(), full_name: inviteName.trim(), role_key: inviteRole, password: invitePassword });
      setInviteOpen(false);
      setInviteEmail(""); setInviteName(""); setInvitePassword(""); setInviteRole("agent");
      await load();
      Alert.alert("Berhasil", "Anggota baru ditambahkan.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menambahkan anggota.");
    } finally {
      setBusy(false);
    }
  }

  async function addRole(member: Member) {
    const roleKey = addRoleKey[member.id];
    if (!roleKey) return;
    setBusy(true);
    try {
      await api.assignRole(member.id, roleKey);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menambahkan role.");
    } finally {
      setBusy(false);
    }
  }

  function removeRole(member: Member, roleKey: string) {
    Alert.alert("Hapus role?", `Hapus role "${roleLabel(roleKey)}" dari ${member.full_name || member.email}?`, [
      { text: "Batal", style: "cancel" },
      {
        text: "Hapus", style: "destructive",
        onPress: async () => {
          setBusy(true);
          try {
            await api.revokeRole(member.id, roleKey);
            await load();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa menghapus role ini.");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  }

  const canManage = myPerms.includes("team.manage");
  const activeCount = members.filter((m) => m.is_active).length;

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Tim</Text>
        {canManage ? (
          <Pressable style={styles.addIconBtn} onPress={() => setInviteOpen((v) => !v)}>
            <Ionicons name="person-add-outline" size={16} color="#fff" />
          </Pressable>
        ) : (
          <View style={{ width: 32 }} />
        )}
      </View>

      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}
      >
        {error ? (
          <Card style={{ borderColor: colors.status.danger }}>
            <Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text>
          </Card>
        ) : null}

        <View style={styles.kpiGrid}>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Workspace</Text><Text style={styles.kpiValueSm} numberOfLines={1}>{org?.name || "—"}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Anggota</Text><Text style={styles.kpiValue}>{members.length}</Text><Text style={styles.kpiSub}>{activeCount} aktif</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Role Saya</Text><Text style={styles.kpiValue}>{myPerms.length}</Text><Text style={styles.kpiSub}>izin</Text></View>
        </View>

        {inviteOpen ? (
          <Card style={{ gap: spacing.sm }}>
            <Text style={styles.formTitle}>Tambah Anggota</Text>
            <TextInput style={styles.input} value={inviteName} onChangeText={setInviteName} placeholder="Nama lengkap" placeholderTextColor={colors.text.muted} />
            <TextInput style={styles.input} value={inviteEmail} onChangeText={setInviteEmail} placeholder="Email" placeholderTextColor={colors.text.muted} autoCapitalize="none" keyboardType="email-address" />
            <TextInput style={styles.input} value={invitePassword} onChangeText={setInvitePassword} placeholder="Password sementara (min. 8 karakter)" placeholderTextColor={colors.text.muted} secureTextEntry />
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
              {roles.filter((r) => r.key !== "owner").map((r) => (
                <Pressable key={r.key} onPress={() => setInviteRole(r.key)} style={[styles.pill, inviteRole === r.key && styles.pillActive]}>
                  <Text style={[styles.pillText, inviteRole === r.key && styles.pillTextActive]}>{r.name || r.key}</Text>
                </Pressable>
              ))}
            </ScrollView>
            {busy ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
              <Pressable style={styles.primaryBtn} onPress={submitInvite}>
                <Text style={styles.primaryBtnText}>Tambah Anggota</Text>
              </Pressable>
            )}
          </Card>
        ) : null}

        <Text style={styles.sectionLabel}>ANGGOTA WORKSPACE ({members.length})</Text>
        {members.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada anggota.</Text></Card>
        ) : (
          members.map((m) => {
            const expanded = expandedId === m.id;
            const assignable = roles.filter((r) => !m.roles.includes(r.key));
            return (
              <Card key={m.id} style={styles.memberCard}>
                <Pressable style={styles.memberRow} onPress={() => canManage && setExpandedId(expanded ? null : m.id)}>
                  <View style={styles.avatar}>
                    <Text style={styles.avatarText}>{initials(m.full_name || m.email)}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.memberName} numberOfLines={1}>{m.full_name || "Tanpa nama"}</Text>
                    <Text style={styles.memberEmail} numberOfLines={1}>{m.email}</Text>
                    <View style={styles.chipRow}>
                      {m.roles.length === 0 ? <Text style={styles.noRole}>Belum ada role</Text> : m.roles.map((r) => <Badge key={r} label={roleLabel(r)} kind="neutral" />)}
                    </View>
                  </View>
                  <View style={{ alignItems: "flex-end", gap: 4 }}>
                    <Badge label={m.is_active ? "AKTIF" : "NONAKTIF"} kind={m.is_active ? "success" : "neutral"} />
                    <Text style={styles.lastLogin}>{m.last_login_at ? formatDate(m.last_login_at) : "Belum login"}</Text>
                  </View>
                  {canManage ? <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={16} color={colors.text.faint} /> : null}
                </Pressable>

                {expanded && canManage ? (
                  <View style={styles.manageBox}>
                    <Text style={styles.manageLabel}>Role saat ini</Text>
                    {m.roles.length === 0 ? (
                      <Text style={styles.noRole}>Belum ada role</Text>
                    ) : (
                      m.roles.map((r) => (
                        <View key={r} style={styles.roleRow}>
                          <Badge label={roleLabel(r)} kind="neutral" />
                          <Pressable onPress={() => removeRole(m, r)} hitSlop={8}>
                            <MaterialCommunityIcons name="trash-can-outline" size={16} color={colors.status.danger} />
                          </Pressable>
                        </View>
                      ))
                    )}
                    {assignable.length > 0 ? (
                      <>
                        <Text style={styles.manageLabel}>Tambah role</Text>
                        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
                          {assignable.map((r) => (
                            <Pressable
                              key={r.key}
                              onPress={() => setAddRoleKey((prev) => ({ ...prev, [m.id]: r.key }))}
                              style={[styles.pill, addRoleKey[m.id] === r.key && styles.pillActive]}
                            >
                              <Text style={[styles.pillText, addRoleKey[m.id] === r.key && styles.pillTextActive]}>{r.name || r.key}</Text>
                            </Pressable>
                          ))}
                        </ScrollView>
                        <Pressable style={styles.outlineBtn} onPress={() => addRole(m)} disabled={!addRoleKey[m.id]}>
                          <Text style={styles.outlineBtnText}>Tambahkan Role</Text>
                        </Pressable>
                      </>
                    ) : null}
                  </View>
                ) : null}
              </Card>
            );
          })
        )}

        <Text style={styles.sectionLabel}>IZIN SAYA ({myPerms.length})</Text>
        <Card style={styles.chipRow}>
          {myPerms.length === 0 ? (
            <Text style={{ color: colors.text.muted, fontSize: 13 }}>Tidak ada izin.</Text>
          ) : (
            myPerms.slice(0, 20).map((p) => <Badge key={p} label={p} kind="neutral" />)
          )}
        </Card>
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
  addIconBtn: { width: 32, height: 32, borderRadius: radius.full, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  topTitle: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  container: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },

  kpiGrid: { flexDirection: "row", gap: spacing.sm },
  kpiCard: { flex: 1, backgroundColor: colors.bg.card, borderRadius: radius.md, borderWidth: 1, borderColor: colors.bg.border, padding: spacing.md, gap: 2 },
  kpiLabel: { color: colors.text.faint, fontSize: 10 },
  kpiValue: { color: colors.text.primary, fontSize: 18, fontWeight: "800" },
  kpiValueSm: { color: colors.text.primary, fontSize: 13, fontWeight: "800", marginTop: 4 },
  kpiSub: { color: colors.text.muted, fontSize: 10 },

  formTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  input: {
    backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, color: colors.text.primary, fontSize: 13,
  },
  pill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border },
  pillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  pillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  pillTextActive: { color: "#fff" },
  primaryBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  outlineBtn: { borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  outlineBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },

  memberCard: { gap: 0, padding: 0, overflow: "hidden" },
  memberRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.lg },
  avatar: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#fff", fontWeight: "800", fontSize: 13 },
  memberName: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  memberEmail: { color: colors.text.muted, fontSize: 11, marginTop: 1 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginTop: spacing.xs },
  noRole: { color: colors.text.faint, fontSize: 11 },
  lastLogin: { color: colors.text.faint, fontSize: 10 },

  manageBox: { gap: spacing.sm, padding: spacing.lg, borderTopWidth: 1, borderTopColor: colors.bg.border },
  manageLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700" },
  roleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
});
