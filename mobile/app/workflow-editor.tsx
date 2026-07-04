import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

type Field = { key: string; label: string; type: "text" | "textarea" | "number" | "select"; default: any; options?: { value: string; label: string }[] };
type CatalogNode = { label: string; description: string; config_fields: Field[] };
type Catalog = Record<string, Record<string, CatalogNode>>;
type ChainNode = { localId: string; category: string; type: string; config: Record<string, any> };

const CATEGORY_ORDER = ["condition", "agent", "action", "notification"];
const CATEGORY_LABEL: Record<string, string> = {
  trigger: "Trigger", condition: "Condition", agent: "Agent", action: "Action", notification: "Notification",
};
const CATEGORY_ICON: Record<string, keyof typeof MaterialCommunityIcons.glyphMap> = {
  trigger: "flash-outline", condition: "call-split", agent: "robot-outline", action: "lightning-bolt-outline", notification: "bell-outline",
};
const STATUS_KIND: Record<string, BadgeKind> = { published: "success", draft: "neutral", disabled: "neutral" };

let idCounter = 0;
function newLocalId() {
  idCounter += 1;
  return `n${Date.now()}_${idCounter}`;
}

// A linear chain is one where every node (starting at the trigger) has at
// most one outgoing edge and no node repeats -- i.e. exactly what this
// mobile builder can produce/edit. Workflows with real condition branching
// (a node with 2 outgoing edges for true/false) can only be built on the
// web canvas; this returns null for those so the screen can fall back to a
// safe read-only view instead of risking silently flattening the branch.
function detectLinearChain(nodes: any[], edges: any[], triggerId: string): string[] | null {
  const outMap = new Map<string, any[]>();
  edges.forEach((e) => {
    if (!outMap.has(e.source)) outMap.set(e.source, []);
    outMap.get(e.source)!.push(e);
  });
  const order: string[] = [];
  let current = triggerId;
  const visited = new Set([triggerId]);
  while (true) {
    const outs = outMap.get(current) || [];
    if (outs.length > 1) return null;
    if (outs.length === 0) break;
    const next = outs[0].target;
    if (visited.has(next)) return null;
    visited.add(next);
    order.push(next);
    current = next;
  }
  if (order.length + 1 !== nodes.length) return null;
  return order;
}

