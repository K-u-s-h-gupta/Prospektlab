(function () {
  var prodBackend = "https://pp2nutjt0l.execute-api.us-east-1.amazonaws.com";
  var host = window.location.hostname || "";
  var isLocal = host === "localhost" || host === "127.0.0.1" || host === "::1";
  var backend = isLocal ? "http://127.0.0.1:8000" : prodBackend;
  window.__BACKEND_URL = backend;
  window.__CONFIG__ = {
    apiBase: backend,
    environment: isLocal ? "local" : "production",
    telemetry: {
      enabled: true,
      connectionString: "InstrumentationKey=b4797745-6b7f-4d72-894f-768bdc808d3d;IngestionEndpoint=https://centralindia-0.in.applicationinsights.azure.com/;LiveEndpoint=https://centralindia.livediagnostics.monitor.azure.com/;ApplicationId=980e7ddb-6ef5-46e2-b7ae-bb833f3fc8c8",
      roleName: "prospektlab-frontend",
      cloudRoleInstance: isLocal ? "local-browser" : "browser"
    }
  };
})();
