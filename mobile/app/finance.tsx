import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { formatDate, idr } from "../src/utils/format";

const INVOICE_STATUS_KIND: Record<string, BadgeKind> = {
  draft: "neutral", sent: "warning", paid: "success", overdue: "danger", cancelled: "neutral",
};
const EXPENSE_STATUS_KIND: Record<string, BadgeKind> = { recorded: "warning", approved: "success", rejected: "danger" };

export default function FinanceCenter() {
  const router = useRouter();
  const [dash, setDash] = useState<any>({});
  const [invoices, setInvoices] = useState<any[]>([]);
  const [expenses, setExpenses] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [invoiceFormOpen, setInvoiceFormOpen] = useState(false);
  const [invCustomer, setInvCustomer] = useState("");
  const [invAmount, setInvAmount] = useState("");
  const [expenseFormOpen, setExpenseFormOpen] = useState(false);
  const [expDesc, setExpDesc] = useState("");
  const [expCategory, setExpCategory] = useState("lainnya");
  const [expAmount, setExpAmount] = useState("");

  const load = useCallback(async () => {
    try {
      setError(null);
      const [dashRes, invRes, expRes] = await Promise.allSettled([
        api.financeDashboard(), api.financeInvoices(50), api.financeExpenses(50),
      ]);
      setDash(dashRes.status === "fulfilled" ? dashRes.value : {});
      setInvoices(invRes.status === "fulfilled" ? invRes.value.invoices || [] : []);
      setExpenses(expRes.status === "fulfilled" ? expRes.value.expenses || [] : []);
      if (dashRes.status === "rejected") setError((dashRes as any).reason?.message || "Gagal memuat Finance Center (perlu izin finance.read).");
    } catch (e: any) {
      setError(e?.message || "Gagal memuat Finance Center.");
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function createInvoice() {
    const amount = parseInt(invAmount.replace(/[^0-9]/g, ""), 10);
    if (!invCustomer.trim() || !amount) {
      Alert.alert("Lengkapi form", "Nama pelanggan dan jumlah wajib diisi.");
      return;
    }
    setBusy("new-invoice");
    try {
      await api.financeCreateInvoice({ customer_name: invCustomer.trim(), amount_idr: amount });
      setInvoiceFormOpen(false); setInvCustomer(""); setInvAmount("");
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa membuat invoice.");
    } finally {
      setBusy(null);
    }
  }

  async function setInvoiceStatus(id: string, status: string) {
    setBusy(id);
    try {
      await api.financeUpdateInvoiceStatus(id, status);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa mengubah status invoice.");
    } finally {
      setBusy(null);
    }
  }

  async function createExpense() {
    const amount = parseInt(expAmount.replace(/[^0-9]/g, ""), 10);
    if (!expDesc.trim() || !amount) {
      Alert.alert("Lengkapi form", "Deskripsi dan jumlah wajib diisi.");
      return;
    }
    setBusy("new-expense");
    try {
      await api.financeCreateExpense({ description: expDesc.trim(), category: expCategory, amount_idr: amount });
      setExpenseFormOpen(false); setExpDesc(""); setExpAmount("");
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa mencatat expense.");
    } finally {
      setBusy(null);
    }
  }

  async function approveExpense(id: string, approve: boolean) {
    setBusy(id);
    try {
      await api.financeApproveExpense(id, approve);
      await load();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memperbarui expense ini.");
    } finally {
      setBusy(null);
    }
  }

  if (error && !dash?.revenue_30d_idr && invoices.length === 0) {
    return (
      <View style={styles.flex}>
        <TopBar title="Finance Center" onBack={() => router.back()} />
        <View style={{ padding: spacing.lg }}>
          <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.flex}>
      <TopBar title="Finance Center" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        <View style={styles.kpiGrid}>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Revenue 30d</Text><Text style={styles.kpiValue}>{idr(dash.revenue_30d_idr)}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Profit 30d</Text><Text style={[styles.kpiValue, { color: (dash.profit_30d_idr ?? 0) >= 0 ? colors.status.success : colors.status.danger }]}>{idr(dash.profit_30d_idr)}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Invoice Pending</Text><Text style={styles.kpiValue}>{dash.pending_invoices_count ?? 0}</Text></View>
          <View style={styles.kpiCard}><Text style={[styles.kpiValue, (dash.overdue_invoices_count ?? 0) > 0 && { color: colors.status.danger }]}>{dash.overdue_invoices_count ?? 0}</Text><Text style={styles.kpiLabel}>Overdue</Text></View>
        </View>

        <Text style={styles.sectionLabel}>INVOICES ({invoices.length})</Text>
        <Pressable style={styles.outlineBtn} onPress={() => setInvoiceFormOpen((v) => !v)}>
          <Text style={styles.outlineBtnText}>{invoiceFormOpen ? "Batal" : "+ Buat Invoice"}</Text>
        </Pressable>
        {invoiceFormOpen ? (
          <Card style={{ gap: spacing.sm }}>
            <TextInput style={styles.input} value={invCustomer} onChangeText={setInvCustomer} placeholder="Nama pelanggan" placeholderTextColor={colors.text.muted} />
            <TextInput style={styles.input} value={invAmount} onChangeText={setInvAmount} placeholder="Jumlah (Rp)" placeholderTextColor={colors.text.muted} keyboardType="numeric" />
            {busy === "new-invoice" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
              <Pressable style={styles.primaryBtn} onPress={createInvoice}><Text style={styles.primaryBtnText}>Buat Invoice</Text></Pressable>
            )}
          </Card>
        ) : null}
        {invoices.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada invoice.</Text></Card>
        ) : (
          invoices.map((inv) => (
            <Card key={inv.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Text style={styles.itemTitle} numberOfLines={1}>{inv.invoice_number}</Text>
                <Badge label={inv.status.toUpperCase()} kind={INVOICE_STATUS_KIND[inv.status] || "neutral"} />
              </View>
              <Text style={styles.itemMeta}>{inv.customer_name} · {idr(inv.amount_idr)}</Text>
              <Text style={styles.itemMeta}>Jatuh tempo: {inv.due_date ? formatDate(inv.due_date) : "—"}</Text>
              {busy === inv.id ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                <View style={styles.actionRow}>
                  {inv.status === "draft" ? <ActionBtn label="Kirim" onPress={() => setInvoiceStatus(inv.id, "sent")} /> : null}
                  {(inv.status === "sent" || inv.status === "overdue") ? <ActionBtn label="Tandai Lunas" primary onPress={() => setInvoiceStatus(inv.id, "paid")} /> : null}
                  {inv.status !== "paid" && inv.status !== "cancelled" ? <ActionBtn label="Batalkan" danger onPress={() => setInvoiceStatus(inv.id, "cancelled")} /> : null}
                </View>
              )}
            </Card>
          ))
        )}

        <Text style={styles.sectionLabel}>EXPENSES ({expenses.length})</Text>
        <Pressable style={styles.outlineBtn} onPress={() => setExpenseFormOpen((v) => !v)}>
          <Text style={styles.outlineBtnText}>{expenseFormOpen ? "Batal" : "+ Catat Expense"}</Text>
        </Pressable>
        {expenseFormOpen ? (
          <Card style={{ gap: spacing.sm }}>
            <TextInput style={styles.input} value={expDesc} onChangeText={setExpDesc} placeholder="Deskripsi" placeholderTextColor={colors.text.muted} />
            <TextInput style={styles.input} value={expCategory} onChangeText={setExpCategory} placeholder="Kategori (operasional/gaji/marketing/sewa/lainnya)" placeholderTextColor={colors.text.muted} />
            <TextInput style={styles.input} value={expAmount} onChangeText={setExpAmount} placeholder="Jumlah (Rp)" placeholderTextColor={colors.text.muted} keyboardType="numeric" />
            {busy === "new-expense" ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
              <Pressable style={styles.primaryBtn} onPress={createExpense}><Text style={styles.primaryBtnText}>Catat Expense</Text></Pressable>
            )}
          </Card>
        ) : null}
        {expenses.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada expense.</Text></Card>
        ) : (
          expenses.map((exp) => (
            <Card key={exp.id} style={styles.itemCard}>
              <View style={styles.itemHead}>
                <Text style={styles.itemTitle} numberOfLines={1}>{exp.description}</Text>
                <Badge label={exp.status.toUpperCase()} kind={EXPENSE_STATUS_KIND[exp.status] || "neutral"} />
              </View>
              <Text style={styles.itemMeta}>{exp.category} · {idr(exp.amount_idr)}</Text>
              {exp.status === "recorded" ? (
                busy === exp.id ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                  <View style={styles.actionRow}>
                    <ActionBtn label="Approve" primary onPress={() => approveExpense(exp.id, true)} />
                    <ActionBtn label="Reject" danger onPress={() => approveExpense(exp.id, false)} />
                  </View>
                )
              ) : null}
            </Card>
          ))
        )}
      </ScrollView>
    </View>
  );
}

function TopBar({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <View style={styles.topBar}>
      <Pressable style={styles.iconBtn} onPress={onBack}>
        <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
      </Pressable>
      <Text style={styles.topTitle}>{title}</Text>
      <View style={{ width: 32 }} />
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
  actionRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap", marginTop: spacing.xs },
  actionBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt },
  actionBtnPrimary: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  actionBtnDanger: { backgroundColor: colors.status.dangerBg, borderColor: colors.status.danger },
  actionBtnText: { color: colors.text.body, fontSize: 12, fontWeight: "700" },
});
