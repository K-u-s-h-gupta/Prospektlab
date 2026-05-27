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

// Token and User Helpers
export function getAuthToken(): string | null {
  return localStorage.getItem('prospektlab_token');
}

export function getAuthHeaders(): HeadersInit {
  const token = getAuthToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

function handleSessionSwitch(email: string) {
  const lastEmail = localStorage.getItem('prospektlab_last_email');
  if (lastEmail && lastEmail.toLowerCase().trim() !== email.toLowerCase().trim()) {
    const keysToRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith('prospektlab_')) {
        keysToRemove.push(key);
      }
    }
    keysToRemove.forEach(key => localStorage.removeItem(key));
  }
  localStorage.setItem('prospektlab_last_email', email);
}

// ── Auth Endpoints ──────────────────────────────────────────────────────

export async function apiLogin(email: string, password: string): Promise<any> {
  const res = await fetch(apiUrl('/auth/login'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Login failed: ${res.statusText}`);
  }

  const data = await res.json();
  if (data.token) {
    const emailToSet = data.user?.email || email;
    handleSessionSwitch(emailToSet);
    localStorage.setItem('prospektlab_token', data.token);
    localStorage.setItem('prospektlab_user', JSON.stringify({
      email: emailToSet,
      name: data.user?.name || 'Researcher',
    }));
  }
  return data;
}

export async function apiSignup(name: string, email: string, password: string, mobile: string, verificationCode: string): Promise<any> {
  const res = await fetch(apiUrl('/auth/signup'), {
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
  });

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
  const res = await fetch(apiUrl('/auth/google'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ credential }),
  });

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
  const res = await fetch(apiUrl('/auth/google/update-mobile'), {
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
}

// ── Portfolio Endpoints ──────────────────────────────────────────────────

export async function getPortfolioMirror(): Promise<any> {
  const res = await fetch(apiUrl('/portfolio/mirror'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to load portfolio mirror: ${res.statusText}`);
  }
  return res.json();
}

