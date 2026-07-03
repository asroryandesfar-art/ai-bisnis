import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, AppState, Linking, Modal, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Badge, BadgeKind } from "../src/components/Badge";
import { Card } from "../src/components/Card";
import { api } from "../src/api/client";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { formatDate } from "../src/utils/format";

function num(v: any): string {
  return new Intl.NumberFormat("id-ID").format(Number(v || 0));
}

const STATUS_KIND: Record<string, BadgeKind> = {
  connected: "success", pending: "warning", error: "danger", disconnected: "neutral",
};

type Bot = { id: string; name: string };

export default function Channels() {
  const router = useRouter();
  const [bots, setBots] = useState<Bot[]>([]);
  const [channels, setChannels] = useState<any[]>([]);
  const [analytics, setAnalytics] = useState<any>({});
  const [waAccounts, setWaAccounts] = useState<any[]>([]);
  const [metaOAuth, setMetaOAuth] = useState<any>({});
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [botsRes, statusRes, analyticsRes, waRes, metaRes] = await Promise.allSettled([
        api.bots(), api.channelStatus(), api.channelAnalytics(30), api.whatsappEmbeddedStatus(), api.metaOAuthStatus(),
      ]);
      setBots(botsRes.status === "fulfilled" ? (botsRes.value as any[]).map((b) => ({ id: b.id, name: b.name })) : []);
      setChannels(statusRes.status === "fulfilled" ? statusRes.value.channels || [] : []);
      setAnalytics(analyticsRes.status === "fulfilled" ? analyticsRes.value : {});
      setWaAccounts(waRes.status === "fulfilled" ? waRes.value.accounts || [] : []);
      setMetaOAuth(metaRes.status === "fulfilled" ? metaRes.value : {});
    } catch (e: any) {
      setError(e?.message || "Gagal memuat channels.");
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

  function findChannel(type: string) {
    return channels.find((c) => c.channel_type === type && c.status !== "disconnected") || channels.find((c) => c.channel_type === type);
  }

  const connectedCount = channels.filter((c) => c.status === "connected").length + (waAccounts.filter((a) => a.connection_status === "connected").length > 0 ? 1 : 0);

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Channels</Text>
        <View style={{ width: 32 }} />
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
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Total Pesan</Text><Text style={styles.kpiValue}>{num(analytics.total_messages)}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Active Users</Text><Text style={styles.kpiValue}>{num(analytics.active_users)}</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Avg Response</Text><Text style={styles.kpiValue}>{Math.round(analytics.response_time_ms || 0)}ms</Text></View>
          <View style={styles.kpiCard}><Text style={styles.kpiLabel}>Connected</Text><Text style={styles.kpiValue}>{connectedCount}/5</Text></View>
        </View>

        <Text style={styles.sectionLabel}>STATUS CHANNEL</Text>

        <WhatsAppCard bots={bots} accounts={waAccounts} onChange={load} />
        <SimpleChannelCard type="telegram" label="Telegram" provider="Telegram Bot API" bots={bots} channel={findChannel("telegram")} onChange={load} />
        <SimpleChannelCard type="website" label="Website Chat" provider="BotNesia widget" bots={bots} channel={findChannel("website")} onChange={load} />
        <MetaChannelCard type="facebook" label="Facebook Messenger" bots={bots} channel={findChannel("facebook")} metaOAuth={metaOAuth} onChange={load} />
        <MetaChannelCard type="instagram" label="Instagram" bots={bots} channel={findChannel("instagram")} metaOAuth={metaOAuth} onChange={load} />

        <Text style={styles.sectionLabel}>PENGGUNAAN CHANNEL</Text>
        {(analytics.channel_usage || []).length === 0 ? (
          <Card><Text style={{ color: colors.text.muted, fontSize: 13, textAlign: "center" }}>Belum ada trafik channel.</Text></Card>
        ) : (
          <Card style={{ padding: 0 }}>
            {analytics.channel_usage.map((row: any, i: number) => (
              <View key={row.channel} style={[styles.usageRow, i > 0 && styles.usageRowBorder]}>
                <Text style={styles.usageChannel}>{row.channel}</Text>
                <Text style={styles.usageValue}>{num(row.messages)} pesan</Text>
                <Text style={styles.usageValue}>{num(row.active_users)} user</Text>
              </View>
            ))}
          </Card>
        )}
      </ScrollView>
    </View>
  );
}

