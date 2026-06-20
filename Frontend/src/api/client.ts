import { buildTelemetryHeaders, getTelemetryRequestId, getTelemetrySessionId, isTelemetryEnabled, trackDependency, trackEvent, trackException } from '../telemetry';
import { sanitizeMojibakeValue } from '../utils/textSanitizer';

export interface ChatRequest {
  message: string;
  response_depth?: 'standard' | 'deep';
  session_id?: string;
}

export interface FinalResponse {
  session_id: string;
  status: string;
  target?: string;
  mode?: string;
  final?: any;
  memo?: string;
  memo_event?: any;
  error?: any;
}

export interface AgentEventData {
  seq: number;
  type: string;
  timestamp: string;
  payload: {
    agent?: string;
    step?: string;
    details?: string;
    status?: 'active' | 'completed' | 'planned';
    [key: string]: any;
  };
}

export type MarketHistoryPeriod = '1M' | '3M' | '6M' | 'YTD' | '1Y' | 'MAX';

export interface MarketHistoryResponse {
  symbol: string;
  name?: string;
  asset_type?: string;
  period: MarketHistoryPeriod;
  currency?: string;
  source: string;
  dates: string[];
  prices: number[];
  change_pct?: number;
  as_of?: string;
  status?: string;
  message?: string;
}

export interface WatchlistSnapshotQuote {
  symbol: string;
  name: string;
  price: number;
  price_label: string;
  change: number;
  change_label: string;
  change_pct: number;
  change_pct_label: string;
  direction: 'up' | 'down';
  source: string;
  source_url?: string;
  isin?: string;
}

export interface WatchlistSnapshotHistory {
  symbol: string;
  name: string;
  dates: string[];
  prices: number[];
  source?: string;
  as_of?: string;
}

export interface WatchlistSnapshotSummarySource {
  headline: string;
  url: string;
  source: string;
  published: string;
  category: string;
  source_tier: number;
}

export interface WatchlistSnapshotSummary {
  key: string;
  symbol: string;
  name: string;
  date: string;
  date_label: string;
  price: number;
  price_label: string;
  pct: number;
  pct_label: string;
  direction: 'up' | 'down';
  summary: string;
  source_count: number;
  sources: WatchlistSnapshotSummarySource[];
}

export interface WatchlistSnapshotNewsItem {
  id: string;
  symbol: string;
  headline: string;
  source: string;
  published: string;
  time: string;
  url: string;
  image?: string;
  source_tier: number;
  category: string;
}

export interface WatchlistSnapshotResponse {
  as_of: string;
  period: MarketHistoryPeriod;
  refresh_after_ms: number;
  quotes: WatchlistSnapshotQuote[];
  movers: WatchlistSnapshotQuote[];
  histories: Record<string, WatchlistSnapshotHistory>;
  daily_summaries: WatchlistSnapshotSummary[];
  notable_movements: WatchlistSnapshotSummary[];
  news: WatchlistSnapshotNewsItem[];
  source_health: {
    quotes: 'ok' | 'stale' | 'unavailable';
    history: 'ok' | 'stale' | 'unavailable';
    news: 'ok' | 'stale' | 'unavailable';
    official: 'ok' | 'stale' | 'unavailable';
  };
}

export interface ScreenerSearchItem {
  symbol: string;
  cin?: string | null;
  isin?: string | null;
  name: string;
  sector?: string;
  confidence?: number | null;
  source?: string;
}

export interface ScreenerSearchResponse {
  query: string;
  items: ScreenerSearchItem[];
  as_of: string;
}

export interface ScreenerQueryResponse {
  as_of: string;
  query: string;
  parsed_filter: Record<string, any>;
  universe_size: number;
  match_count: number;
  matches: Array<Record<string, any>>;
}

export interface PositionInput {
  symbol: string;
  exchange?: string;
  quantity: number;
  market_value: number;
  cost_basis: number;
  name: string;
  isin?: string;
  amfi?: string;
  kind?: string;
  sector?: string;
  industry?: string;
  avg_cost: number;
  last_price: number;
  as_of?: string;
  active?: boolean;
}

export interface AuthUser {
  email: string;
  name: string;
  mobile?: string;
  require_mobile?: boolean;
  email_verified?: boolean;
  plan?: 'free' | 'pro' | string;
}

const AUTH_TOKEN_KEY = 'prospektlab_auth_token';
const AUTH_TOKEN_SESSION_KEY = 'prospektlab_auth_token_session';
const GUEST_ID_KEY = 'prospektlab_guest_id';

// ── Runtime Backend URL Support (for Amplify + separate ECS backend) ─────
function getApiBase(): string {
  if (typeof window !== 'undefined') {
    const w = window as any;
    if (w.__BACKEND_URL) return String(w.__BACKEND_URL).replace(/\/$/, '');
    if (w.__CONFIG__?.apiBase) return String(w.__CONFIG__.apiBase).replace(/\/$/, '');
  }
  // Support Vite env at build time
  const envBase = (import.meta as any)?.env?.VITE_BACKEND_API_URL || '';
  return envBase ? String(envBase).replace(/\/$/, '') : '';
}

function apiUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  const base = getApiBase();
  if (!base) return path;
  const p = path.startsWith('/') ? path : `/${path}`;
  return `${base}${p}`;
}

function isCrossOriginApi(): boolean {
  if (typeof window === 'undefined') return false;
  const base = getApiBase();
  if (!base) return false;
  try {
    return new URL(base, window.location.origin).origin !== window.location.origin;
  } catch (_) {
    return false;
  }
}

function requestCredentials(): RequestCredentials {
  // If we have a bearer token, we can avoid sending cookies on cross-origin calls.
  // If we do not have a token, include cookies so same-site cookie sessions still work
  // on localhost/dev ports and other cookie-based auth setups.
  return getAuthToken() ? (isCrossOriginApi() ? 'omit' : 'include') : 'include';
}

function resolveRequestCredentials(options?: RequestInit): RequestCredentials {
  return options?.credentials ?? requestCredentials();
}

const AUTH_REQUEST_TIMEOUT_MS = 15000;
const MIRROR_STATUS_TIMEOUT_MS = 8000;
const CHAT_START_TIMEOUT_MS = 90000;
// Uploads run server-side LLM/casparser extraction. Keep the client ceiling a bit
// above the backend parse timeouts (90s doc / 60s screenshot) so the server's
// clean 504 wins, while still guaranteeing the UI never hangs forever.
const DOCUMENT_UPLOAD_TIMEOUT_MS = 120000;
const SCREENSHOT_UPLOAD_TIMEOUT_MS = 90000;

function summarizeTelemetryPath(url: string): string {
  try {
    const resolved = new URL(url, typeof window !== 'undefined' ? window.location.origin : 'http://localhost');
    return resolved.pathname;
  } catch (_) {
    return url;
  }
}

