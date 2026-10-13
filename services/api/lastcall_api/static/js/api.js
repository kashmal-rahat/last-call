// services/api/lastcall_api/static/js/api.js
//
// One way to call the api: the judge's access code on every request, JSON bodies,
// and the server's own explanation (FastAPI `detail`) when a request is refused.

import * as dom from './dom.js';
import { showToast } from './ui.js';

export function accessCode() {
  return dom.inspectAccessCodeEl ? dom.inspectAccessCodeEl.value.trim() : '';
}

// The access code, or null after asking the judge to enter it.
export function requireAccessCode() {
  const code = accessCode();
  if (!code) {
    showToast('Please enter your Demo Access Code first.', 'error');
    if (dom.inspectAccessCodeEl) dom.inspectAccessCodeEl.focus();
    return null;
  }
  return code;
}

// fetch() with the access code; `json` is sent as a JSON body, `form` as multipart form data.
export function apiFetch(path, { method = 'GET', json, form } = {}) {
  const headers = {};
  const code = accessCode();
  if (code) headers['X-Demo-Access-Code'] = code;
  let body;
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(json);
  } else if (form !== undefined) {
    body = form;
  }
  return fetch(path, { method, headers, body });
}

// The server's explanation for a refused request, or `fallback`.
export async function errorMessage(res, fallback) {
  const data = await res.json().catch(() => ({}));
  return (typeof data.detail === 'string' && data.detail.trim()) ? data.detail.trim() : fallback;
}
