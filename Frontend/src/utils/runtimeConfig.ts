type RuntimeConfig = {
  apiBase?: string;
  webSocketBase?: string;
  marketDataWebSocketUrl?: string;
};

type RuntimeWindow = Window & {
  __BACKEND_URL?: string;
  __WS_BASE_URL?: string;
  __MARKET_DATA_WS_URL?: string;
  __CONFIG__?: RuntimeConfig;
};

const CANONICAL_PRODUCTION_API_BASE = 'https://api.prospektlab.com';
const EXECUTE_API_HOST_RE = /(^https?:\/\/)?[^/]+\.execute-api\..*\.amazonaws\.com($|\/)/i;

function trimTrailingSlash(value: string): string {
  return String(value || '').trim().replace(/\/$/, '');
}

function readRuntimeWindow(): RuntimeWindow | undefined {
  if (typeof window === 'undefined') {
    return undefined;
  }
  return window as RuntimeWindow;
}

function readEnvValue(keys: string[]): string {
  const env = (import.meta as any)?.env || {};
  for (const key of keys) {
    const value = trimTrailingSlash(String(env[key] || ''));
    if (value) {
      return value;
    }
  }
  return '';
}

function currentHostUsesProspektLabDomain(): boolean {
  const runtimeWindow = readRuntimeWindow();
  const host = String(runtimeWindow?.location?.hostname || '').trim().toLowerCase();
  return host === 'prospektlab.com' || host === 'www.prospektlab.com' || host.endsWith('.prospektlab.com');
}

function toWebSocketProtocol(value: string): string {
  if (/^wss?:\/\//i.test(value)) {
    return value;
  }
  if (/^https?:\/\//i.test(value)) {
    return value.replace(/^http/i, (protocol) =>
      protocol.toLowerCase() === 'https' ? 'wss' : 'ws'
    );
  }
  return `wss://${value.replace(/^\/+/, '')}`;
}

function appendPath(originOrUrl: string, path: string): string {
  const normalized = trimTrailingSlash(originOrUrl);
  if (!normalized) {
    return '';
  }

  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const withoutOrigin = normalized.replace(/^wss?:\/\/[^/]+/i, '');
  if (withoutOrigin && withoutOrigin !== '/') {
    return normalized;
  }

  return `${normalized}${normalizedPath}`;
}

export function getRuntimeApiBase(fallback = ''): string {
  const envBase = readEnvValue(['VITE_BACKEND_API_URL', 'VITE_API_URL']) || trimTrailingSlash(fallback);

  if (typeof window === 'undefined') {
    return envBase;
  }

  const runtimeWindow = readRuntimeWindow();
  const runtimeBase = trimTrailingSlash(
    runtimeWindow?.__BACKEND_URL ||
    runtimeWindow?.__CONFIG__?.apiBase ||
    envBase
  );

  return runtimeBase;
}

function resolveRealtimeBase(fallback = ''): string {
  const runtimeWindow = readRuntimeWindow();
  const explicitBase = trimTrailingSlash(
    runtimeWindow?.__WS_BASE_URL ||
    runtimeWindow?.__CONFIG__?.webSocketBase ||
    readEnvValue(['VITE_BACKEND_WS_BASE_URL', 'VITE_WS_BASE_URL'])
  );

  if (explicitBase) {
    return explicitBase;
  }

  const apiBase = getRuntimeApiBase(fallback);
  if (EXECUTE_API_HOST_RE.test(apiBase) && currentHostUsesProspektLabDomain()) {
    return CANONICAL_PRODUCTION_API_BASE;
  }

  return apiBase;
}

export function getRuntimeWebSocketBase(fallback = ''): string {
  const realtimeBase = resolveRealtimeBase(fallback);
  if (!realtimeBase) {
    return '';
  }
  return trimTrailingSlash(toWebSocketProtocol(realtimeBase));
}

export function getRuntimeMarketDataWebSocketUrl(path = '/ws/market', fallback = ''): string {
  const runtimeWindow = readRuntimeWindow();
  const explicitUrl = trimTrailingSlash(
    runtimeWindow?.__MARKET_DATA_WS_URL ||
    runtimeWindow?.__CONFIG__?.marketDataWebSocketUrl ||
    readEnvValue(['VITE_MARKET_DATA_WS_URL', 'VITE_MARKET_WS_URL'])
  );

  if (explicitUrl) {
    return appendPath(toWebSocketProtocol(explicitUrl), path);
  }

  return appendPath(getRuntimeWebSocketBase(fallback), path);
}