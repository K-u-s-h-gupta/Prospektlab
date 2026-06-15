export {};

declare global {
  interface Window {
    __BACKEND_URL?: string;
    __CONFIG__?: {
      apiBase?: string;
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
