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

const AUTH_REQUEST_TIMEOUT_MS = 15000;
const MIRROR_STATUS_TIMEOUT_MS = 8000;

async function fetchWithTimeout(url: string, options: RequestInit, timeoutMs: number, timeoutMessage: string): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      throw new Error(timeoutMessage);
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

// Token and User Helpers
export function getAuthToken(): string | null {
  return localStorage.getItem('prospektlab_token') || sessionStorage.getItem('prospektlab_token');
}

function getAuthStorage(remember: boolean): Storage {
  return remember ? localStorage : sessionStorage;
}

function removeAuthSessionKeys(storage: Storage) {
  storage.removeItem('prospektlab_token');
  storage.removeItem('prospektlab_user');
}

export function getStoredAuthUser(): string | null {
  return localStorage.getItem('prospektlab_user') || sessionStorage.getItem('prospektlab_user');
}

export function getAuthHeaders(): HeadersInit {
  const token = getAuthToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const bypass = typeof window !== 'undefined' && localStorage.getItem('prospektlab_bypass_token_limit') === 'true';
  if (bypass) {
    headers['X-Bypass-Token-Limit'] = 'true';
  }
  return headers as any;
}

function handleSessionSwitch(email: string) {
  const lastEmail = localStorage.getItem('prospektlab_last_email') || sessionStorage.getItem('prospektlab_last_email');
  if (lastEmail && lastEmail.toLowerCase().trim() !== email.toLowerCase().trim()) {
    const keysToRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith('prospektlab_')) {
        keysToRemove.push(key);
      }
    }
    keysToRemove.forEach(key => localStorage.removeItem(key));
    const sessionKeysToRemove: string[] = [];
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i);
      if (key && key.startsWith('prospektlab_')) {
        sessionKeysToRemove.push(key);
      }
    }
    sessionKeysToRemove.forEach(key => sessionStorage.removeItem(key));
  }
  localStorage.setItem('prospektlab_last_email', email);
}

function handleAuthFailure() {
  const keysToRemove: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && key.startsWith('prospektlab_')) {
      keysToRemove.push(key);
    }
  }
  keysToRemove.forEach(key => localStorage.removeItem(key));
  const sessionKeysToRemove: string[] = [];
  for (let i = 0; i < sessionStorage.length; i++) {
    const key = sessionStorage.key(i);
    if (key && key.startsWith('prospektlab_')) {
      sessionKeysToRemove.push(key);
    }
  }
  sessionKeysToRemove.forEach(key => sessionStorage.removeItem(key));
  if (typeof window !== 'undefined') {
    window.location.hash = '#/login';
  }
}

async function fetchApi(url: string, options?: RequestInit): Promise<Response> {
  const res = await fetch(url, options);
  if (res.status === 401) {
    handleAuthFailure();
  }
  return res;
}

// ── Auth Endpoints ──────────────────────────────────────────────────────

export async function apiLogin(email: string, password: string, remember: boolean = true): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl('/auth/login'),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password }),
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
    const emailToSet = data.user?.email || email;
    handleSessionSwitch(emailToSet);
    const storage = getAuthStorage(remember);
    const otherStorage = remember ? sessionStorage : localStorage;
    removeAuthSessionKeys(otherStorage);
    storage.setItem('prospektlab_token', data.token);
    storage.setItem('prospektlab_user', JSON.stringify({
      email: emailToSet,
      name: data.user?.name || 'Researcher',
    }));
    storage.setItem('prospektlab_last_email', emailToSet);
  }
  return data;
}

export async function apiSignup(name: string, email: string, password: string, mobile: string, verificationCode: string): Promise<any> {
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
        verification_code: verificationCode,
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
    const emailToSet = data.user?.email || email;
    handleSessionSwitch(emailToSet);
    localStorage.setItem('prospektlab_token', data.token);
    localStorage.setItem('prospektlab_user', JSON.stringify({
      email: emailToSet,
      name: data.user?.name || name,
    }));
  }
  return data;
}

