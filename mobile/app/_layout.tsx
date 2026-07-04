import { Stack, useRouter } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { onUnauthorized } from "../src/api/client";
import { colors } from "../src/theme/colors";

export default function RootLayout() {
  const router = useRouter();

  // Mirrors the web's `window.addEventListener("botnesia:unauthorized", showAuth)`
  // (frontend/app.js:3919) -- without this, a 401 (expired/revoked token)
  // would clear the stored token but leave the user stranded on whatever
  // screen they were on instead of returning them to login.
  useEffect(() => onUnauthorized(() => router.replace("/login")), [router]);

  return (
    <>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.bg.app },
        }}
      >
        <Stack.Screen name="index" />
        <Stack.Screen name="(auth)/login" />
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="antrian" />
        <Stack.Screen name="agent-editor" options={{ presentation: "modal" }} />
        <Stack.Screen name="task-create" options={{ presentation: "modal" }} />
        <Stack.Screen name="workflow-editor" options={{ presentation: "modal" }} />
        <Stack.Screen name="chat" />
        <Stack.Screen name="knowledge" />
        <Stack.Screen name="computer" />
        <Stack.Screen name="notifikasi" />
        <Stack.Screen name="inbox" />
        <Stack.Screen name="conversation" />
        <Stack.Screen name="faq" />
        <Stack.Screen name="analytics" />
        <Stack.Screen name="handoff" />
        <Stack.Screen name="channels" />
        <Stack.Screen name="team" />
        <Stack.Screen name="security" />
        <Stack.Screen name="marketplace" />
        <Stack.Screen name="finance" />
        <Stack.Screen name="marketing" />
        <Stack.Screen name="hr" />
        <Stack.Screen name="operations" />
      </Stack>
    </>
  );
}
