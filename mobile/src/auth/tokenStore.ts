import * as SecureStore from "expo-secure-store";

// Mirrors frontend/api-client.js's `tokenStore` (localStorage-backed on web)
// -- same role, same key name, just backed by the OS keychain/keystore via
// expo-secure-store since React Native has no localStorage.
const TOKEN_KEY = "bn_token";

export const tokenStore = {
  get: () => SecureStore.getItemAsync(TOKEN_KEY),
  set: (value: string) => SecureStore.setItemAsync(TOKEN_KEY, value),
  clear: () => SecureStore.deleteItemAsync(TOKEN_KEY),
};
