type TelemetryConfig = {
  enabled?: boolean;
  connectionString?: string;
  roleName?: string;
  cloudRoleInstance?: string;
};

type TelemetryUser = {
  email: string;
  name: string;
};

type TelemetryMeasurements = Record<string, number>;
type TelemetryProperties = Record<string, string | number | boolean | null | undefined>;

type RuntimeConfig = {
  apiBase?: string;
  environment?: string;
  telemetry?: TelemetryConfig;
};

type RuntimeWindow = Window & {
  __BACKEND_URL?: string;
  __CONFIG__?: RuntimeConfig;
};

type TelemetryEnvelope = {
  name: string;
  time: string;
  iKey: string;
  tags: Record<string, string>;
  data: {
    baseType: string;
    baseData: Record<string, any>;
  };
};

const SESSION_STORAGE_KEY = 'prospektlab_telemetry_session_id';
const CLIENT_IDENTITY_KEY = 'prospektlab_telemetry_user';

let initialized = false;
let enabled = false;
let ingestionUrl = '';
let instrumentationKey = '';
let sessionId = '';
let currentUser: TelemetryUser | null = null;
let appRoleName = 'prospektlab-frontend';
let cloudRoleInstance = 'browser';

function getRuntimeWindow(): RuntimeWindow | undefined {
  if (typeof window === 'undefined') {
    return undefined;
  }
  return window as RuntimeWindow;
}

function readRuntimeConfig(): TelemetryConfig {
  const runtimeWindow = getRuntimeWindow();
  const runtimeConfig = runtimeWindow?.__CONFIG__?.telemetry || {};
  const envConnectionString = ((import.meta as any)?.env?.VITE_APPINSIGHTS_CONNECTION_STRING || '') as string;

  return {
    enabled: runtimeConfig.enabled ?? Boolean(runtimeConfig.connectionString || envConnectionString),
    connectionString: runtimeConfig.connectionString || envConnectionString || '',
    roleName: runtimeConfig.roleName,
    cloudRoleInstance: runtimeConfig.cloudRoleInstance,
  };
}

function parseConnectionString(connectionString: string): { ingestionUrl: string; instrumentationKey: string } | null {
  const parts = connectionString
    .split(';')
    .map((segment) => segment.trim())
    .filter(Boolean);

  const parsed: Record<string, string> = {};
  for (const part of parts) {
    const eqIndex = part.indexOf('=');
    if (eqIndex <= 0) {
      continue;
    }
    const key = part.slice(0, eqIndex).trim().toLowerCase();
    const value = part.slice(eqIndex + 1).trim();
    parsed[key] = value;
  }

  const instrumentationKeyValue = parsed['instrumentationkey'];
  const ingestionEndpoint = parsed['ingestionendpoint'] || 'https://dc.services.visualstudio.com';
  if (!instrumentationKeyValue) {
    return null;
  }

  const normalizedEndpoint = ingestionEndpoint.endsWith('/')
    ? ingestionEndpoint
    : `${ingestionEndpoint}/`;

  return {
    instrumentationKey: instrumentationKeyValue,
    ingestionUrl: new URL('v2/track', normalizedEndpoint).toString(),
  };
}

function ensureSessionId(): string {
  if (sessionId) {
    return sessionId;
  }

  const runtimeWindow = getRuntimeWindow();
  if (!runtimeWindow) {
    sessionId = `telemetry-${Date.now()}`;
    return sessionId;
  }

  try {
    const stored = runtimeWindow.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (stored) {
      sessionId = stored;
      return sessionId;
    }
  } catch (_) {
    // Ignore storage access issues and fall back to an in-memory identifier.
  }

  sessionId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `telemetry-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

  try {
    runtimeWindow.sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  } catch (_) {
    // Ignore storage access issues.
  }

  return sessionId;
}

function formatDuration(durationMs?: number): string {
  const totalMs = Math.max(0, Math.round(durationMs || 0));
  const hours = Math.floor(totalMs / 3_600_000);
  const minutes = Math.floor((totalMs % 3_600_000) / 60_000);
  const seconds = Math.floor((totalMs % 60_000) / 1_000);
  const millis = totalMs % 1_000;

  const pad = (value: number, width = 2) => value.toString().padStart(width, '0');
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}.${pad(millis, 3)}`;
}

function sanitizeProperties(properties?: TelemetryProperties): Record<string, string> {
  const sanitized: Record<string, string> = {};
  if (!properties) {
    return sanitized;
  }

  for (const [key, value] of Object.entries(properties)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (typeof value === 'string') {
      sanitized[key] = value;
    } else if (typeof value === 'number' || typeof value === 'boolean') {
      sanitized[key] = String(value);
    } else {
      sanitized[key] = JSON.stringify(value);
    }
  }

  return sanitized;
}