export async function replacePortfolioMirror(positions: PositionInput[]): Promise<any> {
  const res = await fetch(apiUrl('/portfolio/mirror'), {
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

  const res = await fetch(apiUrl('/api/portfolio/upload-cas'), {
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

  const res = await fetch(apiUrl('/api/portfolio/upload-screenshot'), {
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
  const res = await fetch(apiUrl('/api/portfolio/confirm-extraction'), {
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
  const res = await fetch(apiUrl('/api/portfolio/cancel-extraction'), {
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
  const res = await fetch(apiUrl(`/portfolio/analytics?benchmark=${encodeURIComponent(benchmark)}&period=${encodeURIComponent(period)}`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio analytics: ${res.statusText}`);
  }
  return res.json();
}

export async function deletePortfolioMirror(): Promise<any> {
  const res = await fetch(apiUrl('/portfolio/mirror'), {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to clear portfolio: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioNews(limit: number = 12): Promise<any> {
  const res = await fetch(apiUrl(`/portfolio/news?limit=${limit}`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio news: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioSectors(): Promise<any> {
  const res = await fetch(apiUrl('/portfolio/sectors'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio sectors: ${res.statusText}`);
  }
  return res.json();
}

export async function getHoldingDetail(symbol: string): Promise<any> {
  const res = await fetch(apiUrl(`/portfolio/holding/${encodeURIComponent(symbol)}`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch holding detail: ${res.statusText}`);
  }
  return res.json();
}

export async function getCorporateActions(days: number = 30): Promise<any> {
  const res = await fetch(apiUrl(`/portfolio/corporate-actions?days=${days}`), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch corporate actions: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioAlerts(): Promise<any> {
  const res = await fetch(apiUrl('/portfolio/alerts'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch portfolio alerts: ${res.statusText}`);
  }
  return res.json();
}

export async function getTaxSummary(): Promise<any> {
  const res = await fetch(apiUrl('/portfolio/tax-summary'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch tax summary: ${res.statusText}`);
  }
  return res.json();
}

export async function getDividends(): Promise<any> {
  const res = await fetch(apiUrl('/portfolio/dividends'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch dividends: ${res.statusText}`);
  }
  return res.json();
}

export async function postStressTest(scenario: string, customShocks?: any): Promise<any> {
  const res = await fetch(apiUrl('/portfolio/stress-test'), {
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
  const res = await fetch(apiUrl('/portfolio/mf-analytics'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch MF analytics: ${res.statusText}`);
  }
  return res.json();
}

export async function getTodayQueue(): Promise<any> {
  const res = await fetch(apiUrl('/portfolio/today'), {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch action queue: ${res.statusText}`);
  }
  return res.json();
}

export async function getPortfolioBrief(): Promise<any> {
  const res = await fetch(apiUrl('/portfolio/brief'), {
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

  const res = await fetch(apiUrl('/chat/research'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail?.message || errorData.detail || `Failed to start research: ${res.statusText}`);
  }

  return res.json();
}

export async function stopSession(sessionId: string): Promise<any> {
  const res = await fetch(apiUrl(`/sessions/${encodeURIComponent(sessionId)}/stop`), {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to stop research session: ${res.statusText}`);
  }
  return res.json();
}

export async function getSessionResult(sessionId: string): Promise<FinalResponse> {
  const res = await fetch(apiUrl(`/sessions/${encodeURIComponent(sessionId)}/result`), {
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
  const path = `/sessions/${encodeURIComponent(sessionId)}/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`;
  const url = apiUrl(path);

  const eventSource = new EventSource(url);
  let hasClosed = false;

  const closeStream = () => {
    if (!hasClosed) {
      hasClosed = true;
      eventSource.close();
    }
  };

  eventSource.addEventListener('agent_event', (e: any) => {
    if (hasClosed) return;
    try {
      const parsed = JSON.parse(e.data);
      onEvent({
        seq: parsed.id || 0,
        type: 'agent_event',
        timestamp: parsed.timestamp || '',
        payload: parsed,
      });
    } catch (err) {
      console.error('Failed to parse agent event', err);
    }
  });

  eventSource.addEventListener('phase', (e: any) => {
    if (hasClosed) return;
    try {
      const parsed = JSON.parse(e.data);
      onEvent({
        seq: parsed.id || 0,
        type: 'phase',
        timestamp: parsed.timestamp || '',
        payload: parsed,
      });
    } catch (err) {
      console.error('Failed to parse phase event', err);
    }
  });

  eventSource.addEventListener('deep_pass', (e: any) => {
    if (hasClosed) return;
    try {
      const parsed = JSON.parse(e.data);
      onEvent({
        seq: parsed.id || 0,
        type: 'deep_pass',
        timestamp: parsed.timestamp || '',
        payload: parsed,
      });
    } catch (err) {
      console.error('Failed to parse deep pass event', err);
    }
  });

  eventSource.addEventListener('memo', (e: any) => {
    if (hasClosed) return;
    try {
      const parsed = JSON.parse(e.data);
      closeStream();
      onFinal(parsed);
    } catch (err) {
      console.error('Failed to parse memo event', err);
    }
  });

  eventSource.addEventListener('final', (e: any) => {
    if (hasClosed) return;
    try {
      const parsed = JSON.parse(e.data);
      closeStream();
      onFinal(parsed);
    } catch (err) {
      console.error('Failed to parse final event', err);
    }
  });

  eventSource.addEventListener('error', (e: any) => {
    if (hasClosed) return;
    try {
      const parsed = JSON.parse(e.data);
      closeStream();
      onError(new Error(parsed.message || 'Stream processing error'));
    } catch (err) {
      closeStream();
      onError(new Error('Stream encountered an error'));
    }
  });

  eventSource.onerror = () => {
    closeStream();
  };

  return () => {
    closeStream();
  };
}
