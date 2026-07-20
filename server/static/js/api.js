// Thin fetch wrappers over the W1 JSON API. Long EV calls stay synchronous
// server-side; callers render a computing state before awaiting these.

class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

async function request(path, options) {
  const response = await fetch(path, options);
  let body = null;
  try {
    body = await response.json();
  } catch {
    // fall through: non-JSON error body
  }
  if (!response.ok) {
    const detail = body && body.detail ? JSON.stringify(body.detail).replaceAll('"', '') : `HTTP ${response.status}`;
    throw new ApiError(response.status, detail);
  }
  return body;
}

export function post(path, payload) {
  return request(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function get(path) {
  return request(path);
}

export { ApiError };

const toast = document.getElementById('toast');
let toastTimer = null;

export function showError(error) {
  toast.textContent = error && error.message ? error.message : String(error);
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
}

export function randomSeed() {
  return 1 + Math.floor(Math.random() * 999999);
}