export default function WorkflowEditor() {
  const router = useRouter();
  const params = useLocalSearchParams<{ botId?: string; id?: string }>();
  const isEdit = !!params.id;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [catalog, setCatalog] = useState<Catalog>({});
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [triggerType, setTriggerType] = useState("manual_trigger");
  const [chain, setChain] = useState<ChainNode[]>([]);
  const [status, setStatus] = useState<string>("draft");
  const [readOnly, setReadOnly] = useState(false);
  const [readOnlyNodes, setReadOnlyNodes] = useState<any[]>([]);
  const [picker, setPicker] = useState<{ category: string | null; type: string | null }>({ category: null, type: null });
  const [pickerConfig, setPickerConfig] = useState<Record<string, any>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const catRes = await api.wfNodeCatalog();
      setCatalog(catRes.categories || {});
      if (params.id) {
        const wf = await api.wfGet(params.id);
        setName(wf.name || "");
        setDescription(wf.description || "");
        setTriggerType(wf.trigger_type || "manual_trigger");
        setStatus(wf.status || "draft");
        const triggerNode = (wf.nodes || []).find((n: any) => n.category === "trigger");
        const order = triggerNode ? detectLinearChain(wf.nodes || [], wf.edges || [], triggerNode.id) : null;
        if (order === null || !triggerNode) {
          setReadOnly(true);
          setReadOnlyNodes(wf.nodes || []);
        } else {
          setReadOnly(false);
          const byId: Record<string, any> = {};
          (wf.nodes || []).forEach((n: any) => { byId[n.id] = n; });
          setChain(order.map((id) => ({ localId: id, category: byId[id].category, type: byId[id].type, config: byId[id].config || {} })));
        }
      }
    } catch (e: any) {
      Alert.alert("Gagal memuat", e?.message || "Tidak bisa memuat workflow.");
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    load();
  }, [load]);

  function openPicker(category: string) {
    setPicker({ category, type: null });
    setPickerConfig({});
  }

  function pickType(category: string, type: string) {
    const def = catalog[category]?.[type];
    const initial: Record<string, any> = {};
    (def?.config_fields || []).forEach((f) => { initial[f.key] = f.default; });
    setPicker({ category, type });
    setPickerConfig(initial);
  }

  function confirmAddNode() {
    if (!picker.category || !picker.type) return;
    setChain((prev) => [...prev, { localId: newLocalId(), category: picker.category!, type: picker.type!, config: pickerConfig }]);
    setPicker({ category: null, type: null });
    setPickerConfig({});
  }

  function removeNode(localId: string) {
    setChain((prev) => prev.filter((n) => n.localId !== localId));
  }

  function moveNode(index: number, dir: -1 | 1) {
    setChain((prev) => {
      const next = [...prev];
      const target = index + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function updateNodeConfig(localId: string, key: string, value: any) {
    setChain((prev) => prev.map((n) => (n.localId === localId ? { ...n, config: { ...n.config, [key]: value } } : n)));
  }

  function buildPayload() {
    const triggerId = "trigger";
    const nodes = [
      { id: triggerId, type: triggerType, category: "trigger", config: {} },
      ...chain.map((n) => ({ id: n.localId, type: n.type, category: n.category, config: n.config })),
    ];
    // A condition node's edge needs source_handle:"true" so the engine
    // (workflow_engine.py's run_workflow) only continues past it when the
    // condition actually matches -- otherwise it falls back to treating any
    // unlabeled edge as "always continue," which would make the condition a
    // no-op. Every other node type always takes its single outgoing edge
    // regardless of handle, since this builder only produces linear chains
    // (no true/false fork -- see detectLinearChain above).
    const categoryOf: Record<string, string> = { [triggerId]: "trigger" };
    chain.forEach((n) => { categoryOf[n.localId] = n.category; });
    const edges: any[] = [];
    let prev = triggerId;
    chain.forEach((n) => {
      edges.push({ source: prev, target: n.localId, source_handle: categoryOf[prev] === "condition" ? "true" : undefined });
      prev = n.localId;
    });
    return { name: name.trim(), description: description.trim() || null, trigger_type: triggerType, nodes, edges };
  }

  async function save() {
    if (!name.trim()) {
      Alert.alert("Lengkapi form", "Nama workflow wajib diisi.");
      return;
    }
    const payload = buildPayload();
    setSaving(true);
    try {
      if (isEdit && params.id) {
        await api.wfUpdate(params.id, payload);
      } else {
        if (!params.botId) {
          Alert.alert("Error", "Agen tujuan tidak ditemukan.");
          return;
        }
        await api.wfCreate(params.botId, payload);
      }
      router.back();
    } catch (e: any) {
      Alert.alert("Gagal simpan", e?.message || "Tidak bisa menyimpan workflow.");
    } finally {
      setSaving(false);
    }
  }

  async function togglePublish() {
    if (!params.id) return;
    setSaving(true);
    try {
      if (status === "published") {
        await api.wfUnpublish(params.id);
        setStatus("draft");
      } else {
        await api.wfPublish(params.id);
        setStatus("published");
      }
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa mengubah status publish (workflow butuh trigger node).");
    } finally {
      setSaving(false);
    }
  }

  function deleteWorkflow() {
    if (!params.id) return;
    Alert.alert("Hapus workflow?", name, [
      { text: "Batal", style: "cancel" },
      {
        text: "Hapus", style: "destructive",
        onPress: async () => {
          setSaving(true);
          try {
            await api.wfDelete(params.id!);
            router.back();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa menghapus workflow ini.");
          } finally {
            setSaving(false);
          }
        },
      },
    ]);
  }

  if (loading) {
    return (
      <View style={[styles.flex, { alignItems: "center", justifyContent: "center" }]}>
        <ActivityIndicator color={colors.brand.violet400} />
      </View>
    );
  }

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="close" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>{isEdit ? "Edit Otomatisasi" : "Otomatisasi Baru"}</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container}>
        {readOnly ? (
          <Card style={{ borderColor: colors.status.warning, gap: spacing.sm }}>
            <Text style={{ color: colors.status.warning, fontSize: 12, fontWeight: "700" }}>Mode Lihat Saja</Text>
            <Text style={styles.hint}>
              Workflow ini punya percabangan kondisi yang tidak bisa ditampilkan sebagai daftar linear. Edit lewat dashboard web (Workflow Builder) untuk mengubah alur ini.
            </Text>
          </Card>
        ) : null}

        <TextInput
          style={styles.titleInput}
          value={name}
          onChangeText={setName}
          placeholder="Nama otomatisasi"
          placeholderTextColor={colors.text.muted}
          editable={!readOnly}
        />
        <TextInput
          style={styles.input}
          value={description}
          onChangeText={setDescription}
          placeholder="Deskripsi (opsional)"
          placeholderTextColor={colors.text.muted}
          editable={!readOnly}
        />

        <Text style={styles.sectionLabel}>TRIGGER</Text>
        {readOnly ? (
          <Card><Text style={styles.nodeType}>{catalog.trigger?.[triggerType]?.label || triggerType}</Text></Card>
        ) : (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
            {Object.entries(catalog.trigger || {}).map(([key, def]) => (
              <Pressable key={key} onPress={() => setTriggerType(key)} style={[styles.pill, triggerType === key && styles.pillActive]}>
                <Text style={[styles.pillText, triggerType === key && styles.pillTextActive]}>{def.label}</Text>
              </Pressable>
            ))}
          </ScrollView>
        )}

        <Text style={styles.sectionLabel}>ALUR ({readOnly ? readOnlyNodes.length - 1 : chain.length} langkah)</Text>

        {readOnly ? (
          readOnlyNodes.filter((n) => n.category !== "trigger").map((n, i) => (
            <Card key={n.id} style={styles.nodeCard}>
              <View style={styles.nodeHead}>
                <MaterialCommunityIcons name={CATEGORY_ICON[n.category] || "cog-outline"} size={16} color={colors.brand.violet400} />
                <Text style={styles.nodeCategory}>{CATEGORY_LABEL[n.category] || n.category}</Text>
              </View>
              <Text style={styles.nodeType}>{catalog[n.category]?.[n.type]?.label || n.type}</Text>
            </Card>
          ))
        ) : chain.length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada langkah. Tambahkan di bawah.</Text></Card>
        ) : (
          chain.map((n, i) => {
            const def = catalog[n.category]?.[n.type];
            return (
              <Card key={n.localId} style={styles.nodeCard}>
                <View style={styles.nodeHead}>
                  <MaterialCommunityIcons name={CATEGORY_ICON[n.category] || "cog-outline"} size={16} color={colors.brand.violet400} />
                  <Text style={styles.nodeCategory}>{CATEGORY_LABEL[n.category]}</Text>
                  <View style={{ flex: 1 }} />
                  <Pressable onPress={() => moveNode(i, -1)} disabled={i === 0} hitSlop={6}>
                    <Ionicons name="chevron-up" size={16} color={i === 0 ? colors.text.faint : colors.text.body} />
                  </Pressable>
                  <Pressable onPress={() => moveNode(i, 1)} disabled={i === chain.length - 1} hitSlop={6}>
                    <Ionicons name="chevron-down" size={16} color={i === chain.length - 1 ? colors.text.faint : colors.text.body} />
                  </Pressable>
                  <Pressable onPress={() => removeNode(n.localId)} hitSlop={6}>
                    <MaterialCommunityIcons name="trash-can-outline" size={16} color={colors.status.danger} />
                  </Pressable>
                </View>
                <Text style={styles.nodeType}>{def?.label || n.type}</Text>
                {(def?.config_fields || []).map((f) => (
                  <ConfigField key={f.key} field={f} value={n.config[f.key]} onChange={(v) => updateNodeConfig(n.localId, f.key, v)} />
                ))}
              </Card>
            );
          })
        )}

        {!readOnly ? (
          <>
            {picker.category === null ? (
              <View style={styles.addGrid}>
                {CATEGORY_ORDER.map((cat) => (
                  <Pressable key={cat} style={styles.addBtn} onPress={() => openPicker(cat)}>
                    <MaterialCommunityIcons name={CATEGORY_ICON[cat]} size={16} color={colors.brand.violet400} />
                    <Text style={styles.addBtnText}>+ {CATEGORY_LABEL[cat]}</Text>
                  </Pressable>
                ))}
              </View>
            ) : picker.type === null ? (
              <Card style={{ gap: spacing.sm }}>
                <Text style={styles.formTitle}>Pilih {CATEGORY_LABEL[picker.category]}</Text>
                {Object.entries(catalog[picker.category] || {}).map(([key, def]) => (
                  <Pressable key={key} style={styles.optionRow} onPress={() => pickType(picker.category!, key)}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.nodeType}>{def.label}</Text>
                      <Text style={styles.hint}>{def.description}</Text>
                    </View>
                    <Ionicons name="chevron-forward" size={16} color={colors.text.faint} />
                  </Pressable>
                ))}
                <Pressable style={styles.outlineBtn} onPress={() => setPicker({ category: null, type: null })}>
                  <Text style={styles.outlineBtnText}>Batal</Text>
                </Pressable>
              </Card>
            ) : (
              <Card style={{ gap: spacing.sm }}>
                <Text style={styles.formTitle}>{catalog[picker.category]?.[picker.type]?.label}</Text>
                {(catalog[picker.category]?.[picker.type]?.config_fields || []).map((f) => (
                  <ConfigField key={f.key} field={f} value={pickerConfig[f.key]} onChange={(v) => setPickerConfig((prev) => ({ ...prev, [f.key]: v }))} />
                ))}
                <View style={{ flexDirection: "row", gap: spacing.sm }}>
                  <Pressable style={styles.outlineBtnFlex} onPress={() => setPicker({ category: null, type: null })}>
                    <Text style={styles.outlineBtnText}>Batal</Text>
                  </Pressable>
                  <Pressable style={styles.primaryBtnFlex} onPress={confirmAddNode}>
                    <Text style={styles.primaryBtnText}>Tambahkan</Text>
                  </Pressable>
                </View>
              </Card>
            )}
          </>
        ) : null}

        {saving ? (
          <ActivityIndicator size="small" color={colors.brand.violet400} />
        ) : (
          <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
            {!readOnly ? (
              <Pressable style={styles.primaryBtn} onPress={save}>
                <Text style={styles.primaryBtnText}>{isEdit ? "Simpan Perubahan" : "Buat Otomatisasi"}</Text>
              </Pressable>
            ) : null}
            {isEdit ? (
              <>
                <Pressable style={styles.outlineBtn} onPress={togglePublish}>
                  <Text style={styles.outlineBtnText}>{status === "published" ? "Nonaktifkan (Unpublish)" : "Publish"}</Text>
                </Pressable>
                <Pressable style={styles.dangerBtn} onPress={deleteWorkflow}>
                  <Text style={styles.dangerBtnText}>Hapus Workflow</Text>
                </Pressable>
              </>
            ) : null}
          </View>
        )}
      </ScrollView>
    </View>
  );
}

