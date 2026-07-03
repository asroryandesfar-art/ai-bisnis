import { MaterialCommunityIcons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import type { ColorValue } from "react-native";
import { colors } from "../../src/theme/colors";

type IconName = keyof typeof MaterialCommunityIcons.glyphMap;

function TabIcon({ name, color, size = 20 }: { name: IconName; color: ColorValue; size?: number }) {
  return <MaterialCommunityIcons name={name} size={size} color={color as string} />;
}

export default function TabsLayout() {
  return (
    <Tabs
      initialRouteName="beranda"
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.brand.violet400,
        tabBarInactiveTintColor: colors.text.faint,
        tabBarStyle: {
          backgroundColor: colors.bg.app,
          borderTopColor: colors.bg.border,
          borderTopWidth: 1,
          height: 64,
          paddingBottom: 10,
          paddingTop: 6,
        },
        tabBarLabelStyle: { fontSize: 9, fontWeight: "700", letterSpacing: 0.3 },
      }}
    >
      <Tabs.Screen
        name="beranda"
        options={{ title: "Beranda", tabBarIcon: ({ color }) => <TabIcon name="home-outline" color={color} /> }}
      />
      <Tabs.Screen
        name="agen"
        options={{ title: "Agen", tabBarIcon: ({ color }) => <TabIcon name="robot-outline" color={color} /> }}
      />
      <Tabs.Screen
        name="tugas"
        options={{ title: "Tugas", tabBarIcon: ({ color }) => <TabIcon name="lightning-bolt-outline" color={color} /> }}
      />
      <Tabs.Screen
        name="billing"
        options={{ title: "Billing", tabBarIcon: ({ color }) => <TabIcon name="credit-card-outline" color={color} /> }}
      />
      <Tabs.Screen
        name="pengaturan"
        options={{ title: "Pengaturan", tabBarIcon: ({ color }) => <TabIcon name="cog-outline" color={color} /> }}
      />
    </Tabs>
  );
}
