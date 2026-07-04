import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}

// Same formatting as web's usd() helper -- provider costs are tiny, so 4-6
// decimal places are meaningful, not noise.
function usd(value: any, digits = 4): string {
  return `$${Number(value || 0).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

const BUDGET_KIND: Record<string, BadgeKind> = { healthy: "success", warning: "warning", critical: "danger", exceeded: "danger" };

export default function CostIntelligence() {
  const router = useRouter();
  const [data, setData] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [budgetInput, setBudgetInput] = useState("");
  const [savingBudget, setSavingBudget] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      const res = await api.costIntelligence();
      setData(res || {});
      setBudgetInput(String(Number(res?.budget?.monthly_budget_usd || 0)));
    } catch (e: any) {
      setError(e?.message || "Gagal memuat Cost Intelligence.");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function onRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function saveBudget() {
    const value = Number(budgetInput);
    if (Number.isNaN(value) || value < 0) {
      Alert.alert("Tidak valid", "Masukkan angka budget bulanan (USD) yang valid.");
      return;
    }
    setSavingBudget(true);
    try {
      await api.updateCostBudget(value);
      await load();
      Alert.alert("Berhasil", "Budget AI bulanan diperbarui.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menyimpan budget.");
    } finally {
      setSavingBudget(false);
    }
  }

  const budget = data.budget || {};
  const pct = Math.min(100, Number(budget.percentage || 0));
  const budgetLevel = ["warning", "critical", "exceeded"].includes(budget.level) ? budget.level : "healthy";

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Cost Intelligence</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand.violet400} />}>
        {error ? <Card style={{ borderColor: colors.status.danger }}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></Card> : null}

        {loading ? <ActivityIndicator color={colors.brand.violet400} /> : (
          <>
            <View style={styles.kpiGrid}>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Monthly Cost</Text><Text style={styles.kpiValue}>{usd(data.monthly_cost)}</Text><Text style={styles.kpiSub}>{num(data.monthly_calls)} model calls</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Daily Cost</Text><Text style={styles.kpiValue}>{usd(data.daily_cost)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Projected Month</Text><Text style={styles.kpiValue}>{usd(data.projected_monthly_cost)}</Text></View>
              <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Monthly Tokens</Text><Text style={styles.kpiValue}>{num(data.monthly_tokens)}</Text></View>
            </View>

            <Text style={styles.sectionLabel}>MONTHLY BUDGET</Text>
            <Card style={{ gap: spacing.sm }}>
              <View style={styles.rowBetween}>
                <Text style={styles.itemTitle}>{usd(data.monthly_cost)} <Text style={styles.hint}>dari {budget.monthly_budget_usd ? usd(budget.monthly_budget_usd, 2) : "belum diatur"}</Text></Text>
                <Badge label={(budget.level || "unconfigured").toUpperCase()} kind={BUDGET_KIND[budgetLevel] || "neutral"} />
              </View>
              <View style={styles.progressTrack}>
                <View style={[styles.progressFill, { width: `${pct}%` }, budgetLevel !== "healthy" && { backgroundColor: colors.status.danger }]} />
              </View>
              {budget.message ? <Text style={styles.hint}>{budget.message}</Text> : null}
              <View style={{ flexDirection: "row", gap: spacing.sm }}>
                <TextInput
                  style={[styles.input, { flex: 1 }]}
                  value={budgetInput}
                  onChangeText={setBudgetInput}
                  placeholder="Budget bulanan (USD)"
                  placeholderTextColor={colors.text.muted}
                  keyboardType="decimal-pad"
                />
                {savingBudget ? <ActivityIndicator size="small" color={colors.brand.violet400} /> : (
                  <Pressable style={styles.primaryBtn} onPress={saveBudget}>
                    <Text style={styles.primaryBtnText}>Simpan</Text>
                  </Pressable>
                )}
              </View>
            </Card>

            <BreakdownSection title="COST BY AGENT" rows={data.cost_by_agent} />
            <BreakdownSection title="COST BY MODEL" rows={data.cost_by_model} />
            <BreakdownSection title="COST BY CHANNEL" rows={data.cost_by_channel} />

            <Text style={styles.sectionLabel}>MODEL ROUTING</Text>
            {(data.model_routing || []).length === 0 ? (
              <Card><Text style={styles.emptyText}>Belum ada routing data.</Text></Card>
            ) : (
              (data.model_routing || []).map((row: any, i: number) => (
                <Card key={i} style={styles.breakdownRow}>
                  <Badge label={(row.task_complexity || "").toUpperCase()} kind={row.task_complexity === "simple" ? "success" : "warning"} />
                  <Text style={[styles.itemTitle, { flex: 1 }]} numberOfLines={1}>{row.routed_model || "default"}</Text>
                  <Text style={styles.hint}>{num(row.requests)} req</Text>
                </Card>
              ))
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function BreakdownSection({ title, rows }: { title: string; rows?: any[] }) {
  const data = rows || [];
  return (
    <>
      <Text style={styles.sectionLabel}>{title}</Text>
      {data.length === 0 ? (
        <Card><Text style={styles.emptyText}>Belum ada cost data.</Text></Card>
      ) : (
        data.map((row, i) => (
          <Card key={i} style={styles.breakdownRow}>
            <Text style={[styles.itemTitle, { flex: 1 }]} numberOfLines={1}>{row.label || "unknown"}</Text>
            <View style={{ alignItems: "flex-end" }}>
              <Text style={styles.costValue}>{usd(row.cost, 6)}</Text>
              <Text style={styles.hint}>{num(row.tokens)} tokens · {num(row.calls)} calls</Text>
            </View>
          </Card>
        ))
      )}
    </>
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
  kpiValue: { color: colors.text.primary, fontSize: 15, fontWeight: "800" },
  kpiSub: { color: colors.text.muted, fontSize: 9 },

  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  itemTitle: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  hint: { color: colors.text.faint, fontSize: 10 },
  emptyText: { color: colors.text.muted, fontSize: 13, textAlign: "center" },

  progressTrack: { height: 8, borderRadius: 4, backgroundColor: colors.bg.cardAlt, overflow: "hidden" },
  progressFill: { height: "100%", borderRadius: 4, backgroundColor: colors.brand.violet500 },

  input: {
    backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, color: colors.text.primary, fontSize: 13,
  },
  primaryBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingHorizontal: spacing.lg, justifyContent: "center", alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },

  breakdownRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  costValue: { color: colors.brand.violet400, fontSize: 13, fontWeight: "800" },
});