function telemetryMethod(options?: RequestInit): string {
  return (options?.method || 'GET').toUpperCase();
}

function recordDependency(
  url: string,
  options: RequestInit | undefined,
  startMs: number,
  res?: Response,
  requestId?: string,
  error?: unknown
) {
  if (!isTelemetryEnabled()) return;

  const elapsed = typeof performance !== 'undefined' ? performance.now() - startMs : 0;
  const method = telemetryMethod(options);
  const path = summarizeTelemetryPath(url);
  const statusCode = res?.status;
  const success = res ? res.ok : false;

  trackDependency({
    name: `${method} ${path}`,
    url,
    method,
    durationMs: elapsed,
    success,
    statusCode,
    requestId,
    properties: {
      source: 'frontend',
      path,
      session_id: getTelemetrySessionId(),
      error_type: error instanceof Error ? error.name : undefined,
    },
  });

  if (error) {
    const exception = error instanceof Error ? error : new Error(String(error));
    if (exception.name !== 'AbortError') {
      trackException(exception, {
        source: 'frontend',
        path,
        method,
        request_id: requestId || '',
      });
    }
  }
}

async function fetchWithTimeout(url: string, options: RequestInit, timeoutMs: number, timeoutMessage: string): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  const headers = buildTelemetryHeaders(options.headers);
  const requestId = getTelemetryRequestId(headers) || undefined;
  const startMs = typeof performance !== 'undefined' ? performance.now() : Date.now();
  try {
    return await fetch(url, {
      ...options,
      headers: withAuthHeaders(headers),
      credentials: resolveRequestCredentials(options),
      signal: controller.signal,
    }).then((res) => {
      recordDependency(url, options, startMs, res, requestId);
      if (res.status === 401) {
        handleAuthFailure();
      }
      return res;
    });
  } catch (err: any) {
    recordDependency(url, options, startMs, undefined, requestId, err);
    if (err?.name === 'AbortError') {
      throw new Error(timeoutMessage);
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

// ── Auth state (in-memory only; httpOnly cookie is the source of truth) ──
let _cachedUser: AuthUser | null = null;
let _cachedUserPromise: Promise<AuthUser | null> | null = null;
let _authToken: string | null = null;

function getStoredAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  return (
    localStorage.getItem(AUTH_TOKEN_KEY) ||
    sessionStorage.getItem(AUTH_TOKEN_SESSION_KEY) ||
    null
  );
}

function getGuestId(): string {
  if (typeof window === 'undefined') return '';
  let gid = (localStorage.getItem(GUEST_ID_KEY) || '').trim();
  if (!/^g_[0-9a-f]{8,40}$/.test(gid)) {
    gid = `g_${Math.random().toString(16).slice(2)}${Date.now().toString(16)}`;
    localStorage.setItem(GUEST_ID_KEY, gid);
  }
  return gid;
}

function getAuthToken(): string | null {
  if (_authToken) return _authToken;
  _authToken = getStoredAuthToken();
  return _authToken;
}

export function getEventSourceAuthToken(): string | null {
  return getStoredAuthToken();
}

function setAuthToken(token: string | null, remember: boolean = true): void {
  _authToken = token;
  if (typeof window === 'undefined') return;
  if (!token) {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    sessionStorage.removeItem(AUTH_TOKEN_SESSION_KEY);
    return;
  }
  if (remember) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
    sessionStorage.removeItem(AUTH_TOKEN_SESSION_KEY);
  } else {
    sessionStorage.setItem(AUTH_TOKEN_SESSION_KEY, token);
    localStorage.removeItem(AUTH_TOKEN_KEY);
  }
}

function withAuthHeaders(headers?: HeadersInit): HeadersInit {
  const token = getAuthToken();
  const merged = new Headers(headers || {});
  if (token) {
    merged.set('Authorization', `Bearer ${token}`);
  } else {
    const gid = getGuestId();
    if (gid) merged.set('X-Prospekt-Guest-Id', gid);
  }
  return merged;
}

export function getCachedUser(): AuthUser | null {
  return _cachedUser;
}

export function setCachedUser(user: AuthUser | null) {
  _cachedUser = user;
}

export async function getAuthMe(): Promise<AuthUser | null> {
  if (_cachedUserPromise) {
    return _cachedUserPromise;
  }
  _cachedUserPromise = (async () => {
    try {
      const res = await fetchApi(apiUrl('/auth/me'), {
        credentials: requestCredentials(),
      });
      if (res.ok) {
        const data = await res.json();
        const user: AuthUser = {
          email: data.email,
          name: data.name || 'Researcher',
          mobile: data.mobile,
          require_mobile: data.require_mobile,
          email_verified: data.email_verified,
          plan: data.plan || 'free',
        };
        _cachedUser = user;
        return user;
      }
      return null;
    } catch (err) {
      return null;
    } finally {
      _cachedUserPromise = null;
    }
  })();
  return _cachedUserPromise;
}

function handleAuthFailure() {
  const token = getAuthToken();
  if (!token) return; // Don't redirect if user was never logged in (public pages)
  _cachedUser = null;
  setAuthToken(null);
  if (typeof window !== 'undefined') {
    window.location.hash = '#/dashboard/overview';
  }
}

async function fetchApi(url: string, options?: RequestInit): Promise<Response> {
  const headers = buildTelemetryHeaders(options?.headers);
  const requestId = getTelemetryRequestId(headers) || undefined;
  const startMs = typeof performance !== 'undefined' ? performance.now() : Date.now();
  const res = await fetch(url, {
    ...(options || {}),
    headers: withAuthHeaders(headers),
    credentials: resolveRequestCredentials(options),
  });
  recordDependency(url, options, startMs, res, requestId);
  if (res.status === 401) {
    handleAuthFailure();
  }
  return res;
}

// ── Auth Endpoints ──────────────────────────────────────────────────────

async function parseJsonSanitized<T = any>(res: Response): Promise<T> {
  const payload = await res.json();
  return sanitizeMojibakeValue(payload) as T;
}

export async function apiLogin(email: string, password: string, remember: boolean = true): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl('/auth/login'),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password, remember }),
    },
    AUTH_REQUEST_TIMEOUT_MS,
    'Login is taking too long. Please try again in a moment.'
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Login failed: ${res.statusText}`);
  }

  const data = await res.json();
  if (data.token) {
    setAuthToken(data.token, remember);
  }
  if (data.user) {
    _cachedUser = {
      email: data.user?.email || email,
      name: data.user?.name || 'Researcher',
      email_verified: data.user?.email_verified,
    };
  }
  return data;
}

export async function apiSignup(name: string, email: string, password: string, mobile: string, verificationCode?: string): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl('/auth/signup'),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name,
        email,
        password,
        mobile,
        verification_code: verificationCode || undefined,
      }),
    },
    AUTH_REQUEST_TIMEOUT_MS,
    'Signup is taking too long. Please try again in a moment.'
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Signup failed: ${res.statusText}`);
  }

  const data = await res.json();
  if (data.token) {
    setAuthToken(data.token, true);
  }
  if (data.user) {
    _cachedUser = {
      email: data.user?.email || email,
      name: data.user?.name || name,
      email_verified: data.user?.email_verified,
    };
  }
  return data;
}