export async function apiSendVerification(email: string): Promise<any> {
  const res = await fetch(apiUrl('/auth/send-verification'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to send verification: ${res.statusText}`);
  }

  return res.json();
}

export async function apiForgotPassword(email: string): Promise<any> {
  const res = await fetch(apiUrl('/auth/forgot-password'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to send reset code: ${res.statusText}`);
  }

  return res.json();
}

export async function apiResetPassword(email: string, code: string, newPassword: string): Promise<any> {
  const res = await fetch(apiUrl('/auth/reset-password'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, code, new_password: newPassword }),
  });

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
    const emailToSet = data.email;
    if (emailToSet) {
      handleSessionSwitch(emailToSet);
    }
    localStorage.setItem('prospektlab_token', data.token);
    localStorage.setItem('prospektlab_user', JSON.stringify({
      email: data.email,
      name: data.name || data.full_name || 'Researcher',
      mobile: data.mobile,
      require_mobile: data.require_mobile,
    }));
  }
  return data;
}

export async function apiUpdateMobile(mobile: string): Promise<any> {
  const res = await fetchApi(apiUrl('/auth/google/update-mobile'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ mobile }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to update mobile: ${res.statusText}`);
  }

  // Update mobile in localStorage user if available
  const userStr = localStorage.getItem('prospektlab_user');
  if (userStr) {
    const user = JSON.parse(userStr);
    user.mobile = mobile;
    user.require_mobile = false;
    localStorage.setItem('prospektlab_user', JSON.stringify(user));
  }

  return res.json();
}

export async function apiLogout(): Promise<void> {
  await fetch(apiUrl('/auth/logout'), {
    method: 'POST',
    headers: getAuthHeaders(),
  }).catch(() => {});
  
  const keysToRemove: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && key.startsWith('prospektlab_')) {
      keysToRemove.push(key);
    }
  }
  keysToRemove.forEach(key => localStorage.removeItem(key));
  const sessionKeysToRemove: string[] = [];
  for (let i = 0; i < sessionStorage.length; i++) {
    const key = sessionStorage.key(i);
    if (key && key.startsWith('prospektlab_')) {
      sessionKeysToRemove.push(key);
    }
  }
  sessionKeysToRemove.forEach(key => sessionStorage.removeItem(key));
}

// ── Portfolio Endpoints ──────────────────────────────────────────────────

export async function getPortfolioMirror(): Promise<any> {
  const res = await fetchWithTimeout(
    apiUrl('/portfolio/mirror'),
    {
      headers: getAuthHeaders(),
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
  return res.json();
}

export async function replacePortfolioMirror(positions: PositionInput[]): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/mirror'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ positions }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail?.message || errorData.detail || `Failed to replace portfolio mirror: ${res.statusText}`);
  }
  return res.json();
}

export async function uploadPortfolioDocument(file: File, password?: string): Promise<any> {
  const formData = new FormData();
  formData.append('file', file);
  if (password) {
    formData.append('password', password);
  }

  const res = await fetchApi(apiUrl('/api/portfolio/upload-cas'), {
    method: 'POST',
    headers: getAuthHeaders(),
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail?.message || errorData.detail || `Failed to parse document: ${res.statusText}`);
  }

  return res.json();
}

export async function uploadPortfolioScreenshot(file: File): Promise<any> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetchApi(apiUrl('/api/portfolio/upload-screenshot'), {
    method: 'POST',
    headers: getAuthHeaders(),
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail?.message || errorData.detail || `Failed to parse screenshot: ${res.statusText}`);
  }

  return res.json();
}

export async function confirmExtraction(reviewId: string, positions?: any[], sourceType?: string): Promise<any> {
  const res = await fetchApi(apiUrl('/api/portfolio/confirm-extraction'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({
      review_id: reviewId,
      positions: positions,
      source_type: sourceType,
    }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail?.message || errorData.detail || `Failed to confirm extraction: ${res.statusText}`);
  }

  return res.json();
}

export async function cancelExtraction(): Promise<any> {
  const res = await fetchApi(apiUrl('/api/portfolio/cancel-extraction'), {
    method: 'POST',
    headers: getAuthHeaders(),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to cancel extraction: ${res.statusText}`);
  }

  return res.json();
}