function ConfigField({ field, value, onChange }: { field: Field; value: any; onChange: (v: any) => void }) {
  if (field.type === "select") {
    return (
      <View style={{ gap: spacing.xs }}>
        <Text style={styles.fieldLabel}>{field.label}</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
          {(field.options || []).map((opt) => (
            <Pressable key={opt.value} onPress={() => onChange(opt.value)} style={[styles.pill, value === opt.value && styles.pillActive]}>
              <Text style={[styles.pillText, value === opt.value && styles.pillTextActive]}>{opt.label}</Text>
            </Pressable>
          ))}
        </ScrollView>
      </View>
    );
  }
  return (
    <View style={{ gap: spacing.xs }}>
      <Text style={styles.fieldLabel}>{field.label}</Text>
      <TextInput
        style={[styles.input, field.type === "textarea" && { minHeight: 70, textAlignVertical: "top" }]}
        value={String(value ?? "")}
        onChangeText={(t) => onChange(field.type === "number" ? Number(t) || 0 : t)}
        placeholder={field.label}
        placeholderTextColor={colors.text.muted}
        multiline={field.type === "textarea"}
        keyboardType={field.type === "number" ? "numeric" : "default"}
      />
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
  sectionLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: spacing.sm },
  hint: { color: colors.text.faint, fontSize: 11, lineHeight: 16 },

  titleInput: { color: colors.text.primary, fontSize: 20, fontWeight: "800", paddingVertical: spacing.xs },
  input: {
    backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, color: colors.text.primary, fontSize: 13,
  },
  fieldLabel: { color: colors.text.muted, fontSize: 11, fontWeight: "600" },

  pill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border },
  pillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  pillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  pillTextActive: { color: "#fff" },

  nodeCard: { gap: spacing.sm },
  nodeHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  nodeCategory: { color: colors.text.muted, fontSize: 11, fontWeight: "700" },
  nodeType: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },

  addGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.brand.violet500, backgroundColor: "rgba(139,92,246,0.08)",
  },
  addBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },

  formTitle: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  optionRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm },

  primaryBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: "center" },
  primaryBtnFlex: { flex: 1, backgroundColor: colors.brand.violet600, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 13, fontWeight: "700" },
  outlineBtn: { borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: "center" },
  outlineBtnFlex: { flex: 1, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: "center" },
  outlineBtnText: { color: colors.brand.violet400, fontSize: 13, fontWeight: "700" },
  dangerBtn: { borderWidth: 1, borderColor: colors.status.danger, backgroundColor: colors.status.dangerBg, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: "center" },
  dangerBtnText: { color: colors.status.danger, fontSize: 13, fontWeight: "700" },
});