export async function apiSendVerification(email: string): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl('/auth/send-verification'),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email }),
    },
    AUTH_REQUEST_TIMEOUT_MS,
    'Verification email is taking too long. Please try again in a moment.'
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to send verification: ${res.statusText}`);
  }

  return res.json();
}

export async function apiForgotPassword(email: string): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl('/auth/forgot-password'),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email }),
    },
    AUTH_REQUEST_TIMEOUT_MS,
    'Password reset email is taking too long. Please try again in a moment.'
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to send reset code: ${res.statusText}`);
  }

  return res.json();
}

export async function apiResetPassword(email: string, code: string, newPassword: string): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl('/auth/reset-password'),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, code, new_password: newPassword }),
    },
    AUTH_REQUEST_TIMEOUT_MS,
    'Password reset is taking too long. Please try again in a moment.'
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to reset password: ${res.statusText}`);
  }

  return res.json();
}

export async function apiGoogleAuth(credential: string): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl('/auth/google'),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ credential }),
    },
    AUTH_REQUEST_TIMEOUT_MS,
    'Google sign-in is taking too long. Please try again in a moment.'
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Google Auth failed: ${res.statusText}`);
  }

  const data = await res.json();
  if (data.token) {
    setAuthToken(data.token, true);
  }
  if (data.email) {
    _cachedUser = {
      email: data.email,
      name: data.name || data.full_name || 'Researcher',
      mobile: data.mobile,
      require_mobile: data.require_mobile,
    };
  }
  return data;
}

