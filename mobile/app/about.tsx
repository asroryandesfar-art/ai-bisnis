import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Card } from "../src/components/Card";
import { colors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";

// Static content mirrored verbatim from web's renderAbout + renderFounderStory
// (frontend/app.js) -- combined into one mobile screen since both are short
// static marketing/identity pages.
export default function About() {
  const router = useRouter();

  return (
    <View style={styles.flex}>
      <View style={styles.topBar}>
        <Pressable style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text.primary} />
        </Pressable>
        <Text style={styles.topTitle}>Tentang BotNesia</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.hero}>
          <Image source={require("../assets/brand-logo.png")} style={styles.logo} resizeMode="contain" />
          <Text style={styles.eyebrow}>ABOUT BOTNESIA</Text>
          <Text style={styles.heroTitle}>AI Workforce untuk Setiap Bisnis Indonesia</Text>
          <Text style={styles.heroBody}>
            BotNesia membangun tim AI — Customer Service, Sales, Marketing, Finance, HR, Operations, Security, hingga
            Executive Assistant — yang bekerja 24/7 untuk bisnis Anda, tanpa perlu tim teknologi mahal.
          </Text>
        </View>

        <Card style={styles.section}>
          <Text style={styles.eyebrow}>VISION</Text>
          <Text style={styles.sectionTitle}>Visi Kami</Text>
          <Text style={styles.body}>
            Menjadi platform AI Workforce nomor satu di Indonesia — tempat setiap UMKM hingga perusahaan besar bisa
            memiliki tim AI selengkap perusahaan teknologi besar, tanpa harus membangun tim engineering sendiri.
          </Text>
        </Card>

        <Card style={styles.section}>
          <Text style={styles.eyebrow}>MISSION</Text>
          <Text style={styles.sectionTitle}>Misi Kami</Text>
          <Text style={styles.body}>
            Membantu jutaan UMKM dan perusahaan Indonesia menggunakan AI tanpa harus memiliki tim teknologi mahal —
            cukup satu platform, BotNesia menghadirkan tenaga kerja AI yang siap bekerja di berbagai fungsi bisnis
            sekaligus.
          </Text>
        </Card>

        <Card style={styles.section}>
          <Text style={styles.eyebrow}>WHY BOTNESIA EXISTS</Text>
          <Text style={styles.sectionTitle}>Mengapa BotNesia Dibangun</Text>
          <Text style={styles.body}>
            Sebagian besar bisnis di Indonesia — dari toko online kecil hingga perusahaan menengah — tidak punya akses
            ke tim data scientist atau engineer AI seperti perusahaan besar. Software enterprise yang ada pun sering
            terlalu mahal dan rumit untuk skala mereka.
          </Text>
          <Text style={styles.body}>
            BotNesia hadir untuk menutup jarak itu: satu platform yang menggabungkan AI Customer Service, Sales,
            Marketing, Finance, HR, Operations, Security, dan Executive Assistant — semuanya terhubung, semuanya bisa
            dipantau dan disetujui manusia, dan semuanya bisa dijalankan tanpa tim teknologi internal.
          </Text>
        </Card>

        <Card style={styles.section}>
          <Text style={styles.eyebrow}>FOUNDER STORY</Text>
          <Text style={styles.sectionTitle}>Cerita di Balik BotNesia</Text>
          <Text style={styles.founderName}>Asrori — Pendiri BotNesia</Text>
          <Text style={styles.quote}>
            "Membantu jutaan UMKM dan perusahaan Indonesia menggunakan AI tanpa harus memiliki tim teknologi mahal."
          </Text>
          <Text style={styles.body}>
            Asrori melihat dari dekat betapa besar jarak antara bisnis kecil-menengah dengan teknologi AI yang
            sebenarnya bisa membantu mereka tumbuh — bukan karena teknologinya tidak ada, tapi karena terlalu mahal dan
            rumit untuk dipasang sendiri.
          </Text>
          <Text style={styles.body}>
            BotNesia dibangun sebagai jawaban atas masalah itu: AI Workforce yang siap pakai, terjangkau, dan tetap
            mengutamakan kendali manusia di setiap keputusan penting — supaya pemilik bisnis tetap memegang kendali,
            bukan AI yang berjalan sendiri tanpa pengawasan.
          </Text>
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
  topTitle: { color: colors.text.primary, fontSize: 16, fontWeight: "800" },
  container: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },

  hero: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.lg },
  logo: { width: 72, height: 72, borderRadius: radius.md },
  eyebrow: { color: colors.brand.violet400, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  heroTitle: { color: colors.text.primary, fontSize: 20, fontWeight: "800", textAlign: "center", lineHeight: 27 },
  heroBody: { color: colors.text.muted, fontSize: 13, lineHeight: 20, textAlign: "center" },

  section: { gap: spacing.sm },
  sectionTitle: { color: colors.text.primary, fontSize: 15, fontWeight: "800" },
  body: { color: colors.text.body, fontSize: 13, lineHeight: 21 },
  founderName: { color: colors.text.primary, fontSize: 13, fontWeight: "700" },
  quote: { color: colors.brand.violet400, fontSize: 13, fontStyle: "italic", lineHeight: 20 },
});
