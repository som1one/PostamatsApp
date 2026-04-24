import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

export type StoredAuthSession = {
  accessToken: string;
  refreshToken: string;
};

const AUTH_SESSION_KEY = "postamats.auth.session";

function readWebStorage(): string | null {
  if (typeof localStorage === "undefined") {
    return null;
  }
  return localStorage.getItem(AUTH_SESSION_KEY);
}

function writeWebStorage(value: string) {
  if (typeof localStorage === "undefined") {
    return;
  }
  localStorage.setItem(AUTH_SESSION_KEY, value);
}

function clearWebStorage() {
  if (typeof localStorage === "undefined") {
    return;
  }
  localStorage.removeItem(AUTH_SESSION_KEY);
}

export async function readStoredAuthSession(): Promise<StoredAuthSession | null> {
  try {
    const raw =
      Platform.OS === "web"
        ? readWebStorage()
        : await SecureStore.getItemAsync(AUTH_SESSION_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as Partial<StoredAuthSession>;
    if (!parsed.accessToken || !parsed.refreshToken) {
      return null;
    }

    return {
      accessToken: parsed.accessToken,
      refreshToken: parsed.refreshToken,
    };
  } catch (error) {
    console.error("Failed to read stored auth session", error);
    return null;
  }
}

export async function writeStoredAuthSession(session: StoredAuthSession): Promise<void> {
  const raw = JSON.stringify(session);

  if (Platform.OS === "web") {
    writeWebStorage(raw);
    return;
  }

  await SecureStore.setItemAsync(AUTH_SESSION_KEY, raw);
}

export async function clearStoredAuthSession(): Promise<void> {
  if (Platform.OS === "web") {
    clearWebStorage();
    return;
  }

  await SecureStore.deleteItemAsync(AUTH_SESSION_KEY);
}