export async function getPortfolioAnalytics(benchmark: string = 'NIFTY50', period: string = '1y'): Promise<any> {
  const res = await fetchApi(apiUrl(`/portfolio/analytics?benchmark=${encodeURIComponent(benchmark)}&period=${encodeURIComponent(period)}`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio analytics: ${res.statusText}`);
  }
  return res.json();
}

export async function deletePortfolioMirror(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/mirror'), {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to clear portfolio: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioNews(limit: number = 12): Promise<any> {
  const res = await fetchApi(apiUrl(`/portfolio/news?limit=${limit}`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio news: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioSectors(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/sectors'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio sectors: ${res.statusText}`);
  }
  return res.json();
}

export async function getHoldingDetail(symbol: string): Promise<any> {
  const res = await fetchApi(apiUrl(`/portfolio/holding/${encodeURIComponent(symbol)}`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch holding detail: ${res.statusText}`);
  }
  return res.json();
}

export async function getCorporateActions(days: number = 30): Promise<any> {
  const res = await fetchApi(apiUrl(`/portfolio/corporate-actions?days=${days}`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch corporate actions: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioAlerts(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/alerts'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio alerts: ${res.statusText}`);
  }
  return res.json();
}

export async function getTaxSummary(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/tax-summary'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch tax summary: ${res.statusText}`);
  }
  return res.json();
}

export async function getDividends(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/dividends'), {
    headers: getAuthHeaders(),
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
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ scenario, custom_shocks: customShocks }),
  });
  if (!res.ok) {
    throw new Error(`Failed to run stress test: ${res.statusText}`);
  }
  return res.json();
}

export async function getMfAnalytics(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/mf-analytics'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch MF analytics: ${res.statusText}`);
  }
  return res.json();
}

export async function getTodayQueue(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/today'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch action queue: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioBrief(): Promise<any> {
  const res = await fetchApi(apiUrl('/portfolio/brief'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio brief: ${res.statusText}`);
  }
  return res.json();
}

// ── Research and Chat SSE Endpoints ────────────────────────────────────────

export async function startResearch(message: string, mode: 'standard' | 'deep', sessionId?: string, portfolioContext?: string): Promise<any> {
  const payload: Record<string, any> = {
    message: message,
    mode: mode,
  };
  if (sessionId) {
    payload.session_id = sessionId;
  }
  // If portfolioContext is passed, we prepend it to the message or pass as objective
  // The backend chat_research takes a ChatResearchRequest with:
  // message: str, mode: str, session_id: str | None
  // But wait! StartResearchRequest takes:
  // target: str, objective: str, mode: str, session_id: str | None
  // Let's use the chat_research endpoint POST /chat/research:
  // message: req.message, mode: req.mode, session_id: req.session_id
  // If portfolioContext is provided, we send it in req.message.
  const rewrittenMessage = portfolioContext ? `${portfolioContext} ${message}` : message;
  payload.message = rewrittenMessage;

  const headers: any = {
    'Content-Type': 'application/json',
    ...getAuthHeaders(),
  };
  if (typeof window !== 'undefined' && localStorage.getItem('prospektlab_bypass_token_limit') === 'true') {
    headers['X-Bypass-Token-Limit'] = 'true';
  }

  const res = await fetchApi(apiUrl('/chat/research'), {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    const err = new Error(errorData.detail?.message || errorData.detail || `Failed to start research: ${res.statusText}`);
    (err as any).detail = errorData.detail;
    throw err;
  }

  return res.json();
}

export async function stopSession(sessionId: string): Promise<any> {
  const res = await fetchApi(apiUrl(`/sessions/${encodeURIComponent(sessionId)}/stop`), {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to stop research session: ${res.statusText}`);
  }
  return res.json();
}

