import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

// Custom metric to track true server errors (5xx)
const serverErrors = new Rate('server_errors');

export const options = {
  stages: [
    { duration: '30s', target: 20 }, // Ramp up to 20 virtual users
    { duration: '1m', target: 20 },  // Steady state at 20 users
    { duration: '30s', target: 0 },  // Ramp down to 0 users
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'], // 95% of requests must complete under 500ms
    server_errors: ['rate<0.01'],     // Unexpected 5xx errors must be under 1%
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export default function () {
  // 1. GET /health
  let resHealth = http.get(`${BASE_URL}/health`);
  serverErrors.add(resHealth.status >= 500);
  check(resHealth, {
    'health status is 200': (r) => r.status === 200,
    'health check is ok': (r) => r.json().status === 'ok',
  });
  sleep(1);

  // 2. GET /capabilities
  let resCaps = http.get(`${BASE_URL}/capabilities`);
  serverErrors.add(resCaps.status >= 500);
  check(resCaps, {
    'capabilities status is 200': (r) => r.status === 200,
    'capabilities has agent': (r) => r.json().agent !== undefined,
  });
  sleep(1);

  // 3. GET /config
  let resConfig = http.get(`${BASE_URL}/config`);
  serverErrors.add(resConfig.status >= 500);
  check(resConfig, {
    'config status is 200': (r) => r.status === 200,
  });
  sleep(1);

  // 4. POST /auth/login (Negative credentials to test performance & rate limiting)
  let authPayload = JSON.stringify({
    email: 'stress-test@example.com',
    password: 'wrongpassword123',
  });

  let authParams = {
    headers: {
      'Content-Type': 'application/json',
    },
  };

  let resLogin = http.post(`${BASE_URL}/auth/login`, authPayload, authParams);
  serverErrors.add(resLogin.status >= 500);
  check(resLogin, {
    'login returns 401 or 429': (r) => r.status === 401 || r.status === 429,
  });
  sleep(2);
}
