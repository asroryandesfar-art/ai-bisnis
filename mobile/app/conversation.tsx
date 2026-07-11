import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Badge } from "../src/components/Badge";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

type Msg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  model: string | null;
  latency_ms: number | null;
  created_at: string;
  source_chunks: string[] | null;
  intent: string | null;
  selected_agent: string | null;
  routing_confidence: number | null;
  handoff_status: string | null;
  feedback_rating: "helpful" | "not_helpful" | null;
};

type SourceChunk = { id: string; content: string; document_id: string; chunk_index: number; created_at: string };

function initials(name: string) {
  return name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "AN";
}

function timeLabel(iso: string) {
  return new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export default function ConversationDetail() {
  const router = useRouter();
  const params = useLocalSearchParams<{ id: string; name?: string }>();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyFeedback, setBusyFeedback] = useState<string | null>(null);
  const [openSources, setOpenSources] = useState<Record<string, SourceChunk[] | "loading">>({});

  useEffect(() => {
    (async () => {
      try {
        setError(null);
        const res = await api.conversationMessages(params.id);
        setMessages(res as Msg[]);
      } catch (e: any) {
        setError(e?.message || "Gagal memuat percakapan.");
      } finally {
        setLoading(false);
      }
    })();
  }, [params.id]);

  async function rate(msg: Msg, rating: "helpful" | "not_helpful") {
    setBusyFeedback(msg.id);
    try {
      await api.submitFeedback(msg.id, params.id, rating);
      setMessages((prev) => prev.map((m) => (m.id === msg.id ? { ...m, feedback_rating: rating } : m)));
    } catch {
      // Non-critical action -- silently ignore, thumbs just won't update.
    } finally {
      setBusyFeedback(null);
    }
  }

  async function toggleSources(msg: Msg) {
    if (openSources[msg.id] !== undefined) {
      setOpenSources((prev) => {
        const next = { ...prev };
        delete next[msg.id];
        return next;
      });
      return;
    }
    setOpenSources((prev) => ({ ...prev, [msg.id]: "loading" }));
    try {
      const chunks = await api.messageSources(msg.id);
      setOpenSources((prev) => ({ ...prev, [msg.id]: chunks as SourceChunk[] }));
    } catch {
      setOpenSources((prev) => ({ ...prev, [msg.id]: [] }));
    }
  }

  const displayName = params.name || "Pelanggan";

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <View style={styles.headAvatar}>
          <Text style={styles.headAvatarText}>{initials(displayName)}</Text>
        </View>
        <Text style={styles.topTitle} numberOfLines={1}>{displayName}</Text>
        <View style={{ width: 32 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brand.violet400} /></View>
      ) : error ? (
        <View style={styles.center}><Text style={{ color: colors.status.danger, fontSize: 13 }}>{error}</Text></View>
      ) : (
        <ScrollView contentContainerStyle={styles.messages}>
          {messages.length === 0 ? (
            <Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada pesan.</Text>
          ) : null}
          {messages.map((m) => {
            const isAssistant = m.role === "assistant" && !String(m.model || "").startsWith("human");
            const sourcesCount = m.source_chunks?.length || 0;
            const sourcesState = openSources[m.id];
            return m.role === "user" ? (
              <View key={m.id} style={styles.userRow}>
                <View style={styles.userBubble}>
                  <Text style={styles.userText}>{m.content}</Text>
                </View>
                <Text style={styles.timeTextRight}>{timeLabel(m.created_at)}</Text>
              </View>
            ) : (
              <View key={m.id} style={styles.botRow}>
                <View style={styles.avatarSm}>
                  <MaterialCommunityIcons name="robot-outline" size={14} color="#fff" />
                </View>
                <View style={{ flexShrink: 1, flex: 1 }}>
                  <View style={styles.botBubble}>
                    <Text style={styles.botText}>{m.content}</Text>

                    {isAssistant ? (
                      <View style={styles.feedbackRow}>
                        <Pressable
                          onPress={() => rate(m, "helpful")}
                          disabled={busyFeedback === m.id}
                          style={[styles.feedbackBtn, m.feedback_rating === "helpful" && styles.feedbackBtnActivePositive]}
                        >
                          <Ionicons
                            name="thumbs-up-outline"
                            size={13}
                            color={m.feedback_rating === "helpful" ? colors.status.success : colors.text.muted}
                          />
                        </Pressable>
                        <Pressable
                          onPress={() => rate(m, "not_helpful")}
                          disabled={busyFeedback === m.id}
                          style={[styles.feedbackBtn, m.feedback_rating === "not_helpful" && styles.feedbackBtnActiveNegative]}
                        >
                          <Ionicons
                            name="thumbs-down-outline"
                            size={13}
                            color={m.feedback_rating === "not_helpful" ? colors.status.danger : colors.text.muted}
                          />
                        </Pressable>
                      </View>
                    ) : null}

                    {isAssistant && sourcesCount > 0 ? (
                      <Pressable onPress={() => toggleSources(m)} style={styles.sourcesBtn}>
                        <MaterialCommunityIcons name="book-open-variant" size={13} color={colors.brand.violet400} />
                        <Text style={styles.sourcesBtnText}>
                          {sourcesState === undefined ? `Lihat sumber (${sourcesCount})` : "Sembunyikan sumber"}
                        </Text>
                      </Pressable>
                    ) : null}

                    {sourcesState === "loading" ? (
                      <ActivityIndicator size="small" color={colors.brand.violet400} style={{ marginTop: spacing.sm }} />
                    ) : Array.isArray(sourcesState) ? (
                      <View style={styles.sourceList}>
                        {sourcesState.length === 0 ? (
                          <Text style={styles.sourceEmpty}>Tidak ada sumber dokumen untuk jawaban ini.</Text>
                        ) : (
                          sourcesState.map((s) => (
                            <View key={s.id} style={styles.sourceItem}>
                              <Text style={styles.sourceMeta}>Chunk #{s.chunk_index}</Text>
                              <Text style={styles.sourceContent} numberOfLines={4}>{s.content}</Text>
                            </View>
                          ))
                        )}
                      </View>
                    ) : null}

                    {isAssistant && (m.intent || m.selected_agent) ? (
                      <View style={styles.routingRow}>
                        {m.intent ? <Badge label={`Intent: ${m.intent}`} kind="neutral" /> : null}
                        {m.selected_agent ? <Badge label={`Agent: ${m.selected_agent}`} kind="neutral" /> : null}
                        {m.routing_confidence != null ? <Badge label={`Conf: ${Math.round(m.routing_confidence * 100)}%`} kind="neutral" /> : null}
                        {m.handoff_status ? <Badge label={`Handoff: ${m.handoff_status}`} kind="warning" /> : null}
                      </View>
                    ) : null}
                  </View>
                  <Text style={styles.timeTextLeft}>
                    {timeLabel(m.created_at)}{m.latency_ms ? ` · ${m.latency_ms}ms` : ""}
                  </Text>
                </View>
              </View>
            );
          })}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  topBar: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingTop: spacing.xl, paddingBottom: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.bg.border,
  },
  iconBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  headAvatar: { width: 30, height: 30, borderRadius: radius.sm, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  headAvatarText: { color: "#fff", fontWeight: "800", fontSize: 11 },
  topTitle: { flex: 1, color: colors.text.primary, fontSize: 15, fontWeight: "800" },

  messages: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  userRow: { alignItems: "flex-end" },
  userBubble: { maxWidth: "82%", backgroundColor: colors.brand.violet600, paddingHorizontal: spacing.md, paddingVertical: spacing.md, borderRadius: radius.lg, borderBottomRightRadius: 4 },
  userText: { color: "#fff", fontSize: 14, lineHeight: 20 },
  botRow: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, maxWidth: "92%" },
  avatarSm: { width: 26, height: 26, borderRadius: radius.sm, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  botBubble: { backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border, paddingHorizontal: spacing.md, paddingVertical: spacing.md, borderRadius: radius.lg, borderBottomLeftRadius: 4, flexShrink: 1 },
  botText: { color: colors.text.body, fontSize: 14, lineHeight: 20 },
  timeTextLeft: { color: colors.text.faint, fontSize: 10, marginTop: 2, marginLeft: spacing.xs },
  timeTextRight: { color: colors.text.faint, fontSize: 10, marginTop: 2, marginRight: spacing.xs, alignSelf: "flex-end" },

  feedbackRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  feedbackBtn: { paddingHorizontal: spacing.sm + 2, paddingVertical: 4, borderRadius: radius.full, backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border },
  feedbackBtnActivePositive: { backgroundColor: colors.status.successBg, borderColor: colors.status.success },
  feedbackBtnActiveNegative: { backgroundColor: colors.status.dangerBg, borderColor: colors.status.danger },

  sourcesBtn: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: spacing.sm },
  sourcesBtnText: { color: colors.brand.violet400, fontSize: 11, fontWeight: "700" },
  sourceList: { marginTop: spacing.sm, gap: spacing.sm },
  sourceItem: { backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, padding: spacing.sm, borderWidth: 1, borderColor: colors.bg.border },
  sourceMeta: { color: colors.text.faint, fontSize: 10, fontWeight: "700", marginBottom: 2 },
  sourceContent: { color: colors.text.body, fontSize: 11, lineHeight: 16 },
  sourceEmpty: { color: colors.text.muted, fontSize: 11 },

  routingRow: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: spacing.sm },
});
