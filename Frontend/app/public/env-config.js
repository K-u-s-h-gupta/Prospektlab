(function () {
  var prodBackend = "https://pp2nutjt0l.execute-api.us-east-1.amazonaws.com";
  var host = window.location.hostname || "";
  var isLocal = host === "localhost" || host === "127.0.0.1" || host === "::1";
  var backend = isLocal ? "http://127.0.0.1:8000" : prodBackend;
  window.__BACKEND_URL = backend;
  window.__CONFIG__ = {
    apiBase: backend,
    environment: isLocal ? "local" : "production"
  };
})();
