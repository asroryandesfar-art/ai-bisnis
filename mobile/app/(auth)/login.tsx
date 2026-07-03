import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  Alert,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { GradientButton } from "../../src/components/GradientButton";
import { TextField } from "../../src/components/TextField";
import { api, APIError } from "../../src/api/client";
import { tokenStore } from "../../src/auth/tokenStore";
import { colors } from "../../src/theme/colors";
import { radius, spacing } from "../../src/theme/spacing";

export default function Login() {
  const router = useRouter();
  const [tab, setTab] = useState<"login" | "register">("login");

  // Login fields
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  // Register fields -- same 3 fields as the web's #register-form (org_name,
  // email, password min 8), no separate full_name (web doesn't collect it
  // either; RegisterReq.full_name is optional server-side).
  const [orgName, setOrgName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [showRegPassword, setShowRegPassword] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleLogin() {
    if (!email || !password) {
      setError("Email dan password wajib diisi.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const { token } = await api.login(email.trim(), password);
      await tokenStore.set(token);
      router.replace("/beranda");
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Login gagal. Coba lagi.");
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister() {
    if (!orgName || !regEmail || !regPassword) {
      setError("Nama bisnis, email, dan password wajib diisi.");
      return;
    }
    if (regPassword.length < 8) {
      setError("Password minimal 8 karakter.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const { token } = await api.register(orgName.trim(), regEmail.trim(), regPassword);
      await tokenStore.set(token);
      router.replace("/beranda");
    } catch (e) {
      setError(e instanceof APIError ? e.message : "Pendaftaran gagal. Coba lagi.");
    } finally {
      setLoading(false);
    }
  }

  function switchTab(next: "login" | "register") {
    setTab(next);
    setError(null);
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <View style={styles.brandRow}>
          <Image source={require("../../assets/brand-logo.png")} style={styles.brandIcon} />
          <View>
            <Text style={styles.brandTitle}>BotNesia</Text>
            <Text style={styles.brandSubtitle}>AI Business Platform</Text>
          </View>
        </View>

        <View style={styles.tabRow}>
          <Pressable style={tab === "login" ? styles.tabActive : styles.tabInactive} onPress={() => switchTab("login")}>
            <Text style={tab === "login" ? styles.tabActiveText : styles.tabInactiveText}>Masuk</Text>
          </Pressable>
          <Pressable style={tab === "register" ? styles.tabActive : styles.tabInactive} onPress={() => switchTab("register")}>
            <Text style={tab === "register" ? styles.tabActiveText : styles.tabInactiveText}>Daftar</Text>
          </Pressable>
        </View>

        {tab === "login" ? (
          <>
            <Text style={styles.h1}>Selamat Datang</Text>
            <Text style={styles.h1Sub}>Masuk ke dashboard AI Anda</Text>

            <View style={{ gap: spacing.lg, marginTop: spacing.lg }}>
              <TextField
                label="Email"
                placeholder="anda@perusahaan.com"
                autoCapitalize="none"
                keyboardType="email-address"
                value={email}
                onChangeText={setEmail}
              />
              <View>
                <TextField
                  label="Password"
                  placeholder="••••••••••"
                  secureTextEntry={!showPassword}
                  value={password}
                  onChangeText={setPassword}
                />
                <Pressable style={styles.eyeButton} onPress={() => setShowPassword((v) => !v)}>
                  <Ionicons name={showPassword ? "eye-off-outline" : "eye-outline"} size={18} color={colors.text.muted} />
                </Pressable>
              </View>
            </View>

            <Pressable style={styles.forgotWrap} onPress={() => Alert.alert("Segera hadir", "Reset password lewat app mobile belum tersedia.")}>
              <Text style={styles.forgotText}>Lupa password?</Text>
            </Pressable>

            {error ? <Text style={styles.error}>{error}</Text> : null}

            <View style={{ marginTop: spacing.lg }}>
              <GradientButton title="Masuk ke Dashboard  →" onPress={handleLogin} loading={loading} />
            </View>
          </>
        ) : (
          <>
            <Text style={styles.h1}>Buat Workspace</Text>
            <Text style={styles.h1Sub}>Siapkan akun dan organisasi baru</Text>

            <View style={{ gap: spacing.lg, marginTop: spacing.lg }}>
              <TextField
                label="Nama bisnis"
                placeholder="Toko Maju Jaya"
                value={orgName}
                onChangeText={setOrgName}
              />
              <TextField
                label="Email"
                placeholder="anda@perusahaan.com"
                autoCapitalize="none"
                keyboardType="email-address"
                value={regEmail}
                onChangeText={setRegEmail}
              />
              <View>
                <TextField
                  label="Password"
                  placeholder="Minimal 8 karakter"
                  secureTextEntry={!showRegPassword}
                  value={regPassword}
                  onChangeText={setRegPassword}
                />
                <Pressable style={styles.eyeButton} onPress={() => setShowRegPassword((v) => !v)}>
                  <Ionicons name={showRegPassword ? "eye-off-outline" : "eye-outline"} size={18} color={colors.text.muted} />
                </Pressable>
              </View>
            </View>

            {error ? <Text style={styles.error}>{error}</Text> : null}

            <View style={{ marginTop: spacing.lg }}>
              <GradientButton title="Buat Akun  →" onPress={handleRegister} loading={loading} />
            </View>
          </>
        )}

        <View style={styles.dividerRow}>
          <View style={styles.dividerLine} />
          <Text style={styles.dividerText}>atau lanjutkan dengan</Text>
          <View style={styles.dividerLine} />
        </View>

        <View style={styles.socialRow}>
          <Pressable style={styles.socialButton} onPress={() => Alert.alert("Segera hadir", "Login Google belum tersedia di app mobile.")}>
            <Text style={styles.socialText}>Google</Text>
          </Pressable>
          <Pressable style={styles.socialButton} onPress={() => Alert.alert("Segera hadir", "Login Microsoft belum tersedia di app mobile.")}>
            <Text style={styles.socialText}>Microsoft</Text>
          </Pressable>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg.base },
  container: { padding: spacing.xl, paddingTop: spacing.xxl + spacing.lg, gap: 0 },
  brandRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginBottom: spacing.xl },
  brandIcon: { width: 44, height: 44, borderRadius: radius.md, resizeMode: "cover" },
  brandTitle: { color: colors.text.primary, fontSize: 18, fontWeight: "800" },
  brandSubtitle: { color: colors.text.muted, fontSize: 11, fontWeight: "600" },
  tabRow: { flexDirection: "row", backgroundColor: colors.bg.card, borderRadius: radius.lg, padding: 4, marginBottom: spacing.xl },
  tabActive: { flex: 1, backgroundColor: colors.brand.violet600, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: "center" },
  tabActiveText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  tabInactive: { flex: 1, paddingVertical: spacing.md, alignItems: "center" },
  tabInactiveText: { color: colors.text.muted, fontWeight: "700", fontSize: 13 },
  h1: { color: colors.text.primary, fontSize: 28, fontWeight: "800" },
  h1Sub: { color: colors.text.muted, fontSize: 13, marginTop: 4 },
  eyeButton: { position: "absolute", right: spacing.lg, top: 34 },
  forgotWrap: { alignSelf: "flex-end", marginTop: spacing.sm },
  forgotText: { color: colors.brand.violet400, fontSize: 12, fontWeight: "600" },
  error: { color: colors.status.danger, fontSize: 12, marginTop: spacing.md },
  dividerRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.xl },
  dividerLine: { flex: 1, height: 1, backgroundColor: colors.bg.border },
  dividerText: { color: colors.text.faint, fontSize: 11 },
  socialRow: { flexDirection: "row", gap: spacing.md, marginTop: spacing.lg },
  socialButton: {
    flex: 1, borderWidth: 1, borderColor: colors.bg.border, borderRadius: radius.lg,
    paddingVertical: spacing.md + 2, alignItems: "center", backgroundColor: colors.bg.card,
  },
  socialText: { color: colors.text.body, fontWeight: "600", fontSize: 13 },
});