// Builds the HTML page loaded into the hidden orchestrator WebView. Mirrors
// web's loadFacebookSdk()+waitForEmbeddedSignupMessage()+connectWhatsAppEmbedded()
// (frontend/app.js) as closely as possible: init the FB JS SDK, call
// FB.login() (which internally window.open()s the actual signup UI --
// react-native-webview's onOpenWindow renders that as a second, visible
// WebView), listen for the WA_EMBEDDED_SIGNUP "FINISH" postMessage Meta
// sends once the user picks a phone number, then relay both pieces of data
// back to React Native via window.ReactNativeWebView.postMessage.
function buildEmbeddedSignupHtml(appId: string, configId: string, apiVersion: string): string {
  return `<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;background:#0D1017">
<script>
  function post(payload) { window.ReactNativeWebView.postMessage(JSON.stringify(payload)); }
  window.addEventListener("message", function (event) {
    if (String(event.origin || "").indexOf("facebook.com") === -1) return;
    var payload = event.data;
    try { payload = typeof payload === "string" ? JSON.parse(payload) : payload; } catch (e) { return; }
    if (payload && payload.type === "WA_EMBEDDED_SIGNUP" && payload.event === "FINISH") {
      post({ type: "signup_data", data: payload.data || {} });
    }
  });
  window.fbAsyncInit = function () {
    FB.init({ appId: "${appId}", version: "${apiVersion}", xfbml: false });
    post({ type: "sdk_ready" });
    FB.login(function (response) {
      post({ type: "login_response", response: response });
    }, {
      config_id: "${configId}",
      response_type: "code",
      override_default_response_type: true,
      extras: { setup: {}, sessionInfoVersion: "3" },
    });
  };
  (function (d, s, id) {
    var js, fjs = d.getElementsByTagName(s)[0];
    if (d.getElementById(id)) return;
    js = d.createElement(s); js.id = id;
    js.src = "https://connect.facebook.net/en_US/sdk.js";
    js.onerror = function () { post({ type: "sdk_error" }); };
    fjs.parentNode.insertBefore(js, fjs);
  })(document, "script", "facebook-jssdk");
</script>
</body></html>`;
}