function sanitizeMeasurements(measurements?: TelemetryMeasurements): TelemetryMeasurements {
  const sanitized: TelemetryMeasurements = {};
  if (!measurements) {
    return sanitized;
  }

  for (const [key, value] of Object.entries(measurements)) {
    if (typeof value === 'number' && Number.isFinite(value)) {
      sanitized[key] = value;
    }
  }

  return sanitized;
}

function buildTags(extraTags?: Record<string, string>): Record<string, string> {
  const tags: Record<string, string> = {
    'ai.application.ver': 'prospektlab-web',
    'ai.device.id': ensureSessionId(),
    'ai.session.id': ensureSessionId(),
    'ai.cloud.role': appRoleName,
    'ai.cloud.roleInstance': cloudRoleInstance,
    'ai.operation.id': ensureSessionId(),
  };

  if (currentUser) {
    tags['ai.user.id'] = currentUser.email;
    tags['ai.user.authUserId'] = currentUser.email;
    tags['ai.user.accountId'] = currentUser.email;
  }

  return {
    ...tags,
    ...(extraTags || {}),
  };
}

function buildEnvelope(baseType: string, baseData: Record<string, any>, extraTags?: Record<string, string>): TelemetryEnvelope {
  return {
    name: `Microsoft.ApplicationInsights.${baseType}`,
    time: new Date().toISOString(),
    iKey: instrumentationKey,
    tags: buildTags(extraTags),
    data: {
      baseType,
      baseData,
    },
  };
}

async function postEnvelopes(envelopes: TelemetryEnvelope[]): Promise<void> {
  if (!enabled || envelopes.length === 0 || !ingestionUrl) {
    return;
  }

  const payload = JSON.stringify(envelopes);

  if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
    const blob = new Blob([payload], { type: 'application/json' });
    if (navigator.sendBeacon(ingestionUrl, blob)) {
      return;
    }
  }

  await fetch(ingestionUrl, {
    method: 'POST',
    mode: 'cors',
    keepalive: true,
    headers: {
      'Content-Type': 'application/json',
    },
    body: payload,
  }).catch(() => {});
}

function schedule(envelopes: TelemetryEnvelope[]): void {
  if (!enabled || envelopes.length === 0) {
    return;
  }

  void postEnvelopes(envelopes);
}

function buildCommonProperties(properties?: TelemetryProperties): Record<string, string> {
  const runtimeWindow = getRuntimeWindow();
  const base: Record<string, string> = {
    source: 'frontend',
    session_id: ensureSessionId(),
    environment: runtimeWindow?.__CONFIG__?.environment || (import.meta as any)?.env?.MODE || 'unknown',
  };

  if (currentUser) {
    base.user_email = currentUser.email;
    base.user_name = currentUser.name;
  }

  return {
    ...base,
    ...sanitizeProperties(properties),
  };
}

function handleGlobalError(event: ErrorEvent) {
  trackException(event.error || new Error(event.message || 'Unhandled error'), {
    handler: 'window.error',
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
  });
}

function handleUnhandledRejection(event: PromiseRejectionEvent) {
  const reason = event.reason instanceof Error
    ? event.reason
    : new Error(typeof event.reason === 'string' ? event.reason : 'Unhandled promise rejection');
  trackException(reason, {
    handler: 'window.unhandledrejection',
  });
}

export function initializeTelemetry(): void {
  if (initialized) {
    return;
  }
  initialized = true;

  const config = readRuntimeConfig();
  enabled = Boolean(config.enabled && config.connectionString);
  if (!enabled) {
    return;
  }

  const parsed = parseConnectionString(config.connectionString || '');
  if (!parsed) {
    enabled = false;
    return;
  }

  ingestionUrl = parsed.ingestionUrl;
  instrumentationKey = parsed.instrumentationKey;
  appRoleName = config.roleName || 'prospektlab-frontend';
  cloudRoleInstance = config.cloudRoleInstance || 'browser';
  ensureSessionId();

  const runtimeWindow = getRuntimeWindow();
  if (runtimeWindow) {
    runtimeWindow.addEventListener('error', handleGlobalError);
    runtimeWindow.addEventListener('unhandledrejection', handleUnhandledRejection);
  }

  trackEvent('app_initialized', {
    session_id: ensureSessionId(),
    environment: getRuntimeWindow()?.__CONFIG__?.environment || (import.meta as any)?.env?.MODE || 'unknown',
  });
}

