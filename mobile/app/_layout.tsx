import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { colors } from "../src/theme/colors";

export default function RootLayout() {
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
        <Stack.Screen name="chat" />
        <Stack.Screen name="knowledge" />
        <Stack.Screen name="computer" />
        <Stack.Screen name="notifikasi" />
      </Stack>
    </>
  );
}
