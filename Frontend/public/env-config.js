(function () {
  var prodBackend = "https://wr7fle8bc1.execute-api.ap-south-1.amazonaws.com";
  var host = window.location.hostname || "";
  var canonicalHost = "prospektlab.com";
  var canonicalAliases = {
    "www.prospektlab.com": true,
    "d1pw8a1zc1b4q.cloudfront.net": true,
    "d1pw81azc1b4q.cloudfront.net": true,
    "dobiy4fdx7cb.cloudfront.net": true,
    "dobiy4fdxr7cb.cloudfront.net": true,
    "app.prospektlab.com": true
  };
  var isLocal = host === "localhost" || host === "127.0.0.1" || host === "::1";
  if (!isLocal && host && host !== canonicalHost && canonicalAliases[host]) {
    var canonicalUrl = window.location.protocol + "//" + canonicalHost + window.location.pathname + window.location.search + window.location.hash;
    window.location.replace(canonicalUrl);
    return;
  }
  var backend = isLocal ? "http://127.0.0.1:8000" : prodBackend;

  // Migration safety: recover older cached holdings into the manual snapshot key
  // so users moved across deployments/regions do not land on an empty dashboard.
  try {
    var manualKey = "prospektlab_manual_portfolio";
    var legacyKey = "prospektlab_portfolio";
    var hasManual = window.localStorage.getItem(manualKey);
    var legacyRaw = window.localStorage.getItem(legacyKey);
    if (!hasManual && legacyRaw) {
      var legacy = JSON.parse(legacyRaw);
      if (Array.isArray(legacy) && legacy.length > 0) {
        var migrated = legacy
          .map(function (item) {
            var symbol = String((item && item.symbol) || "").trim();
            var quantity = Number((item && (item.quantity != null ? item.quantity : item.qty)) || 0);
            var avgCost = Number((item && (item.avg_cost != null ? item.avg_cost : item.avgCost)) || 0);
            var current = Number((item && item.current) || avgCost || 0);
            if (!symbol || !(quantity > 0) || !(avgCost > 0)) return null;
            return {
              symbol: symbol,
              name: String((item && item.name) || symbol),
              quantity: quantity,
              avg_cost: avgCost,
              market_value: quantity * current,
              cost_basis: quantity * avgCost,
              kind: String((item && item.assetClass) || "").toLowerCase().includes("mutual") ? "mf" : "equity",
              sector: String((item && item.sector) || "General"),
              last_price: current
            };
          })
          .filter(function (row) { return !!row; });
        if (migrated.length > 0) {
          window.localStorage.setItem(manualKey, JSON.stringify(migrated));
        }
      }
    }
  } catch (_err) {
    // no-op: never block app boot on local cache migration
  }

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
