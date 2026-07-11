import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View,
} from "react-native";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

type Msg = { id: string; role: "bot" | "user"; text: string; at: number };

function initials(name: string) {
  return name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
}

function timeLabel(ms: number) {
  return new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit" }).format(new Date(ms));
}

export default function Chat() {
  const router = useRouter();
  const params = useLocalSearchParams<{ botId?: string }>();
  const [bot, setBot] = useState<any>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<ScrollView>(null);

  useEffect(() => {
    (async () => {
      try {
        const bots: any[] = await api.bots();
        const found = params.botId ? bots.find((b) => String(b.id) === String(params.botId)) : bots[0];
        if (!found) {
          setError("Belum ada agen. Buat agen dulu di tab Agen.");
          return;
        }
        setBot(found);
        setMessages([{ id: "greet", role: "bot", text: found.greeting || "Halo! Ada yang bisa saya bantu?", at: Date.now() }]);
      } catch (e: any) {
        setError(e?.message || "Gagal memuat agen.");
      }
    })();
  }, [params.botId]);

  async function send() {
    const text = input.trim();
    if (!text || sending || !bot) return;
    setInput("");
    const userMsg: Msg = { id: `u${Date.now()}`, role: "user", text, at: Date.now() };
    setMessages((m) => [...m, userMsg]);
    setSending(true);
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 50);
    try {
      const res = await api.chat(bot.id, text, sessionId);
      setSessionId(res.session_id || sessionId);
      setMessages((m) => [...m, { id: `b${Date.now()}`, role: "bot", text: res.answer || "(tidak ada jawaban)", at: Date.now() }]);
    } catch (e: any) {
      setMessages((m) => [...m, { id: `e${Date.now()}`, role: "bot", text: e?.message || "Gagal mengirim pesan.", at: Date.now() }]);
    } finally {
      setSending(false);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 50);
    }
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <View style={styles.agentHead}>
          <View style={[styles.avatar, { backgroundColor: bot?.primary_color || colors.brand.violet600 }]}>
            <Text style={styles.avatarText}>{bot ? initials(bot.name) : "AI"}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <View style={styles.nameRow}>
              <Text style={styles.agentName} numberOfLines={1}>{bot?.name || "Agen AI"}</Text>
              {bot?.status === "active" ? (
                <View style={styles.aktifBadge}><Text style={styles.aktifText}>AKTIF</Text></View>
              ) : null}
            </View>
            <Text style={styles.agentSub}>{bot ? (bot.status === "active" ? "Online" : "Offline") : "—"}</Text>
          </View>
        </View>
      </View>

      <ScrollView ref={scrollRef} contentContainerStyle={styles.messages} onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: false })}>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {messages.map((m) =>
          m.role === "user" ? (
            <View key={m.id} style={styles.userRow}>
              <View style={[styles.userBubble, { backgroundColor: colors.brand.violet500 }]}>
                <Text style={styles.userText}>{m.text}</Text>
              </View>
              <Text style={styles.timeTextRight}>{timeLabel(m.at)}</Text>
            </View>
          ) : (
            <View key={m.id} style={styles.botRow}>
              <View style={[styles.avatarSm, { backgroundColor: bot?.primary_color || colors.brand.violet600 }]}>
                <MaterialCommunityIcons name="robot-outline" size={14} color="#fff" />
              </View>
              <View style={{ flexShrink: 1 }}>
                <View style={styles.botBubble}>
                  <Text style={styles.botText}>{m.text}</Text>
                </View>
                <Text style={styles.timeTextLeft}>{timeLabel(m.at)}</Text>
              </View>
            </View>
          )
        )}
        {sending ? (
          <View style={styles.botRow}>
            <View style={[styles.avatarSm, { backgroundColor: bot?.primary_color || colors.brand.violet600 }]}>
              <MaterialCommunityIcons name="robot-outline" size={14} color="#fff" />
            </View>
            <View style={styles.botBubble}>
              <ActivityIndicator size="small" color={colors.brand.violet400} />
            </View>
          </View>
        ) : null}
      </ScrollView>

      <View style={styles.composer}>
        <TextInput
          style={styles.composerInput}
          value={input}
          onChangeText={setInput}
          placeholder="Ketik pesan…"
          placeholderTextColor={colors.text.muted}
          multiline
          editable={!!bot}
          onSubmitEditing={send}
        />
        <Pressable style={[styles.sendBtn, (!input.trim() || sending) && styles.sendBtnDisabled]} onPress={send} disabled={!input.trim() || sending}>
          <Ionicons name="send" size={18} color="#fff" />
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  topBar: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingTop: spacing.xl, paddingBottom: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.bg.border,
  },
  iconBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  agentHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flex: 1 },
  avatar: { width: 40, height: 40, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  nameRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  agentName: { color: colors.text.primary, fontSize: 15, fontWeight: "800", flexShrink: 1 },
  aktifBadge: { backgroundColor: colors.status.successBgStrong, paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.full },
  aktifText: { color: colors.status.success, fontSize: 9, fontWeight: "800" },
  agentSub: { color: colors.text.muted, fontSize: 11, marginTop: 1 },
  messages: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xl },
  error: { color: colors.status.danger, fontSize: 13, textAlign: "center" },
  userRow: { alignItems: "flex-end" },
  userBubble: { maxWidth: "82%", paddingHorizontal: spacing.md, paddingVertical: spacing.md, borderRadius: radius.lg, borderBottomRightRadius: 4 },
  userText: { color: "#fff", fontSize: 14, lineHeight: 20 },
  botRow: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, maxWidth: "88%" },
  avatarSm: { width: 26, height: 26, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  botBubble: { backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border, paddingHorizontal: spacing.md, paddingVertical: spacing.md, borderRadius: radius.lg, borderBottomLeftRadius: 4, flexShrink: 1 },
  botText: { color: colors.text.body, fontSize: 14, lineHeight: 20 },
  timeTextLeft: { color: colors.text.faint, fontSize: 10, marginTop: 2, marginLeft: spacing.xs },
  timeTextRight: { color: colors.text.faint, fontSize: 10, marginTop: 2, marginRight: spacing.xs, alignSelf: "flex-end" },
  composer: {
    flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.bg.border, backgroundColor: colors.bg.app,
  },
  composerInput: {
    flex: 1, backgroundColor: colors.bg.card, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.lg,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md, color: colors.text.primary, fontSize: 14, maxHeight: 120,
  },
  sendBtn: { width: 44, height: 44, borderRadius: radius.lg, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  sendBtnDisabled: { opacity: 0.5 },
});
