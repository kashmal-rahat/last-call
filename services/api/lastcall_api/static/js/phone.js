// services/api/lastcall_api/static/js/phone.js
//
// Phone demo (Module 9): instead of the browser call, Twilio rings the presenter's SIM.
// Shown only with ?phone=1 while the server has PHONE_DEMO_ENABLED=true; otherwise this
// module does nothing and the page is exactly the judges' page.

import { state } from './state.js';
import * as dom from './dom.js';
import { updateShelfLock } from './lock.js';
import { renderResults } from './reading.js';
import {
  setStatus,
  appendMessage,
  appendNotice,
  appendWhatsApp,
  startCallTimer,
  stopCallTimer,
  triggerWaveformAnimation,
  pollBatchUntilCompleted
} from './call.js';

const POLL_MS = 1000;
const ANSWER_LIMIT_MS = 75000;      // Twilio rings for 30 s; allow for set-up and the AI greeting
const CALL_LIMIT_MS = 7 * 60 * 1000; // the agent ends calls by MAX_CALL_SECONDS (300 s)

let enabled = false;
let defaultCallerSub = '';

export function isPhoneMode() {
  return enabled && !!dom.phoneModeToggle && dom.phoneModeToggle.checked;
}

export async function initPhoneDemo() {
  if (!dom.phoneModeBox || !dom.phoneModeToggle) return;
  if (new URLSearchParams(window.location.search).get('phone') !== '1') return;
  try {
    const res = await fetch('/demo/phone/config');
    if (!res.ok) return; // 404 = switched off on the server
    enabled = !!(await res.json()).enabled;
  } catch (e) {
    console.warn('initPhoneDemo', e);
    return;
  }
  if (!enabled) return;
  defaultCallerSub = dom.callerSub ? dom.callerSub.textContent : '';
  dom.phoneModeBox.hidden = false;
  dom.phoneModeToggle.addEventListener('change', () => {
    if (!dom.phoneModeToggle.checked && dom.callerSub) dom.callerSub.textContent = defaultCallerSub;
  });
}

// Called by startCallForItem after /demo/calls; a throw here is handled by its catch.
export async function startPhoneCall(data, code) {
  dom.btnHangup.disabled = true; // the call is ended on the phone
  if (dom.callerSub) dom.callerSub.textContent = 'Ringing your phone through Twilio · the AI speaks Urdu';
  setStatus('Ringing your phone…', 'busy');

  const res = await fetch('/demo/phone/dial', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Demo-Access-Code': code },
    body: JSON.stringify({ call_id: data.call_id, token: data.token })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Could not ring the phone (${res.status})`);
  }

  appendNotice('Ringing your phone…');
  followPhoneCall(data.call_id, data.batch_id, code);
}

async function followPhoneCall(callId, batchId, code) {
  const shown = new Set();
  const started = Date.now();
  let answered = false;

  while (true) {
    await new Promise(r => setTimeout(r, POLL_MS));
    let d = null;
    try {
      const res = await fetch(`/demo/phone/calls/${encodeURIComponent(callId)}`, {
        headers: { 'X-Demo-Access-Code': code }
      });
      if (res.ok) d = await res.json();
    } catch (e) {
      console.warn('followPhoneCall', e);
    }

    if (d) {
      if (!answered && d.status !== 'pending') {
        answered = true;
        if (dom.callerSub) dom.callerSub.textContent = 'On your phone through Twilio · the AI speaks Urdu';
        startCallTimer();
        setStatus('Live Call', 'live');
        appendNotice('Call answered');
      }
      for (const line of d.lines || []) {
        if (shown.has(line.i)) continue;
        shown.add(line.i);
        if (line.kind === 'whatsapp') {
          appendWhatsApp(line);
          continue;
        }
        appendMessage(line.speaker, line.text);
        if (line.speaker === 'agent') triggerWaveformAnimation();
      }
      if (d.status === 'completed') break;
    }

    const elapsed = Date.now() - started;
    if (!answered && elapsed > ANSWER_LIMIT_MS) {
      endUnanswered();
      return;
    }
    if (elapsed > CALL_LIMIT_MS) break;
  }

  stopCallTimer();
  appendNotice('Call ended');
  await pollBatchUntilCompleted(batchId, callId);
}

function endUnanswered() {
  stopCallTimer();
  setStatus('No answer', 'error');
  appendNotice('The phone was not answered.');
  state.isCallInProgress = false;
  updateShelfLock();
  if (state.currentInspection) renderResults(state.currentInspection, state.currentDisplayUrl);
}