export function getTelemetrySessionId(): string {
  return ensureSessionId();
}

export function setTelemetryUser(user: TelemetryUser | null): void {
  currentUser = user
    ? {
        email: user.email,
        name: user.name || user.email,
      }
    : null;

  const runtimeWindow = getRuntimeWindow();
  if (!runtimeWindow) {
    return;
  }

  try {
    if (currentUser) {
      runtimeWindow.sessionStorage.setItem(CLIENT_IDENTITY_KEY, JSON.stringify(currentUser));
    } else {
      runtimeWindow.sessionStorage.removeItem(CLIENT_IDENTITY_KEY);
    }
  } catch (_) {
    // Ignore storage access issues.
  }
}

export function clearTelemetryUser(): void {
  setTelemetryUser(null);
}

export function trackEvent(name: string, properties?: TelemetryProperties, measurements?: TelemetryMeasurements): void {
  if (!enabled) {
    return;
  }

  schedule([
    buildEnvelope('EventData', {
      ver: 2,
      name,
      properties: buildCommonProperties(properties),
      measurements: sanitizeMeasurements(measurements),
    }),
  ]);
}

export function trackPageView(name: string, properties?: TelemetryProperties): void {
  if (!enabled) {
    return;
  }

  const runtimeWindow = getRuntimeWindow();
  const navigationEntry = typeof performance !== 'undefined'
    ? performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
    : undefined;
  const durationMs = navigationEntry?.duration;

  schedule([
    buildEnvelope('PageviewData', {
      ver: 2,
      name,
      uri: runtimeWindow?.location?.href || name,
      duration: typeof durationMs === 'number' ? formatDuration(durationMs) : undefined,
      properties: buildCommonProperties({
        page_title: runtimeWindow?.document?.title || name,
        referrer: runtimeWindow?.document?.referrer || '',
        route: name,
        ...properties,
      }),
    }),
  ]);
}

export function trackDependency(options: {
  name: string;
  url: string;
  method: string;
  durationMs: number;
  success: boolean;
  statusCode?: number;
  properties?: TelemetryProperties;
  measurements?: TelemetryMeasurements;
  requestId?: string;
}): void {
  if (!enabled) {
    return;
  }

  let target = options.url;
  try {
    target = new URL(options.url, getRuntimeWindow()?.location?.origin || 'http://localhost').host || options.url;
  } catch (_) {
    target = options.url;
  }

  schedule([
    buildEnvelope('RemoteDependencyData', {
      ver: 2,
      id: options.requestId || ensureSessionId(),
      name: options.name,
      data: options.url,
      target,
      duration: formatDuration(options.durationMs),
      success: options.success,
      resultCode: options.statusCode !== undefined ? String(options.statusCode) : undefined,
      type: 'Fetch',
      properties: buildCommonProperties(options.properties),
      measurements: sanitizeMeasurements({
        ...options.measurements,
        duration_ms: options.durationMs,
      }),
    }),
  ]);
}

export function trackException(error: Error, properties?: TelemetryProperties, measurements?: TelemetryMeasurements): void {
  if (!enabled) {
    return;
  }

  schedule([
    buildEnvelope('ExceptionData', {
      ver: 2,
      exceptions: [
        {
          typeName: error.name || 'Error',
          message: error.message || String(error),
          hasFullStack: Boolean(error.stack),
          stack: error.stack || '',
        },
      ],
      severityLevel: 3,
      properties: buildCommonProperties(properties),
      measurements: sanitizeMeasurements(measurements),
    }),
  ]);
}

export function buildTelemetryHeaders(headers?: HeadersInit): HeadersInit {
  const merged = new Headers(headers || {});
  merged.set('X-Prospektlab-Request-Id', typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`);
  merged.set('X-Prospektlab-Session-Id', ensureSessionId());
  return merged;
}

export function getTelemetryRequestId(headers: HeadersInit): string | null {
  if (headers instanceof Headers) {
    return headers.get('X-Prospektlab-Request-Id');
  }
  if (Array.isArray(headers)) {
    const entry = headers.find(([key]) => key.toLowerCase() === 'x-prospektlab-request-id');
    return entry ? entry[1] : null;
  }
  if (typeof headers === 'object' && headers) {
    const record = headers as Record<string, string>;
    return record['X-Prospektlab-Request-Id'] || record['x-prospektlab-request-id'] || null;
  }
  return null;
}

export function isTelemetryEnabled(): boolean {
  return enabled;
}
