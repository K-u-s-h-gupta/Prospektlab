function getLocalStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function safeLocalStorageGet(key: string, fallback = ''): string {
  const storage = getLocalStorage();
  if (!storage) {
    return fallback;
  }
  try {
    return storage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function safeLocalStorageSet(key: string, value: string): boolean {
  const storage = getLocalStorage();
  if (!storage) {
    return false;
  }
  try {
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function safeLocalStorageRemove(key: string): boolean {
  const storage = getLocalStorage();
  if (!storage) {
    return false;
  }
  try {
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}