function WhatsAppCard({ bots, accounts, onChange }: { bots: Bot[]; accounts: any[]; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [botId, setBotId] = useState<string | null>(bots[0]?.id ?? null);
  const [busy, setBusy] = useState(false);
  const [WebViewComp, setWebViewComp] = useState<any>(null);
  const [signupHtml, setSignupHtml] = useState<string | null>(null);
  const [signupState, setSignupState] = useState<string | null>(null);
  const [popupUrl, setPopupUrl] = useState<string | null>(null);
  const loginCodeRef = useRef<string | null>(null);
  const signupDataRef = useRef<any>(null);

  const connected = accounts.filter((a) => a.connection_status === "connected");
  const status = connected.length ? "connected" : accounts.some((a) => a.connection_status === "error") ? "error" : "disconnected";

  function closeFlow() {
    setSignupHtml(null);
    setPopupUrl(null);
    loginCodeRef.current = null;
    signupDataRef.current = null;
  }

  async function finish() {
    if (!signupState || !botId || !loginCodeRef.current || !signupDataRef.current) return;
    setBusy(true);
    try {
      await api.whatsappEmbeddedCallback({
        state: signupState,
        code: loginCodeRef.current,
        waba_id: signupDataRef.current.waba_id,
        phone_number_id: signupDataRef.current.phone_number_id,
        business_id: signupDataRef.current.business_id,
      });
      closeFlow();
      onChange();
      Alert.alert("Berhasil", "WhatsApp terhubung.");
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa menyelesaikan koneksi WhatsApp.");
    } finally {
      setBusy(false);
    }
  }

  function onOrchestratorMessage(raw: string) {
    let msg: any;
    try { msg = JSON.parse(raw); } catch { return; }
    if (msg.type === "sdk_error") {
      Alert.alert("Gagal memuat Facebook SDK", "Periksa koneksi internet Anda, lalu coba lagi.");
      closeFlow();
    } else if (msg.type === "login_response") {
      setPopupUrl(null); // FB SDK closes its own popup once login resolves
      const code = msg.response?.authResponse?.code;
      if (!code) {
        Alert.alert("Dibatalkan", "Koneksi WhatsApp dibatalkan.");
        closeFlow();
        return;
      }
      loginCodeRef.current = code;
      if (signupDataRef.current) finish();
    } else if (msg.type === "signup_data") {
      signupDataRef.current = msg.data;
      if (loginCodeRef.current) finish();
    }
  }

  async function startConnect() {
    if (!botId) {
      Alert.alert("Belum ada agen", "Buat agen dulu di tab Agen.");
      return;
    }
    setBusy(true);
    try {
      const config = await api.whatsappEmbeddedConnect(botId);
      // Loaded lazily (never a top-level import) so a native-module issue
      // with this specific package can only ever fail this one action --
      // never crash the whole app at boot, same lazy-load pattern already
      // used for expo-document-picker elsewhere in this app.
      const { WebView } = await import("react-native-webview");
      setWebViewComp(() => WebView);
      setSignupState(config.state);
      setSignupHtml(buildEmbeddedSignupHtml(config.app_id, config.config_id, config.graph_api_version));
      setOpen(false);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memulai koneksi WhatsApp. Pastikan META_EMBEDDED_SIGNUP_CONFIG_ID sudah dikonfigurasi.");
    } finally {
      setBusy(false);
    }
  }

  function disconnect(bId: string) {
    Alert.alert("Putuskan WhatsApp?", "Agen ini akan berhenti menerima pesan WhatsApp.", [
      { text: "Batal", style: "cancel" },
      {
        text: "Putuskan", style: "destructive",
        onPress: async () => {
          setBusy(true);
          try {
            await api.whatsappEmbeddedDisconnect(bId);
            onChange();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa memutuskan WhatsApp.");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  }

  return (
    <Card style={styles.channelCard}>
      <View style={styles.channelHead}>
        <View style={styles.channelTitleRow}>
          <View style={[styles.channelDot, { backgroundColor: "#25D366" }]}><Text style={styles.channelDotText}>WA</Text></View>
          <View>
            <Text style={styles.channelName}>WhatsApp</Text>
            <Text style={styles.channelProvider}>Meta Embedded Signup</Text>
          </View>
        </View>
        <Badge label={status.toUpperCase()} kind={STATUS_KIND[status]} />
      </View>
      {accounts.length === 0 ? (
        <Text style={styles.channelStat}>Belum ada agen terhubung</Text>
      ) : (
        accounts.map((a) => {
          const bot = bots.find((b) => b.id === a.bot_id);
          return (
            <View key={a.bot_id} style={styles.statRow}>
              <Text style={styles.channelStat}>{bot?.name || "Agen"}</Text>
              <Text style={styles.channelStatValue}>{a.phone_number_id || "Belum lengkap"}</Text>
            </View>
          );
        })
      )}

      {busy && !signupHtml ? (
        <ActivityIndicator size="small" color={colors.brand.violet400} />
      ) : (
        <>
          {connected.map((a) => (
            <Pressable key={a.bot_id} style={styles.dangerBtn} onPress={() => disconnect(a.bot_id)}>
              <Text style={styles.dangerBtnText}>Putuskan {bots.find((b) => b.id === a.bot_id)?.name || "agen"}</Text>
            </Pressable>
          ))}
          <Pressable style={styles.primaryBtn} onPress={() => setOpen((v) => !v)}>
            <Text style={styles.primaryBtnText}>{open ? "Batal" : "Connect Agent"}</Text>
          </Pressable>
          {open ? (
            <View style={{ gap: spacing.sm, marginTop: spacing.sm }}>
              {bots.length > 1 ? (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
                  {bots.map((b) => (
                    <Pressable key={b.id} onPress={() => setBotId(b.id)} style={[styles.pill, botId === b.id && styles.pillActive]}>
                      <Text style={[styles.pillText, botId === b.id && styles.pillTextActive]}>{b.name}</Text>
                    </Pressable>
                  ))}
                </ScrollView>
              ) : null}
              <Pressable style={styles.primaryBtn} onPress={startConnect}>
                <Text style={styles.primaryBtnText}>Lanjutkan dengan Meta</Text>
              </Pressable>
            </View>
          ) : null}
        </>
      )}

      {/* Hidden orchestrator WebView -- runs the FB SDK + FB.login() call.
          Not rendered visibly; the actual signup UI the user interacts with
          is the popup WebView below, opened via onOpenWindow. */}
      {WebViewComp && signupHtml ? (
        <View style={{ height: 0, width: 0, opacity: 0 }}>
          <WebViewComp
            originWhitelist={["*"]}
            javaScriptEnabled
            domStorageEnabled
            setSupportMultipleWindows
            onOpenWindow={(e: any) => setPopupUrl(e.nativeEvent?.targetUrl || null)}
            onMessage={(e: any) => onOrchestratorMessage(e.nativeEvent.data)}
            source={{ html: signupHtml }}
          />
        </View>
      ) : null}

      {WebViewComp && popupUrl ? (
        <Modal visible animationType="slide" onRequestClose={closeFlow}>
          <View style={styles.webviewModal}>
            <View style={styles.webviewModalBar}>
              <Pressable onPress={closeFlow} hitSlop={8}>
                <Ionicons name="close" size={22} color={colors.text.primary} />
              </Pressable>
              <Text style={styles.webviewModalTitle}>Hubungkan WhatsApp</Text>
              <View style={{ width: 22 }} />
            </View>
            <WebViewComp source={{ uri: popupUrl }} originWhitelist={["*"]} javaScriptEnabled domStorageEnabled />
          </View>
        </Modal>
      ) : null}
    </Card>
  );
}

function SimpleChannelCard({
  type, label, provider, bots, channel, onChange,
}: {
  type: "telegram" | "website"; label: string; provider: string; bots: Bot[]; channel: any; onChange: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [botId, setBotId] = useState<string | null>(bots[0]?.id ?? null);
  const [displayName, setDisplayName] = useState("");
  const [domain, setDomain] = useState("");
  const [busy, setBusy] = useState(false);
  const connected = channel?.status === "connected";
  const status = channel?.status || "disconnected";

  async function connect() {
    if (!botId || !displayName.trim()) {
      Alert.alert("Lengkapi form", "Pilih agen dan isi nama tampilan.");
      return;
    }
    setBusy(true);
    try {
      await api.connectChannel({
        bot_id: botId, channel_type: type, display_name: displayName.trim(),
        credentials: {}, config: type === "website" && domain ? { domain } : {},
      });
      setOpen(false);
      setDisplayName("");
      setDomain("");
      onChange();
      Alert.alert("Berhasil", `${label} terhubung.`);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || `Tidak bisa menghubungkan ${label}.`);
    } finally {
      setBusy(false);
    }
  }

  function disconnect() {
    Alert.alert(`Putuskan ${label}?`, "Channel ini akan berhenti menerima pesan.", [
      { text: "Batal", style: "cancel" },
      {
        text: "Putuskan", style: "destructive",
        onPress: async () => {
          setBusy(true);
          try {
            await api.disconnectChannel(channel.id);
            onChange();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa memutuskan channel ini.");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  }

  return (
    <Card style={styles.channelCard}>
      <View style={styles.channelHead}>
        <View style={styles.channelTitleRow}>
          <View style={styles.channelDot}><Text style={styles.channelDotText}>{label.slice(0, 2).toUpperCase()}</Text></View>
          <View>
            <Text style={styles.channelName}>{label}</Text>
            <Text style={styles.channelProvider}>{provider}</Text>
          </View>
        </View>
        <Badge label={status.toUpperCase()} kind={STATUS_KIND[status] || "neutral"} />
      </View>
      <View style={styles.statRow}>
        <Text style={styles.channelStat}>Aktivitas terakhir</Text>
        <Text style={styles.channelStatValue}>{channel?.last_activity_at ? formatDate(channel.last_activity_at) : "—"}</Text>
      </View>
      <View style={styles.statRow}>
        <Text style={styles.channelStat}>Pesan</Text>
        <Text style={styles.channelStatValue}>{num(channel?.message_count || 0)}</Text>
      </View>

      {busy ? (
        <ActivityIndicator size="small" color={colors.brand.violet400} />
      ) : connected ? (
        <Pressable style={styles.dangerBtn} onPress={disconnect}>
          <Text style={styles.dangerBtnText}>Putuskan</Text>
        </Pressable>
      ) : (
        <>
          <Pressable style={styles.primaryBtn} onPress={() => setOpen((v) => !v)}>
            <Text style={styles.primaryBtnText}>{open ? "Batal" : `Hubungkan ${label}`}</Text>
          </Pressable>
          {open ? (
            <View style={{ gap: spacing.sm, marginTop: spacing.sm }}>
              {bots.length > 1 ? (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
                  {bots.map((b) => (
                    <Pressable key={b.id} onPress={() => setBotId(b.id)} style={[styles.pill, botId === b.id && styles.pillActive]}>
                      <Text style={[styles.pillText, botId === b.id && styles.pillTextActive]}>{b.name}</Text>
                    </Pressable>
                  ))}
                </ScrollView>
              ) : null}
              <TextInput
                style={styles.input}
                value={displayName}
                onChangeText={setDisplayName}
                placeholder="Nama tampilan (mis. Customer Service Utama)"
                placeholderTextColor={colors.text.muted}
              />
              {type === "website" ? (
                <TextInput
                  style={styles.input}
                  value={domain}
                  onChangeText={setDomain}
                  placeholder="Domain website (https://contoh.com)"
                  placeholderTextColor={colors.text.muted}
                  autoCapitalize="none"
                />
              ) : null}
              <Pressable style={styles.primaryBtn} onPress={connect}>
                <Text style={styles.primaryBtnText}>Hubungkan</Text>
              </Pressable>
            </View>
          ) : null}
        </>
      )}
    </Card>
  );
}

function MetaChannelCard({
  type, label, bots, channel, metaOAuth, onChange,
}: {
  type: "facebook" | "instagram"; label: string; bots: Bot[]; channel: any; metaOAuth: any; onChange: () => void;
}) {
  const [waiting, setWaiting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [botId, setBotId] = useState<string | null>(bots[0]?.id ?? null);
  const [pageId, setPageId] = useState<string | null>(null);
  const appState = useRef(AppState.currentState);

  const connected = channel?.status === "connected";
  const pages: any[] = metaOAuth?.pages || [];
  const usablePages = type === "instagram" ? pages.filter((p) => p.instagram?.id) : pages;
  const hasPendingSelection = waiting && metaOAuth?.status === "pending_selection" && usablePages.length > 0;

  // Meta OAuth completes in the system browser (no deep-link back into the
  // app), so re-check status once the user returns to the foreground --
  // mirrors web's URL-param based auto-continuation, adapted for native.
  useEffect(() => {
    if (!waiting) return;
    const sub = AppState.addEventListener("change", (next) => {
      if (appState.current.match(/inactive|background/) && next === "active") {
        onChange();
      }
      appState.current = next;
    });
    return () => sub.remove();
  }, [waiting, onChange]);

  async function startConnect() {
    if (!bots.length) {
      Alert.alert("Belum ada agen", "Buat agen dulu di tab Agen.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.metaOAuthStart(botId || bots[0].id, type);
      setWaiting(true);
      await Linking.openURL(res.auth_url);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa memulai login Meta.");
    } finally {
      setBusy(false);
    }
  }

  async function checkStatus() {
    setBusy(true);
    try {
      await onChange();
    } finally {
      setBusy(false);
    }
  }

  async function submitSelection() {
    if (!botId || !pageId) {
      Alert.alert("Lengkapi pilihan", "Pilih agen dan akun yang ingin dihubungkan.");
      return;
    }
    const page = usablePages.find((p) => String(p.id) === pageId);
    setBusy(true);
    try {
      await api.metaOAuthSelect({
        bot_id: botId, page_id: pageId, channels: [type],
        instagram_id: type === "instagram" ? page?.instagram?.id : undefined,
      });
      setWaiting(false);
      onChange();
      Alert.alert("Berhasil", `${label} terhubung.`);
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || `Tidak bisa menghubungkan ${label}.`);
    } finally {
      setBusy(false);
    }
  }

  function disconnect() {
    Alert.alert(`Putuskan ${label}?`, "Channel ini akan berhenti menerima pesan.", [
      { text: "Batal", style: "cancel" },
      {
        text: "Putuskan", style: "destructive",
        onPress: async () => {
          setBusy(true);
          try {
            await api.disconnectChannel(channel.id);
            onChange();
          } catch (e: any) {
            Alert.alert("Gagal", e?.message || "Tidak bisa memutuskan channel ini.");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  }

  async function refresh() {
    setBusy(true);
    try {
      await api.metaOAuthRefresh();
      onChange();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || "Tidak bisa refresh akses.");
    } finally {
      setBusy(false);
    }
  }

  const status = connected ? "connected" : channel?.status || "disconnected";

  return (
    <Card style={styles.channelCard}>
      <View style={styles.channelHead}>
        <View style={styles.channelTitleRow}>
          <View style={styles.channelDot}><Text style={styles.channelDotText}>{label.slice(0, 2).toUpperCase()}</Text></View>
          <View>
            <Text style={styles.channelName}>{label}</Text>
            <Text style={styles.channelProvider}>Meta OAuth</Text>
          </View>
        </View>
        <Badge label={status.toUpperCase()} kind={STATUS_KIND[status] || "neutral"} />
      </View>
      <View style={styles.statRow}>
        <Text style={styles.channelStat}>Agen</Text>
        <Text style={styles.channelStatValue}>{bots.find((b) => b.id === channel?.bot_id)?.name || "Belum ditugaskan"}</Text>
      </View>
      <View style={styles.statRow}>
        <Text style={styles.channelStat}>Token expiry</Text>
        <Text style={styles.channelStatValue}>{metaOAuth?.token_expires_at ? formatDate(metaOAuth.token_expires_at) : "—"}</Text>
      </View>

      {busy ? (
        <ActivityIndicator size="small" color={colors.brand.violet400} />
      ) : connected ? (
        <View style={styles.actionRow}>
          <Pressable style={styles.outlineBtn} onPress={refresh}>
            <Text style={styles.outlineBtnText}>Refresh Akses</Text>
          </Pressable>
          <Pressable style={styles.dangerBtnFlex} onPress={disconnect}>
            <Text style={styles.dangerBtnText}>Putuskan</Text>
          </Pressable>
        </View>
      ) : hasPendingSelection ? (
        <View style={{ gap: spacing.sm }}>
          <Text style={styles.hintText}>Pilih akun {type === "instagram" ? "Instagram Business" : "Facebook Page"} yang ingin dihubungkan:</Text>
          {bots.length > 1 ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
              {bots.map((b) => (
                <Pressable key={b.id} onPress={() => setBotId(b.id)} style={[styles.pill, botId === b.id && styles.pillActive]}>
                  <Text style={[styles.pillText, botId === b.id && styles.pillTextActive]}>{b.name}</Text>
                </Pressable>
              ))}
            </ScrollView>
          ) : null}
          {usablePages.map((p) => (
            <Pressable
              key={p.id}
              onPress={() => setPageId(String(p.id))}
              style={[styles.optionRow, pageId === String(p.id) && styles.optionRowActive]}
            >
              <Text style={styles.optionText}>
                {type === "instagram" ? `${p.instagram?.username || "Instagram"} · ${p.name}` : p.name}
              </Text>
              {pageId === String(p.id) ? <Ionicons name="checkmark-circle" size={18} color={colors.brand.violet400} /> : null}
            </Pressable>
          ))}
          <Pressable style={styles.primaryBtn} onPress={submitSelection}>
            <Text style={styles.primaryBtnText}>Hubungkan</Text>
          </Pressable>
        </View>
      ) : waiting ? (
        <View style={{ gap: spacing.sm }}>
          <Text style={styles.hintText}>Selesaikan login di browser, lalu kembali ke app ini.</Text>
          <Pressable style={styles.primaryBtn} onPress={checkStatus}>
            <Text style={styles.primaryBtnText}>Saya sudah login, lanjutkan</Text>
          </Pressable>
        </View>
      ) : (
        <Pressable style={styles.primaryBtn} onPress={startConnect}>
          <Text style={styles.primaryBtnText}>{type === "instagram" ? "Connect Instagram Business" : "Connect Facebook"}</Text>
        </Pressable>
      )}
    </Card>
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
  kpiValue: { color: colors.text.primary, fontSize: 18, fontWeight: "800" },

  channelCard: { gap: spacing.sm },
  channelHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  channelTitleRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  channelDot: { width: 34, height: 34, borderRadius: radius.md, backgroundColor: colors.brand.violet600, alignItems: "center", justifyContent: "center" },
  channelDotText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  channelName: { color: colors.text.primary, fontSize: 14, fontWeight: "700" },
  channelProvider: { color: colors.text.faint, fontSize: 10, marginTop: 1 },
  statRow: { flexDirection: "row", justifyContent: "space-between" },
  channelStat: { color: colors.text.muted, fontSize: 12 },
  channelStatValue: { color: colors.text.body, fontSize: 12, fontWeight: "600" },
  hintText: { color: colors.text.faint, fontSize: 11, lineHeight: 16 },

  primaryBtn: { backgroundColor: colors.brand.violet600, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  primaryBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  dangerBtn: { borderWidth: 1, borderColor: colors.status.danger, backgroundColor: colors.status.dangerBg, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  dangerBtnFlex: { flex: 1, borderWidth: 1, borderColor: colors.status.danger, backgroundColor: colors.status.dangerBg, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  dangerBtnText: { color: colors.status.danger, fontSize: 12, fontWeight: "700" },
  outlineBtn: { flex: 1, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt, borderRadius: radius.sm, paddingVertical: spacing.sm + 2, alignItems: "center" },
  outlineBtnText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "700" },
  actionRow: { flexDirection: "row", gap: spacing.sm },

  pill: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border },
  pillActive: { backgroundColor: colors.brand.violet600, borderColor: colors.brand.violet600 },
  pillText: { color: colors.text.muted, fontSize: 12, fontWeight: "700" },
  pillTextActive: { color: "#fff" },
  input: {
    backgroundColor: colors.bg.cardAlt, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, color: colors.text.primary, fontSize: 13,
  },
  optionRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.md,
    borderRadius: radius.sm, borderWidth: 1, borderColor: colors.bg.border, backgroundColor: colors.bg.cardAlt,
  },
  optionRowActive: { borderColor: colors.brand.violet500 },
  optionText: { color: colors.text.body, fontSize: 12, flex: 1 },

  usageRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: spacing.md },
  usageRowBorder: { borderTopWidth: 1, borderTopColor: colors.bg.border },
  usageChannel: { color: colors.text.primary, fontSize: 13, fontWeight: "700", flex: 1, textTransform: "capitalize" },
  usageValue: { color: colors.text.muted, fontSize: 11 },

  webviewModal: { flex: 1, backgroundColor: colors.bg.base },
  webviewModalBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingTop: spacing.xxl, paddingBottom: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.bg.border,
  },
  webviewModalTitle: { color: colors.text.primary, fontSize: 15, fontWeight: "800" },
});
