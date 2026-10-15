// services/api/lastcall_api/static/js/api.js
//
// One way to call the api: the judge's access code on every request, JSON bodies,
// and the server's own explanation (FastAPI `detail`) when a request is refused.

import * as dom from './dom.js';
import { showToast } from './ui.js';

export function accessCode() {
  return dom.inspectAccessCodeEl ? dom.inspectAccessCodeEl.value.trim() : '';
}

const HEADER_CLEARANCE_PX = 80;  // the sticky header and the gap under it (sections' scroll-margin-top)

export const ACCESS_CODE_MISSING = 'Enter the access code. You’ll find it in our submission deck.';
export const ACCESS_CODE_REFUSED = "This access code isn't right. You'll find it in our submission deck.";

// A problem with the code is shown at the code field, where it is fixed, not by the button that was
// clicked (which may be a screen away): the field turns red with the reason under it, comes into view
// if it isn't, and takes focus with its text selected, so typing replaces it. Typing clears the error.
export function showAccessCodeError(message) {
  const input = dom.inspectAccessCodeEl;
  if (!input || !dom.accessCodeError) {
    showToast(message, 'error');
    return;
  }
  dom.accessCodeError.textContent = message;
  dom.accessCodeError.hidden = false;
  input.setAttribute('aria-invalid', 'true');
  const box = input.getBoundingClientRect();
  if (box.top < HEADER_CLEARANCE_PX || box.bottom > window.innerHeight) {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    input.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
  }
  input.focus({ preventScroll: true });
  input.select();
}

export function clearAccessCodeError() {
  if (!dom.inspectAccessCodeEl || !dom.accessCodeError) return;
  dom.inspectAccessCodeEl.removeAttribute('aria-invalid');
  dom.accessCodeError.hidden = true;
  dom.accessCodeError.textContent = '';
}

// The access code, or null after asking the judge to enter it.
export function requireAccessCode() {
  const code = accessCode();
  if (!code) {
    showAccessCodeError(ACCESS_CODE_MISSING);
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