export async function apiUpdateMobile(mobile: string): Promise<any> {
  const res = await fetchApi(apiUrl('/auth/google/update-mobile'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({ mobile }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to update mobile: ${res.statusText}`);
  }

  if (_cachedUser) {
    _cachedUser = { ..._cachedUser, mobile, require_mobile: false };
  }

  return res.json();
}

export async function apiLogout(): Promise<void> {
  await fetchApi(apiUrl('/auth/logout'), {
    method: 'POST',
  }).catch(() => {});
  _cachedUser = null;
  setAuthToken(null);
}

// ── Portfolio Endpoints ──────────────────────────────────────────────────

export async function getPortfolioMirror(): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl('/portfolio/mirror'),
    {
      credentials: 'include',
    },
    MIRROR_STATUS_TIMEOUT_MS,
    'Portfolio status check timed out.'
  );
  if (res.status === 401) {
    handleAuthFailure();
  }
  if (!res.ok) {
    throw new Error(`Failed to load portfolio mirror: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function replacePortfolioMirror(positions: PositionInput[]): Promise<any> {
  trackEvent('portfolio_mirror_replace_requested', {
    source: 'frontend',
    position_count: positions.length,
  });
  const res = await fetchApi(apiUrl('/portfolio/mirror'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({ positions }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    trackEvent('portfolio_mirror_replace_failed', {
      source: 'frontend',
      position_count: positions.length,
      status_code: res.status,
    });
    throw new Error(errorData.detail?.message || errorData.detail || `Failed to replace portfolio mirror: ${res.statusText}`);
  }
  const result = await parseJsonSanitized(res);
  trackEvent('portfolio_mirror_replace_completed', {
    source: 'frontend',
    position_count: positions.length,
  });
  return result;
}

export interface ManualPositionInput {
  symbol: string;
  quantity: number;
  avg_cost: number;
  date_purchased?: string;
}

export async function syncManualPortfolio(positions: ManualPositionInput[]): Promise<any> {
  trackEvent('portfolio_manual_sync_requested', {
    source: 'frontend',
    position_count: positions.length,
  });
  const res = await fetchApi(apiUrl('/portfolio/mirror/sync-manual'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({ positions }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    trackEvent('portfolio_manual_sync_failed', {
      source: 'frontend',
      position_count: positions.length,
      status_code: res.status,
    });
    throw new Error(errorData.detail?.message || errorData.detail || `Failed to sync manual portfolio: ${res.statusText}`);
  }
  const result = await parseJsonSanitized(res);
  trackEvent('portfolio_manual_sync_completed', {
    source: 'frontend',
    position_count: positions.length,
  });
  return result;
}

export async function uploadPortfolioDocument(file: File, password?: string): Promise<any> {
  trackEvent('portfolio_upload_requested', {
    source: 'frontend',
    upload_type: 'document',
    file_name: file.name,
    file_size_bytes: file.size,
    has_password: Boolean(password),
  });
  const formData = new FormData();
  formData.append('file', file);
  if (password) {
    formData.append('password', password);
  }

  const res = await fetchWithTimeout(
    apiUrl('/api/portfolio/upload-cas'),
    {
      method: 'POST',
      credentials: 'include',
      body: formData,
    },
    DOCUMENT_UPLOAD_TIMEOUT_MS,
    'Document upload timed out. Try a broker CSV/XLSX export or a clear screenshot.',
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    trackEvent('portfolio_upload_failed', {
      source: 'frontend',
      upload_type: 'document',
      file_name: file.name,
      status_code: res.status,
    });
    throw new Error(errorData.detail?.message || errorData.detail || `Failed to parse document: ${res.statusText}`);
  }

  const result = await parseJsonSanitized(res);
  trackEvent('portfolio_upload_completed', {
    source: 'frontend',
    upload_type: 'document',
    file_name: file.name,
    result_code: result?.code || result?.status || 'unknown',
  });
  return result;
}

export async function uploadPortfolioScreenshot(file: File): Promise<any> {
  trackEvent('portfolio_upload_requested', {
    source: 'frontend',
    upload_type: 'screenshot',
    file_name: file.name,
    file_size_bytes: file.size,
  });
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetchWithTimeout(
    apiUrl('/api/portfolio/upload-screenshot'),
    {
      method: 'POST',
      credentials: 'include',
      body: formData,
    },
    SCREENSHOT_UPLOAD_TIMEOUT_MS,
    'Screenshot upload timed out. Try a smaller, clearer image or a broker CSV/XLSX export.',
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    trackEvent('portfolio_upload_failed', {
      source: 'frontend',
      upload_type: 'screenshot',
      file_name: file.name,
      status_code: res.status,
    });
    throw new Error(errorData.detail?.message || errorData.detail || `Failed to parse screenshot: ${res.statusText}`);
  }

  const result = await parseJsonSanitized(res);
  trackEvent('portfolio_upload_completed', {
    source: 'frontend',
    upload_type: 'screenshot',
    file_name: file.name,
    result_code: result?.code || result?.status || 'unknown',
  });
  return result;
}

export async function confirmExtraction(
  reviewId: string,
  positions?: any[],
  sourceType?: string,
  reviewToken?: string | null,
): Promise<any> {
  trackEvent('portfolio_extraction_confirm_requested', {
    source: 'frontend',
    review_id: reviewId,
    source_type: sourceType || 'unknown',
    position_count: positions?.length || 0,
  });
  const res = await fetchApi(apiUrl('/api/portfolio/confirm-extraction'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({
      review_id: reviewId,
      positions: positions,
      source_type: sourceType,
      review_token: reviewToken || undefined,
    }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    trackEvent('portfolio_extraction_confirm_failed', {
      source: 'frontend',
      review_id: reviewId,
      status_code: res.status,
    });
    throw new Error(errorData.detail?.message || errorData.detail || `Failed to confirm extraction: ${res.statusText}`);
  }

  const result = await parseJsonSanitized(res);
  trackEvent('portfolio_extraction_confirm_completed', {
    source: 'frontend',
    review_id: reviewId,
    source_type: sourceType || 'unknown',
  });
  return result;
}

export async function cancelExtraction(): Promise<any> {
  trackEvent('portfolio_extraction_cancel_requested', {
    source: 'frontend',
  });
  const res = await fetchApi(apiUrl('/api/portfolio/cancel-extraction'), {
    method: 'POST',
    credentials: 'include',
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    trackEvent('portfolio_extraction_cancel_failed', {
      source: 'frontend',
      status_code: res.status,
    });
    throw new Error(errorData.detail || `Failed to cancel extraction: ${res.statusText}`);
  }

  const result = await parseJsonSanitized(res);
  trackEvent('portfolio_extraction_cancel_completed', {
    source: 'frontend',
  });
  return result;
}

export async function getPortfolioAnalytics(benchmark: string = 'NIFTY50', period: string = '1y'): Promise<any> {
  const res = await fetchApi(apiUrl(`/portfolio/analytics?benchmark=${encodeURIComponent(benchmark)}&period=${encodeURIComponent(period)}`), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio analytics: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function deletePortfolioMirror(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/mirror'), {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to clear portfolio: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getPortfolioNews(limit: number = 12): Promise<any> {
  const res = await fetchApi(apiUrl(`/portfolio/news?limit=${limit}`), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio news: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getPortfolioSectors(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/sectors'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio sectors: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

// ── Governance & Network intelligence ──────────────────────────────────────

export interface GovernanceFlag {
  code: string;
  severity: 'info' | 'watch' | 'high';
  detail: string;
  evidence: Record<string, any>;
}

export interface GovernanceResult {
  cin: string;
  score: number;
  band: 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH';
  subscores: Record<string, number>;
  flags: GovernanceFlag[];
  coverage: Record<string, boolean>;
  computed_at: string;
}

export interface PortfolioGovernance {
  portfolio_governance_score: number;
  portfolio_governance_band: 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH';
  flagged_holdings: Array<{
    symbol: string; name: string; cin: string; score: number;
    band: string; weight_pct: number;
    top_flags: Array<{ code: string; severity: string; detail: string }>;
  }>;
  band_distribution: Record<string, number>;
  coverage: { holdings_total: number; holdings_scored: number; coverage_ratio: number };
  unresolved: Array<{ symbol: string; name: string; reason: string }>;
  store_unavailable?: boolean;
}

export async function getPortfolioGovernance(): Promise<PortfolioGovernance> {
  const res = await fetchApi(apiUrl('/portfolio/governance'), { credentials: 'include' });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio governance: ${res.statusText}`);
  }
  return res.json();
}

export async function getCompanyGovernance(cin: string): Promise<GovernanceResult> {
  const res = await fetchApi(apiUrl(`/company/${encodeURIComponent(cin)}/governance`), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch company governance: ${res.statusText}`);
  }
  return res.json();
}

export interface CompanyNetwork {
  seed: { id: string; name: string };
  nodes: Array<{ id: string; label: string; name: string; degree: number; is_seed?: boolean }>;
  links: Array<{ source: string; target: string; label: string; designation: string }>;
  connected_companies: Array<{ id: string; name: string; shared_directors: number }>;
  summary: { directors: number; connected_companies: number };
}

export async function getCompanyNetwork(cin: string): Promise<CompanyNetwork> {
  const res = await fetchApi(apiUrl(`/company/${encodeURIComponent(cin)}/network`), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch company network: ${res.statusText}`);
  }
  return res.json();
}

export interface CompanyProvenance {
  cin: string;
  company_name: string;
  sections: Array<{
    predicate: string;
    label: string;
    facts: Array<{
      value: any;
      as_of: string | null;
      confidence: number;
      evidence: { source_table?: string; source_url?: string; detail?: string };
    }>;
  }>;
  summary: { total_facts: number; cited_facts: number; citation_ratio: number; predicates: number };
}

export async function getCompanyProvenance(cin: string): Promise<CompanyProvenance> {
  const res = await fetchApi(apiUrl(`/company/${encodeURIComponent(cin)}/provenance`), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch provenance: ${res.statusText}`);
  }
  return res.json();
}

export interface CompanyHealth {
  cin: string;
  completeness_score: number;
  grade: 'evidence_grade' | 'partial' | 'thin';
  present: string[];
  missing: string[];
  has_enforcement: boolean;
  edge_labels: Record<string, number>;
}

export async function getCompanyHealth(cin: string): Promise<CompanyHealth> {
  const res = await fetchApi(apiUrl(`/company/${encodeURIComponent(cin)}/health`), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch company health: ${res.statusText}`);
  }
  return res.json();
}

export interface FilingTriageResult {
  count: number;
  alerts: number;
  results: Array<{
    subject?: string; headline?: string; title?: string; category?: string;
    materiality: { band: 'HIGH' | 'MEDIUM' | 'ROUTINE'; category: string; score: number; reasons: string[] };
    alert: boolean;
  }>;
}

export async function triageFilings(filings: any[]): Promise<FilingTriageResult> {
  const res = await fetchApi(apiUrl('/filings/triage'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filings }),
  });
  if (!res.ok) {
    throw new Error(`Failed to triage filings: ${res.statusText}`);
  }
  return res.json();
}

export async function getHoldingDetail(symbol: string): Promise<any> {
  const res = await fetchApi(apiUrl(`/portfolio/holding/${encodeURIComponent(symbol)}`), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch holding detail: ${res.statusText}`);
  }
  return res.json();
}

export async function getCorporateActions(days: number = 30): Promise<any> {
  const res = await fetchApi(apiUrl(`/portfolio/corporate-actions?days=${days}`), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch corporate actions: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioAlerts(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/alerts'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio alerts: ${res.statusText}`);
  }
  return res.json();
}

export async function getTaxSummary(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/tax-summary'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch tax summary: ${res.statusText}`);
  }
  return res.json();
}

export async function getDividends(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/dividends'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch dividends: ${res.statusText}`);
  }
  return res.json();
}

export async function postStressTest(scenario: string, customShocks?: any): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/stress-test'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({ scenario, custom_shocks: customShocks }),
  });
  if (!res.ok) {
    throw new Error(`Failed to run stress test: ${res.statusText}`);
  }
  return res.json();
}

export async function getMfAnalytics(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/mf-analytics'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch MF analytics: ${res.statusText}`);
  }
  return res.json();
}

export async function getTodayQueue(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/today'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch action queue: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioBrief(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/brief'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio brief: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioCommentary(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/commentary'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio commentary: ${res.statusText}`);
  }
  return res.json();
}

// ── Research and Chat SSE Endpoints ────────────────────────────────────────

export async function startResearch(message: string, mode: 'standard' | 'deep', portfolioContext?: string): Promise<any> {
  const rewrittenMessage = portfolioContext ? `${portfolioContext} ${message}` : message;
  // Keep deep mode explicit, but route standard chat through the lightweight backend mode.
  const apiMode = mode === 'standard' ? 'chat' : 'deep';
  const payload: Record<string, any> = {
    // Keep a clean user query for portfolio-scope routing and target detection.
    target: message,
    // Keep enriched context for synthesis quality.
    message: rewrittenMessage,
    mode: apiMode,
  };
  trackEvent('research_start_requested', {
    source: 'frontend',
    mode,
    backend_mode: apiMode,
    has_portfolio_context: Boolean(portfolioContext),
    message_length: message.length,
  });

  const res = await fetchWithTimeout(
    apiUrl('/chat/research'),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify(payload),
    },
    CHAT_START_TIMEOUT_MS,
    'Starting the analysis is taking too long. Please try again.'
  );

  if (!res.ok) {
    if (res.status === 401) {
      handleAuthFailure();
    }
    const errorData = await res.json().catch(() => ({}));
    trackEvent('research_start_failed', {
      source: 'frontend',
      mode,
      status_code: res.status,
    });
    const err = new Error(errorData.detail?.message || errorData.detail || `Failed to start research: ${res.statusText}`);
    (err as any).detail = errorData.detail;
    throw err;
  }

  const result = await res.json();
  trackEvent('research_start_accepted', {
    source: 'frontend',
    mode,
    session_id: result?.session_id || '',
  });
  return result;
}

export async function stopSession(sessionId: string): Promise<any> {
  trackEvent('research_stop_requested', {
    source: 'frontend',
    session_id: sessionId,
  });
  const res = await fetchApi(apiUrl(`/sessions/${encodeURIComponent(sessionId)}/stop`), {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    trackEvent('research_stop_failed', {
      source: 'frontend',
      session_id: sessionId,
      status_code: res.status,
    });
    throw new Error(`Failed to stop research session: ${res.statusText}`);
  }
  const result = await res.json();
  trackEvent('research_stop_completed', {
    source: 'frontend',
    session_id: sessionId,
  });
  return result;
}

export async function getSessionResult(sessionId: string): Promise<FinalResponse> {
  trackEvent('research_result_requested', {
    source: 'frontend',
    session_id: sessionId,
  });
  const res = await fetchApi(apiUrl(`/sessions/${encodeURIComponent(sessionId)}/result`), {
    credentials: 'include',
  });
  if (!res.ok) {
    trackEvent('research_result_failed', {
      source: 'frontend',
      session_id: sessionId,
      status_code: res.status,
    });
    throw new Error(`Failed to fetch session result: ${res.statusText}`);
  }
  const result = await res.json();
  trackEvent('research_result_received', {
    source: 'frontend',
    session_id: sessionId,
    status: result?.status || 'unknown',
  });
  return result;
}

export function streamSession(
  sessionId: string,
  onEvent: (event: AgentEventData) => void,
  onFinal: (final: any) => void,
  onError: (error: any) => void
): () => void {
  const MAX_RECONNECT_ATTEMPTS = 12;
  // Deep research runs can exceed 90s; keep stream alive long enough for completion.
  const MAX_STREAM_DURATION_MS = 12 * 60_000;
  const streamStartedAt = Date.now();
  let lastEventId: number | null = null;
  let sseAbort = new AbortController();
  let sseReconnectTimer: any = null;
  let sseActive = true;
  let onFinalCalled = false;
  let onErrorCalled = false;
  let reconnectAttempts = 0;

  const closeStream = () => {
    if (sseActive) {
      sseActive = false;
      clearTimeout(sseReconnectTimer);
      sseAbort.abort();
    }
  };

  function scheduleReconnect(delayMs = 1500) {
    if (!sseActive || onFinalCalled || onErrorCalled) return;
    reconnectAttempts += 1;
    if (reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
      closeStream();
      void finalizeFromResult();
      return;
    }
    clearTimeout(sseReconnectTimer);
    sseReconnectTimer = setTimeout(connectSSE, delayMs);
  }

  async function finalizeFromResult() {
    if (onFinalCalled || onErrorCalled) return;
    try {
      const result = await getSessionResult(sessionId);
      const status = String(result.status || '').toLowerCase();
      const hasDeliverableMemo = Boolean(
        result.memo ||
        result.final?.memo ||
        result.final?.memo_preview ||
        result.memo_event?.preview
      );
      const errorPayload = result.error;
      const errorMessage =
        typeof errorPayload === 'string'
          ? errorPayload
          : errorPayload?.message || errorPayload?.payload?.message || null;

      if (errorMessage || result.status === 'error') {
        if (!onErrorCalled) {
          onErrorCalled = true;
          onError(new Error(errorMessage || 'Research failed'));
        }
        return;
      }

      if (!hasDeliverableMemo && status !== 'done') {
        if (!sseActive) {
          if (!onErrorCalled) {
            onErrorCalled = true;
            onError(new Error('Research timed out before a final answer was available.'));
          }
          return;
        }
        trackEvent('research_stream_waiting_for_result', {
          source: 'frontend',
          session_id: sessionId,
          status: status || 'unknown',
        });
        scheduleReconnect();
        return;
      }

      if (!onFinalCalled) {
        onFinalCalled = true;
        onFinal(result.final || result);
      }
    } catch (err) {
      if (!onErrorCalled) {
        onErrorCalled = true;
        onError(err instanceof Error ? err : new Error('Failed to retrieve session result'));
      }
    }
  }

  function handleTerminalEvent(evType: string, evData: string) {
    if (evType === 'final') {
      try {
        const parsed = JSON.parse(evData);
        closeStream();
        trackEvent('research_stream_final', {
          source: 'frontend',
          session_id: sessionId,
        });
        if (!onFinalCalled) {
          onFinalCalled = true;
          onFinal(parsed);
        }
      } catch (err) {
        console.error('Failed to parse final event data', err);
        void finalizeFromResult();
      }
      return;
    }

    if (evType === 'error') {
      try {
        const parsed = JSON.parse(evData);
        closeStream();
        trackEvent('research_stream_error', {
          source: 'frontend',
          session_id: sessionId,
          phase: 'stream_error_event',
          message: parsed.message || 'unknown',
        });
        if (!onErrorCalled) {
          onErrorCalled = true;
          onError(new Error(parsed.message || 'Stream processing error'));
        }
      } catch (err) {
        closeStream();
        trackEvent('research_stream_error', {
          source: 'frontend',
          session_id: sessionId,
          phase: 'stream_error_event',
        });
        if (!onErrorCalled) {
          onErrorCalled = true;
          onError(new Error('Stream encountered an error'));
        }
      }
      return;
    }

    if (evType === 'done' || evType === 'deep_complete') {
      closeStream();
      trackEvent('research_stream_completed', {
        source: 'frontend',
        session_id: sessionId,
        phase: evType,
      });
      void finalizeFromResult();
    }
  }

  async function connectSSE() {
    if (!sseActive) return;
    if (Date.now() - streamStartedAt > MAX_STREAM_DURATION_MS) {
      closeStream();
      void finalizeFromResult();
      return;
    }
    sseAbort = new AbortController();
    
    // Reconnect before API Gateway's 30s timeout fires
    clearTimeout(sseReconnectTimer);
    sseReconnectTimer = setTimeout(() => {
      if (sseActive) {
        console.info("SSE: proactive reconnect (25s window)");
        sseAbort.abort();
        connectSSE();
      }
    }, 25000);

    const headers: Record<string, string> = { 
      "Accept": "text/event-stream", 
      "Cache-Control": "no-cache" 
    };
    const telemetryHeaders = buildTelemetryHeaders(headers);
    const requestId = getTelemetryRequestId(telemetryHeaders) || undefined;
    const token = getAuthToken();
    if (token) {
      (telemetryHeaders as Headers).set?.("Authorization", `Bearer ${token}`);
    }
    if (lastEventId !== null) {
      (telemetryHeaders as Headers).set?.("Last-Event-ID", String(lastEventId));
    }

    const path = `/sessions/${encodeURIComponent(sessionId)}/stream`;
    let url = apiUrl(path);
    if (lastEventId !== null) {
      url += (url.includes("?") ? "&" : "?") + "after=" + encodeURIComponent(lastEventId);
    }
    const startMs = typeof performance !== 'undefined' ? performance.now() : Date.now();

    let resp: Response;
    try {
      resp = await fetch(url, {
        headers: withAuthHeaders(telemetryHeaders),
        signal: sseAbort.signal,
        credentials: requestCredentials(),
      });
    } catch (err: any) {
      if (!sseActive) return;
      if (err && err.name === "AbortError") return; // proactive reconnect
      trackDependency({
        name: `GET ${path}`,
        url,
        method: 'GET',
        durationMs: (typeof performance !== 'undefined' ? performance.now() : Date.now()) - startMs,
        success: false,
        requestId,
        properties: {
          source: 'frontend',
          session_id: sessionId,
          phase: 'stream_connect',
          error_type: err?.name || 'Error',
        },
      });
      trackEvent('research_stream_error', {
        source: 'frontend',
        session_id: sessionId,
        phase: 'connect',
      });
      console.warn("SSE fetch error, retrying in 2s:", err);
      clearTimeout(sseReconnectTimer);
      sseReconnectTimer = setTimeout(connectSSE, 2000);
      return;
    }

    trackDependency({
      name: `GET ${path}`,
      url,
      method: 'GET',
      durationMs: (typeof performance !== 'undefined' ? performance.now() : Date.now()) - startMs,
      success: resp.ok,
      statusCode: resp.status,
      requestId,
      properties: {
        source: 'frontend',
        session_id: sessionId,
        phase: 'stream_connect',
      },
    });

    if (!resp.ok) {
      if (!sseActive) return;
      if (resp.status === 404) {
        closeStream();
        void finalizeFromResult();
        return;
      }
      trackEvent('research_stream_error', {
        source: 'frontend',
        session_id: sessionId,
        phase: 'http_error',
        status_code: resp.status,
      });
      console.warn("SSE HTTP error status:", resp.status, "— retrying in 3s");
      clearTimeout(sseReconnectTimer);
      sseReconnectTimer = setTimeout(connectSSE, 3000);
      return;
    }

    trackEvent('research_stream_connected', {
      source: 'frontend',
      session_id: sessionId,
      resumed: String(lastEventId !== null),
    });
    reconnectAttempts = 0;

    const reader = resp.body?.getReader();
    if (!reader) {
      console.error("SSE response body is not readable");
      if (!onErrorCalled) {
        onErrorCalled = true;
        onError(new Error("Response body is not readable"));
      }
      return;
    }

    const decoder = new TextDecoder();
    let buf = "";
    let streamEnded = false;

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) {
          streamEnded = true;
          break;
        }
        buf += decoder.decode(value, { stream: true });
        
        let boundary;
        while ((boundary = buf.indexOf("\n\n")) !== -1) {
          const block = buf.slice(0, boundary);
          buf = buf.slice(boundary + 2);
          if (!block.trim() || block.startsWith(":")) continue; // keepalive comment
          
          let evType = "message";
          let evData = "";
          let evId: string | null = null;
          
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) {
              evType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              evData = line.slice(5).trim();
            } else if (line.startsWith("id:")) {
              evId = line.slice(3).trim();
            }
          }
          
          if (evId !== null) {
            const parsedId = parseInt(evId, 10);
            if (!isNaN(parsedId)) {
              lastEventId = parsedId;
            }
          }

          if (evType === 'final' || evType === 'error' || evType === 'done' || evType === 'deep_complete') {
            handleTerminalEvent(evType, evData);
            continue;
          }

          try {
            const parsed = JSON.parse(evData);
            onEvent({
              seq: parsed.id || (evId ? parseInt(evId, 10) : 0),
              type: evType,
              timestamp: parsed.timestamp || '',
              payload: parsed,
            });
          } catch (err) {
            console.error(`Failed to parse ${evType} event data`, err);
          }
        }
      }
      if (sseActive && !onFinalCalled && !onErrorCalled) {
        scheduleReconnect(1000);
      }
    } catch (err: any) {
      if (!sseActive) return;
      if (err && err.name === "AbortError") return; // proactive reconnect in progress
      console.warn("SSE read error, retrying in 2s:", err);
      clearTimeout(sseReconnectTimer);
      sseReconnectTimer = setTimeout(connectSSE, 2000);
      return;
    }

    if (streamEnded && sseActive && !onFinalCalled && !onErrorCalled) {
      void finalizeFromResult();
    }
  }

  connectSSE();

  return () => {
    closeStream();
  };
}


// ── Market Data & Token Usage API Endpoints ──────────────────────────────

export async function getUserTokenUsage(): Promise<any> {
  const res = await fetchApi(apiUrl('/user/token-usage'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch user token usage: ${res.statusText}`);
  }
  return res.json();
}

export async function getUserSubscription(): Promise<any> {
  const res = await fetchApi(apiUrl('/user/subscription'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch subscription: ${res.statusText}`);
  }
  return res.json();
}

export async function createRazorpayOrder(amountPaise: number, currency = 'INR', plan = 'pro'): Promise<any> {
  const res = await fetchApi(apiUrl('/api/create-order'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ amount: amountPaise, currency, plan }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const error = new Error(err.detail || `Failed to create order: ${res.statusText}`) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json();
}

export async function verifyRazorpayPayment(
  razorpay_order_id: string,
  razorpay_payment_id: string,
  razorpay_signature: string,
): Promise<any> {
  const res = await fetchApi(apiUrl('/api/verify-payment'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ razorpay_order_id, razorpay_payment_id, razorpay_signature }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const error = new Error(err.detail || `Payment verification failed: ${res.statusText}`) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json();
}

export async function getMarketQuotes(symbols: string[]): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl(`/market/quotes?symbols=${encodeURIComponent(symbols.join(','))}`),
    { credentials: 'include' },
    12000,
    'Market quotes request timed out. Please retry.',
  );
  if (!res.ok) {
    throw new Error(`Failed to fetch market quotes: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getMarketNews(query?: string, limit: number = 10, includeImages = false): Promise<any> {
  const params = new URLSearchParams();
  if (query) params.set('query', query);
  params.set('limit', String(Math.max(1, Math.min(60, Number(limit) || 10))));
  params.set('images', includeImages ? '1' : '0');
  const qStr = params.toString();
  const res = await fetchWithTimeout(
    apiUrl(`/market/news${qStr ? `?${qStr}` : ''}`),
    { credentials: 'include' },
    12000,
    'Market news request timed out. Please retry.',
  );
  if (!res.ok) {
    throw new Error(`Failed to fetch market news: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getMarketIndices(): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl('/market/indices'),
    { credentials: 'include' },
    20000,
    'Market indices request timed out. Please retry.',
  );
  if (!res.ok) {
    throw new Error(`Failed to fetch market indices: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getMarketHistory(
  symbol: string,
  period: MarketHistoryPeriod,
  assetType?: string
): Promise<MarketHistoryResponse> {
  const params = new URLSearchParams({
    symbol,
    period,
  });
  if (assetType) params.set('asset_type', assetType);

  const res = await fetchApi(apiUrl(`/market/history?${params.toString()}`), {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch market history: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getWatchlistSnapshot(
  symbols: string[],
  period: MarketHistoryPeriod = '1M',
): Promise<WatchlistSnapshotResponse> {
  const params = new URLSearchParams({
    symbols: symbols.join(','),
    period,
  });
  const res = await fetchWithTimeout(
    apiUrl(`/watchlist/snapshot?${params.toString()}`),
    { credentials: 'include' },
    15000,
    'Watchlist snapshot timed out. Showing available live quotes.',
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch watchlist snapshot: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

// ── Flash Content Engine API ──────────────────────────────────────────────────

export async function screenerSearch(query: string, limit = 8): Promise<ScreenerSearchResponse> {
  const params = new URLSearchParams({
    q: query,
    limit: String(limit),
  });
  const res = await fetchWithTimeout(
    apiUrl(`/screener/search?${params.toString()}`),
    { credentials: 'include' },
    8000,
    'Screener search timed out. Please retry.',
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to search screener universe: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getScreenerSnapshot(identifier: string, period: MarketHistoryPeriod = '1Y'): Promise<any> {
  const params = new URLSearchParams({ period });
  const res = await fetchWithTimeout(
    apiUrl(`/screener/company/${encodeURIComponent(identifier)}/snapshot?${params.toString()}`),
    { credentials: 'include' },
    15000,
    'Screener snapshot timed out. Showing cached data if available.',
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to load screener snapshot: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getScreenerFinancials(identifier: string): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl(`/screener/company/${encodeURIComponent(identifier)}/financials`),
    { credentials: 'include' },
    18000,
    'Screener financials timed out. Try refreshing this section.',
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to load screener financials: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getScreenerTechnicals(identifier: string, period: MarketHistoryPeriod = '1Y'): Promise<any> {
  const params = new URLSearchParams({ period });
  const res = await fetchWithTimeout(
    apiUrl(`/screener/company/${encodeURIComponent(identifier)}/technicals?${params.toString()}`),
    { credentials: 'include' },
    12000,
    'Screener technicals timed out. Please retry.',
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to load screener technicals: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getScreenerEvents(identifier: string, limit = 25): Promise<any> {
  const params = new URLSearchParams({ limit: String(limit) });
  const res = await fetchWithTimeout(
    apiUrl(`/screener/company/${encodeURIComponent(identifier)}/events?${params.toString()}`),
    { credentials: 'include' },
    12000,
    'Screener events timed out. Please retry.',
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to load screener events: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function getScreenerAnalysis(identifier: string): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl(`/screener/company/${encodeURIComponent(identifier)}/analyze`),
    { credentials: 'include' },
    25000,
    'Screener analysis is still loading. Please retry in a moment.',
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to load screener analysis: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export async function runScreenerQuery(
  query: string,
  limit = 25,
  universe: string[] = [],
): Promise<ScreenerQueryResponse> {
  const res = await fetchWithTimeout(
    apiUrl('/screener/query'),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ query, limit, universe }),
    },
    15000,
    'Screener query timed out. Please try a narrower query.',
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to run screener query: ${res.statusText}`);
  }
  return parseJsonSanitized(res);
}

export interface FlashGenerationRequest {
  mode?: 'flash' | 'deep' | 'research';
  content_type: 'earnings' | 'sebi' | 'trend' | 'company' | 'manual';
  target: string;
  objective?: string;
  source_url?: string;
  source_markdown?: string;
  route_base?: string;
  include_image?: boolean;
  overwrite?: boolean;
}

export interface FlashJobStarted {
  job_id: string;
  stream: string;
  status: string;
  events: string;
  result: string;
  mode: string;
  content_type: string;
}

export interface ArticleListItem {
  slug: string;
  title: string;
  description: string;
  route_base: string;
  public_url: string;
  generated_at: string;
  image_path?: string;
  confidence_score: number;
  publish_status: 'draft' | 'published';
  publish_gate_status?: 'draft' | 'publish';
  content_type?: string;
  mode?: string;
  quality_score?: number;
  ikg_covered?: boolean;
  job_id?: string;
  editorial_review?: Record<string, any>;
  editorial_quality_score?: number;
  publish_urgency_score?: number;
}

export interface ArticleDetail extends ArticleListItem {
  html_path: string;
  json_path: string;
  sources_used: Array<{ title: string; url: string }>;
  publish_reasons: string[];
  mirrored_public_path?: string;
  article?: {
    title?: string;
    description?: string;
    hero_eyebrow?: string;
    hero_title?: string;
    hero_summary?: string;
    keywords?: string[];
    narrative_lede?: string;
    market_context?: string;
    analyst_commentary?: string;
    key_takeaways?: Array<{ heading: string; detail: string }>;
    metrics?: Array<{ label: string; value: string; change?: string; period?: string; source?: string }>;
    sections?: Array<{ heading: string; paragraphs?: string[]; bullets?: string[] }>;
    faqs?: Array<{ question: string; answer: string }>;
    [k: string]: unknown;
  };
  editorial_review?: Record<string, any>;
}

export interface FlashIngestRequest {
  content_type: 'earnings' | 'sebi' | 'trend';
  mode?: 'flash' | 'deep' | 'research';
  symbols?: string[];
  isin_list?: string[];
  bse_codes?: string[];
  route_base?: string;
  max_events_per_source?: number;
  include_image?: boolean;
  dry_run?: boolean;
}

export interface AutomationStatus {
  status: string;
  last_started_at: string;
  last_completed_at: string;
  last_error: string;
  last_summary: Record<string, any>;
  source_health: Record<string, any>;
  current_run?: Record<string, any>;
  activity_log?: Array<Record<string, any>>;
  recent_items: Array<Record<string, any>>;
  cursor: number;
  updated_at: string;
  automation_mode?: string;
  automation_label?: string;
  status_detail?: string;
  scheduler_status?: string;
  scheduler_enabled?: boolean;
  scheduler_last_heartbeat_at?: string;
  next_scheduled_run_at?: string;
  fallback_status?: string;
  fallback_daily_count?: number;
  fallback_daily_target?: number;
  fallback_remaining_today?: number;
  fallback_generated_today?: number;
  fallback_published_today?: number;
  fallback_held_today?: number;
  fallback_candidates_considered?: number;
  fallback_qualified_topics?: number;
  fallback_last_action?: string;
  fallback_review_reasons?: string[];
  next_fallback_after?: string;
  search_console?: {
    enabled?: boolean;
    configured?: boolean;
    site_url?: string;
    sitemap_url?: string;
    error?: string;
    top_pages?: Array<Record<string, any>>;
    top_queries?: Array<Record<string, any>>;
    generated_at?: string;
  };
}

export async function generateFlashArticle(req: FlashGenerationRequest): Promise<FlashJobStarted> {
  const res = await fetchApi(apiUrl('/api/content/flash/generate'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Flash generation failed: ${res.statusText}`);
  }
  return res.json();
}

export async function ingestFlashEvents(req: FlashIngestRequest): Promise<FlashJobStarted> {
  const res = await fetchApi(apiUrl('/api/content/flash/ingest-events'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Ingest failed: ${res.statusText}`);
  }
  return res.json();
}

export async function getContentAutomationStatus(): Promise<AutomationStatus> {
  const res = await fetchApi(apiUrl('/api/content/automation/status'), {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch automation status: ${res.statusText}`);
  }
  return res.json();
}

export async function runContentAutomationNow(): Promise<FlashJobStarted> {
  const res = await fetchApi(apiUrl('/api/content/automation/run-now'), {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to start automation sweep: ${res.statusText}`);
  }
  return res.json();
}

export async function listContentArticles(
  routeBase?: string,
  limit = 80,
): Promise<{ items: ArticleListItem[]; count: number }> {
  const params = new URLSearchParams();
  if (routeBase) params.set('route_base', routeBase);
  params.set('limit', String(limit));
  const res = await fetchApi(apiUrl(`/api/content/articles?${params.toString()}`), {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Failed to list articles: ${res.statusText}`);
  return parseJsonSanitized(res);
}

export async function getContentArticle(slug: string, routeBase = 'insights'): Promise<ArticleDetail> {
  const res = await fetchApi(
    apiUrl(`/api/content/articles/${encodeURIComponent(slug)}?route_base=${routeBase}`),
    { credentials: 'include' },
  );
  if (!res.ok) throw new Error(`Article not found: ${slug}`);
  return parseJsonSanitized(res);
}

export async function getContentArticleHtml(slug: string, routeBase = 'insights'): Promise<string> {
  const res = await fetchApi(
    apiUrl(`/api/content/articles/${encodeURIComponent(slug)}/html?route_base=${routeBase}`),
    { credentials: 'include' },
  );
  if (!res.ok) throw new Error(`Article HTML not found: ${slug}`);
  return res.text();
}

export async function publishContentArticle(
  slug: string,
  routeBase = 'insights',
): Promise<{ slug: string; publish_status: string; publish_gate_status?: string; public_url?: string }> {
  const res = await fetchApi(
    apiUrl(`/api/content/articles/${encodeURIComponent(slug)}/publish?route_base=${routeBase}`),
    { method: 'POST', credentials: 'include' },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Publish failed: ${res.statusText}`);
  }
  return res.json();
}

export async function unpublishContentArticle(
  slug: string,
  routeBase = 'insights',
): Promise<{ slug: string; publish_status: string; publish_gate_status?: string }> {
  const res = await fetchApi(
    apiUrl(`/api/content/articles/${encodeURIComponent(slug)}/unpublish?route_base=${routeBase}`),
    { method: 'POST', credentials: 'include' },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Unpublish failed: ${res.statusText}`);
  }
  return res.json();
}

/** Returns the SSE stream URL for a flash job (caller creates EventSource). */
export function flashJobStreamUrl(jobId: string): string {
  return apiUrl(`/sessions/${encodeURIComponent(jobId)}/stream`);
}

export function flashJobStatusUrl(jobId: string): string {
  return apiUrl(`/sessions/${encodeURIComponent(jobId)}/status`);
}


// ── Document export (deep mode only) ─────────────────────────────────

export type ExportFormat = 'pdf' | 'docx' | 'xlsx';

export interface ExportJobStatus {
  job_id: string;
  status: 'queued' | 'running' | 'done' | 'error';
  format?: string;
  error?: string;
}

export async function requestExport(
  sessionId: string,
  format: ExportFormat,
  style: string = 'sell_side',
): Promise<ExportJobStatus> {
  const res = await fetchApi(apiUrl('/research/export'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ session_id: sessionId, format, style }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Export request failed: ${res.statusText}`);
  }
  return res.json();
}

export async function pollExport(jobId: string): Promise<ExportJobStatus> {
  const res = await fetchApi(apiUrl(`/research/export/${encodeURIComponent(jobId)}`), {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Export poll failed: ${res.statusText}`);
  return res.json();
}

export async function downloadExport(jobId: string): Promise<Blob> {
  const res = await fetchApi(apiUrl(`/research/export/${encodeURIComponent(jobId)}/download`), {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Export download failed: ${res.statusText}`);
  return res.blob();
}

export async function downloadExportAndSave(jobId: string, format: ExportFormat): Promise<void> {
  const blob = await downloadExport(jobId);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `prospektlab_report.${format}`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 100);
}