export async function getSessionResult(sessionId: string): Promise<FinalResponse> {
  const res = await fetchApi(apiUrl(`/sessions/${encodeURIComponent(sessionId)}/result`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch session result: ${res.statusText}`);
  }
  return res.json();
}

export function streamSession(
  sessionId: string,
  onEvent: (event: AgentEventData) => void,
  onFinal: (final: any) => void,
  onError: (error: any) => void
): () => void {
  const token = getAuthToken();
  
  let lastEventId: number | null = null;
  let sseAbort = new AbortController();
  let sseReconnectTimer: any = null;
  let sseActive = true;
  let onFinalCalled = false;
  let onErrorCalled = false;

  const closeStream = () => {
    if (sseActive) {
      sseActive = false;
      clearTimeout(sseReconnectTimer);
      sseAbort.abort();
    }
  };

  async function finalizeFromResult() {
    if (onFinalCalled || onErrorCalled) return;
    try {
      const result = await getSessionResult(sessionId);
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
        if (!onErrorCalled) {
          onErrorCalled = true;
          onError(new Error(parsed.message || 'Stream processing error'));
        }
      } catch (err) {
        closeStream();
        if (!onErrorCalled) {
          onErrorCalled = true;
          onError(new Error('Stream encountered an error'));
        }
      }
      return;
    }

    if (evType === 'done' || evType === 'deep_complete') {
      closeStream();
      void finalizeFromResult();
    }
  }

  async function connectSSE() {
    if (!sseActive) return;
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
    if (token) {
      headers["Authorization"] = "Bearer " + token;
    }
    if (lastEventId !== null) {
      headers["Last-Event-ID"] = String(lastEventId);
    }

    const path = `/sessions/${encodeURIComponent(sessionId)}/stream`;
    let url = apiUrl(path);
    if (token) {
      url += (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token);
    }
    if (lastEventId !== null) {
      url += (url.includes("?") ? "&" : "?") + "after=" + encodeURIComponent(lastEventId);
    }

    let resp: Response;
    try {
      resp = await fetch(url, { headers, signal: sseAbort.signal });
    } catch (err: any) {
      if (!sseActive) return;
      if (err && err.name === "AbortError") return; // proactive reconnect
      console.warn("SSE fetch error, retrying in 2s:", err);
      clearTimeout(sseReconnectTimer);
      sseReconnectTimer = setTimeout(connectSSE, 2000);
      return;
    }

    if (!resp.ok) {
      if (!sseActive) return;
      if (resp.status === 404) {
        closeStream();
        void finalizeFromResult();
        return;
      }
      console.warn("SSE HTTP error status:", resp.status, "— retrying in 3s");
      clearTimeout(sseReconnectTimer);
      sseReconnectTimer = setTimeout(connectSSE, 3000);
      return;
    }

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
      while (true) {
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
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch user token usage: ${res.statusText}`);
  }
  return res.json();
}

export async function getMarketQuotes(symbols: string[]): Promise<any> {
  const res = await fetchApi(apiUrl(`/market/quotes?symbols=${encodeURIComponent(symbols.join(','))}`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch market quotes: ${res.statusText}`);
  }
  return res.json();
}

export async function getMarketNews(query?: string): Promise<any> {
  const qStr = query ? `?query=${encodeURIComponent(query)}` : '';
  const res = await fetchApi(apiUrl(`/market/news${qStr}`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch market news: ${res.statusText}`);
  }
  return res.json();
}

export async function getMarketIndices(): Promise<any> {
  const res = await fetchApi(apiUrl('/market/indices'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch market indices: ${res.statusText}`);
  }
  return res.json();
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
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch market history: ${res.statusText}`);
  }
  return res.json();
}

