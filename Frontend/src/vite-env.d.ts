export {};

declare global {
  interface Window {
    __BACKEND_URL?: string;
    __WS_BASE_URL?: string;
    __MARKET_DATA_WS_URL?: string;
    __CONFIG__?: {
      apiBase?: string;
      webSocketBase?: string;
      marketDataWebSocketUrl?: string;
      environment?: string;
      telemetry?: {
        enabled?: boolean;
        connectionString?: string;
        roleName?: string;
        cloudRoleInstance?: string;
      };
    };
  }
}