// services/api/lastcall_api/static/js/call.js

import { state, martNow } from './state.js';
import * as dom from './dom.js';
import { setStoredItem } from './storage.js';
import { ACCESS_CODE_REFUSED, apiFetch, errorMessage, requireAccessCode, showAccessCodeError } from './api.js';
import { showToast, scriptClass, icon, initials, scrollToSection } from './ui.js';
import { updateShelfLock } from './lock.js';
import { renderResults } from './reading.js';
import { renderNextActionRow } from './buyers.js';
import { formatCallbackTime } from './format.js';
import { isPhoneMode, startPhoneCall } from './phone.js';

export function setStatus(text, type = '') {
  if (dom.statusText) dom.statusText.textContent = text;
  let chipClass = 'chip chip-slate';
  if (type === 'live') chipClass = 'chip chip-emerald';
  else if (type === 'busy') chipClass = 'chip chip-amber';
  else if (type === 'error') chipClass = 'chip chip-rose';
  if (dom.statusBadge) dom.statusBadge.className = 'status-badge ' + chipClass + ' ' + type;
}

export function appendMessage(speaker, text) {
  const isAgent = speaker === 'agent';
  const msg = document.createElement('div');
  msg.className = 'msg ' + (isAgent ? 'msg-agent' : 'msg-buyer');

  const label = document.createElement('div');
  label.className = 'msg-speaker';
  label.textContent = isAgent ? 'AI agent' : 'You';
  msg.appendChild(label);

  const bubble = document.createElement('div');
  const sClass = scriptClass(text);
  bubble.className = 'msg-bubble' + (sClass ? ' ' + sClass : '');
  bubble.dir = 'auto';
  bubble.textContent = text;
  msg.appendChild(bubble);

  dom.transcript.appendChild(msg);
  dom.transcript.scrollTop = dom.transcript.scrollHeight;
}

// Tool and connection notices in plain words (e.g. "Tool: verify_offer (counter)" → "Price check · counter")
const TOOL_LABELS = {
  verify_offer: 'Price check',
  confirm_deal: 'Deal confirmed',
  record_outcome: 'Outcome recorded',
  schedule_callback: 'Call-back scheduled',
  send_photo: 'Photo sent on WhatsApp'
};

export function appendNotice(text) {
  let display = text;
  const tool = /^Tool: (\w+)(?: \(([^)]*)\))?$/.exec(text || '');
  if (tool) {
    const label = TOOL_LABELS[tool[1]] || tool[1].replace(/_/g, ' ');
    display = tool[2] && tool[2] !== 'executing' ? `${label} · ${tool[2]}` : label;
  } else if (/^Call closed/.test(text || '')) {
    display = 'Call ended';
  }
  const notice = document.createElement('div');
  notice.className = 'transcript-notice' + (tool ? ' is-tool' : '');
  notice.textContent = display;
  dom.transcript.appendChild(notice);
  dom.transcript.scrollTop = dom.transcript.scrollHeight;
}

// A WhatsApp message the agent sent the buyer during the call (D62): an item photo or the deal confirmation
const WHATSAPP_LABELS = { photo: 'WhatsApp to buyer · photo', confirmation: 'WhatsApp to buyer · confirmation' };

export function appendWhatsApp(event) {
  const msg = document.createElement('div');
  msg.className = 'msg msg-agent msg-whatsapp';

  const label = document.createElement('div');
  label.className = 'msg-speaker';
  label.appendChild(icon('message'));
  label.append(WHATSAPP_LABELS[event.whatsapp] || 'WhatsApp to buyer');
  msg.appendChild(label);

  const bubble = document.createElement('div');
  bubble.className = 'wa-bubble';
  if (event.media_url && /^https?:\/\//.test(event.media_url)) {
    const img = document.createElement('img');
    img.className = 'wa-photo';
    img.alt = event.text || 'Photo of the produce';
    img.addEventListener('load', () => { dom.transcript.scrollTop = dom.transcript.scrollHeight; });
    img.addEventListener('error', () => img.remove());
    img.src = event.media_url;
    bubble.appendChild(img);
  }
  const text = document.createElement('div');
  text.className = 'wa-text';
  text.textContent = event.text || '';
  bubble.appendChild(text);
  msg.appendChild(bubble);

  dom.transcript.appendChild(msg);
  dom.transcript.scrollTop = dom.transcript.scrollHeight;
}

export function renderCallerAvatar(name) {
  if (dom.callerAvatar) dom.callerAvatar.textContent = initials(name);
}

export function startCallTimer() {
  state.callStartTime = Date.now();
  if (dom.callDuration) dom.callDuration.textContent = '00:00';
  if (state.callTimerInterval) clearInterval(state.callTimerInterval);
  state.callTimerInterval = setInterval(() => {
    const sec = Math.floor((Date.now() - state.callStartTime) / 1000);
    const m = String(Math.floor(sec / 60)).padStart(2, '0');
    const s = String(sec % 60).padStart(2, '0');
    if (dom.callDuration) dom.callDuration.textContent = `${m}:${s}`;
  }, 1000);
}

// The transcript's starting content (every node, as written in index.html), taken once when the module loads,
// so the page stays the only source of its text. Defensive: the module can load without the real page (tests).
const transcriptStart = [...(dom.transcript?.childNodes ?? [])].map(node => node.cloneNode(true));

// Puts the call section back to how the page starts: hidden, no caller, no transcript, no result.
// Used when the shelf's results are reset (a new inspection, New shelf, a branch change); never during a call.
export function resetCallPanel() {
  if (state.isCallInProgress) return;
  stopCallTimer();
  dom.voiceSection.style.display = 'none';
  dom.callBuyerName.textContent = '—';
  dom.callerAvatar.textContent = '';
  for (const el of [dom.callItemQty, dom.callOpeningQuote, dom.callFloorPrice, dom.callPickupWindow]) el.textContent = '—';
  if (dom.callDuration) dom.callDuration.textContent = '00:00';
  setStatus('Connecting…');
  dom.btnHangup.disabled = true;
  dom.transcript.replaceChildren(...transcriptStart.map(node => node.cloneNode(true)));  // hidden first: not announced
  dom.resultCard.style.display = 'none';
  dom.resultCard.classList.remove('visible');
  dom.resultContent.replaceChildren();
  dom.resultNextAction.replaceChildren();
}

export function stopCallTimer() {
  if (state.callTimerInterval) {
    clearInterval(state.callTimerInterval);
    state.callTimerInterval = null;
  }
}

export function triggerWaveformAnimation() {
  if (!dom.waveformBox) return;
  dom.waveformBox.classList.add('waveform-active');
  if (state.waveformTimer) clearTimeout(state.waveformTimer);
  state.waveformTimer = setTimeout(() => {
    if (dom.waveformBox) dom.waveformBox.classList.remove('waveform-active');
  }, 500);
}

export async function startCallForItem(itemKey, buyerId) {
  state.retryCount = 0;
  const code = requireAccessCode();
  if (!code) return;
  setStoredItem('lc_code', code);

  if (!state.currentInspection || !state.currentInspection.inspection_id) {
    showToast('Please run a shelf inspection first.', 'error');
    return;
  }

  const branchId = dom.branchSelect.value || null;
  let qty = null;
  if (state.quantityEdited[itemKey]) {
    const parsed = parseFloat(state.quantityInputs[itemKey]);
    qty = (!isNaN(parsed) && parsed > 0) ? parsed : null;
  }
  const staffChecked = !!state.staffCheckedMap[itemKey];

  state.isCallInProgress = true;
  // Who this call is with, from the start, so the Buyers list marks the right buyer (not an earlier call's);
  // the server's answer below confirms it, and fills it in when the server picks the buyer.
  // `hungUp` is set by Hang up: each step below checks it after waiting, so a call hung up while it is
  // still starting never goes on to the microphone or the agent.
  const call = { itemKey, batchId: null, callId: null, buyerId: buyerId || null, hungUp: false };
  state.currentActiveCall = call;
  updateShelfLock();
  renderResults(state.currentInspection, state.currentDisplayUrl);

  const liveSection = dom.voiceSection;
  if (liveSection) {
    liveSection.style.display = 'block';
    scrollToSection(liveSection);
  }

  dom.btnHangup.disabled = false;
  startCallTimer();
  setStatus('Starting…', 'busy');
  dom.transcript.replaceChildren();
  if (dom.resultCard) {
    dom.resultCard.style.display = 'none';
    dom.resultCard.classList.remove('visible');
  }

  try {
    const payload = {
      inspection_id: state.currentInspection.inspection_id,
      item_key: itemKey,
      branch_id: branchId,
      quantity: qty,
      staff_checked: staffChecked,
      buyer_id: buyerId || null
    };

    const res = await apiFetch('/demo/calls', { method: 'POST', json: payload });

    if (res.status === 401) {
      showAccessCodeError(ACCESS_CODE_REFUSED);
      throw new Error(ACCESS_CODE_REFUSED);  // the catch below ends the call that never started
    } else if (!res.ok) {
      throw new Error(await errorMessage(res, `Failed to create call (${res.status})`));
    }

    const data = await res.json();
    if (call.hungUp) return endCallBeforeConnect(call);
    Object.assign(call, {
      batchId: data.batch_id,
      callId: data.call_id,
      buyerId: data.buyer ? data.buyer.buyer_id : buyerId
    });
    renderResults(state.currentInspection, state.currentDisplayUrl);  // the Buyers list now marks the confirmed buyer

    // Populate Call info panel
    const bName = data.buyer ? data.buyer.name : 'Buyer';
    dom.callBuyerName.textContent = bName;
    renderCallerAvatar(bName);

    const itmName = data.deal ? data.deal.item : 'Produce';
    const dealQ = data.deal ? data.deal.quantity : (qty || '—');
    const dealU = data.deal ? data.deal.unit : 'kg';
    dom.callItemQty.textContent = `${itmName} · ${dealQ}\u00A0${dealU}`;

    if (data.deal && data.deal.opening != null) {
      dom.callOpeningQuote.textContent = `Rs\u00A0${data.deal.opening} / ${dealU}`;
    } else {
      dom.callOpeningQuote.textContent = 'Free donation';
    }

    if (data.deal && data.deal.floor != null) {
      dom.callFloorPrice.textContent = `Rs\u00A0${data.deal.floor} / ${dealU}`;
    } else {
      dom.callFloorPrice.textContent = 'None (donation)';
    }

    dom.callPickupWindow.textContent = (data.deal && data.deal.pickup_window) ? data.deal.pickup_window : 'Today';

    // Phone demo (Module 9): Twilio rings the presenter's SIM instead of using the microphone
    if (isPhoneMode()) {
      await startPhoneCall(data);
      return;
    }

    // Initialize AudioContext and microphone in order (24 kHz)
    state.audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    await state.audioCtx.audioWorklet.addModule('/static/capture-worklet.js');
    await state.audioCtx.audioWorklet.addModule('/static/playback-worklet.js');
    if (call.hungUp) return endCallBeforeConnect(call);

    state.playbackNode = new AudioWorkletNode(state.audioCtx, 'playback-worklet');
    state.playbackNode.connect(state.audioCtx.destination);

    state.micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    });
    if (call.hungUp) return endCallBeforeConnect(call);  // e.g. hung up while the browser asked for the microphone
    const micSource = state.audioCtx.createMediaStreamSource(state.micStream);
    state.captureNode = new AudioWorkletNode(state.audioCtx, 'capture-worklet');
    micSource.connect(state.captureNode);

    setStatus('Connecting audio…', 'busy');
    connectWebSocket(data.ws_url, data.token);

  } catch (err) {
    if (call.hungUp) return endCallBeforeConnect(call);  // the judge ended it; a refused microphone isn't an error then
    state.scoutErrorsMap[itemKey] = err.message;
    showToast(err.message, 'error');
    setStatus('Ready');
    dom.btnHangup.disabled = true;
    state.isCallInProgress = false;
    state.currentActiveCall = null;  // the call never started
    cleanupAudio();
    updateShelfLock();
    renderResults(state.currentInspection, state.currentDisplayUrl);
  }
}

export function connectWebSocket(wsUrl, token) {
  const call = state.currentActiveCall;
  state.ws = new WebSocket(wsUrl);
  state.ws.binaryType = 'arraybuffer';

  let speechEndTs = 0;
  let waitingForAgentAudio = false;
  let opened = false;

  state.ws.onopen = () => {
    opened = true;
    setStatus('Connecting…', 'busy');
    state.ws.send(JSON.stringify({ type: 'auth', token: token }));

    state.captureNode.port.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
          state.ws.send(event.data);
        }
      } else if (event.data && event.data.type === 'speech_end') {
        speechEndTs = performance.now();
        waitingForAgentAudio = true;
      }
    };
  };

  state.ws.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      triggerWaveformAnimation();
      if (waitingForAgentAudio && speechEndTs > 0) {
        const latMs = Math.round(performance.now() - speechEndTs);
        waitingForAgentAudio = false;
        speechEndTs = 0;
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
          state.ws.send(JSON.stringify({ type: 'latency', ms: latMs }));
        }
      }
      state.playbackNode.port.postMessage(event.data, [event.data]);
    } else {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'transcript') {
          if (data.speaker === 'agent') {
            setStatus('Live', 'live');
          }
          appendMessage(data.speaker, data.text);
        } else if (data.type === 'whatsapp') {
          appendWhatsApp(data);
        } else if (data.type === 'interrupted') {
          state.playbackNode.port.postMessage({ type: 'clear' });
          appendNotice('Interrupted');
        } else if (data.type === 'tool') {
          appendNotice(`Tool: ${data.name} (${data.decision || 'executing'})`);
        } else if (data.type === 'busy') {
          appendNotice('Server busy, retrying…');
          handleBusyRetry(wsUrl, token);
        }
      } catch (e) {
        console.warn('connectWebSocket message parse', e);
      }
    }
  };

  state.ws.onclose = async (event) => {
    // Hung up while the connection was still opening: the server never got the call, so there is no result
    if (!opened && call && call.hungUp) {
      endCallBeforeConnect(call);
      return;
    }
    if (event.code === 1013) {
      setStatus('Server busy');
      return;
    }

    cleanupAudio();
    dom.btnHangup.disabled = true;

    if (event.code === 4401 || event.code === 4409 || event.code === 4423 || (event.code >= 4000 && event.code < 5000)) {
      state.isCallInProgress = false;
      updateShelfLock();
      if (event.code === 4401) {
        setStatus('Access refused');
        showToast('This call was refused. Please start it again.', 'error');
      } else if (event.code === 4409) {
        setStatus('Session expired');
        showToast('This call session has expired. Please start the call again.', 'error');
      } else if (event.code === 4423) {
        setStatus('Another call is on');
        showToast('Another call is already running for this item.', 'error');
      } else {
        setStatus('Call failed');
        showToast(`The call closed unexpectedly (code ${event.code}). Please try again.`, 'error');
      }
      if (state.currentInspection) renderResults(state.currentInspection, state.currentDisplayUrl);
      return;
    }

    setStatus('Call ended');
    appendNotice(`Call closed (Code: ${event.code})`);

    if (state.currentActiveCall && state.currentActiveCall.batchId) {
      await pollBatchUntilCompleted(state.currentActiveCall.batchId, state.currentActiveCall.callId);
    } else {
      state.isCallInProgress = false;
      updateShelfLock();
      if (state.currentInspection) renderResults(state.currentInspection, state.currentDisplayUrl);
    }
  };

  state.ws.onerror = () => {
    cleanupAudio();
    setStatus('Connection lost');
  };
}

export async function pollBatchUntilCompleted(batchId, callId) {
  setStatus('Saving the result…', 'busy');
  let attemptFound = false;
  let batchData = null;

  for (let i = 0; i < 8; i++) {
    await new Promise(r => setTimeout(r, 1000));
    try {
      const res = await apiFetch(`/demo/batches/${encodeURIComponent(batchId)}`);
      if (res.ok) {
        batchData = await res.json();
        const att = (batchData.attempts || []).find(a => a.call_id === callId);
        if (att && att.call_status === 'completed') {
          attemptFound = true;
          break;
        }
      }
    } catch (e) {
      console.warn('pollBatchUntilCompleted', e);
    }
  }

  state.isCallInProgress = false;
  updateShelfLock();
  setStatus('Call ended');

  if (state.currentActiveCall && state.currentActiveCall.itemKey) {
    if (batchData) {
      state.currentBatchesMap[state.currentActiveCall.itemKey] = batchData;
    }
    renderResults(state.currentInspection, state.currentDisplayUrl);
  }

  if (attemptFound && batchData) {
    renderCallResult(batchData, callId);
  } else {
    renderCallPendingResult(batchId, callId);
  }
}

export function renderCallResult(batchData, callId) {
  dom.resultCard.style.display = 'block';
  dom.resultCard.classList.add('visible');
  dom.resultContent.replaceChildren();
  dom.resultNextAction.replaceChildren();

  const attempt = (batchData.attempts || []).find(a => a.call_id === callId) ||
    (batchData.attempts && batchData.attempts[batchData.attempts.length - 1]);

  if (attempt) {
    const unit = batchData.unit || 'kg';
    const isDeal = attempt.outcome === 'deal' || attempt.outcome === 'partial_deal';
    let title;
    if (isDeal) {
      title = (attempt.step === 'donate' || attempt.agreed_price === 0)
        ? `Donated ${attempt.agreed_quantity || 0}\u00A0${unit}`
        : `Deal agreed · ${attempt.agreed_quantity || 0}\u00A0${unit} at Rs\u00A0${attempt.agreed_price == null ? '—' : attempt.agreed_price} / ${unit}`;
    } else {
      const labels = {
        declined: 'Buyer declined',
        call_back: 'Buyer asked for a call back',
        no_answer: 'No answer',
        do_not_call: 'Buyer asked not to be called again',
        wants_photo: 'Buyer wants a photo first',
        wants_manager: 'Buyer wants to speak to the manager'
      };
      title = attempt.dropped
        ? 'Ended early'
        : labels[attempt.outcome] || (attempt.outcome || 'Call finished').replace(/_/g, ' ');
    }

    const row = document.createElement('div');
    row.className = 'result-row';
    const badge = document.createElement('div');
    badge.className = 'result-icon ' + (isDeal ? 'is-deal' : 'is-other');
    badge.appendChild(icon(isDeal ? 'check' : 'x'));
    row.appendChild(badge);

    const text = document.createElement('div');
    const t = document.createElement('div');
    t.className = 'result-title';
    t.textContent = title;
    text.appendChild(t);
    const sub = document.createElement('div');
    sub.className = 'result-sub';
    const parts = [`${batchData.remaining_quantity} of ${batchData.total_quantity}\u00A0${unit} left`];
    if (attempt.outcome === 'call_back' && attempt.callback_at && !attempt.dropped) {
      parts.unshift(`Call back ${formatCallbackTime(attempt.callback_at, martNow())}`);
    }
    if (isDeal && attempt.pickup_time) {
      parts.unshift(`Pickup ${new Date(attempt.pickup_time).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Karachi' })}`);
    }
    sub.textContent = parts.join(' · ');
    text.appendChild(sub);
    row.appendChild(text);
    dom.resultContent.appendChild(row);
  }

  const scout = state.currentActiveCall ? state.scoutResultsMap[state.currentActiveCall.itemKey] : null;
  const buyers = (scout && scout.buyers) ? scout.buyers : [];
  renderNextActionRow(dom.resultNextAction, batchData, state.currentActiveCall ? state.currentActiveCall.itemKey : null, buyers, true);
}

export function renderCallPendingResult(batchId, callId) {
  dom.resultCard.style.display = 'block';
  dom.resultCard.classList.add('visible');
  dom.resultContent.textContent = 'Saving the call result…';
  dom.resultNextAction.replaceChildren();

  const btnRef = document.createElement('button');
  btnRef.type = 'button';
  btnRef.className = 'btn-ghost btn-sm';
  btnRef.textContent = 'Refresh';
  btnRef.addEventListener('click', () => {
    pollBatchUntilCompleted(batchId, callId);
  });
  dom.resultNextAction.appendChild(btnRef);
}

export function handleBusyRetry(wsUrl, token) {
  if (state.retryCount < 3) {
    state.retryCount++;
    const call = state.currentActiveCall;
    setTimeout(() => {
      if (call && call.hungUp) {
        endCallBeforeConnect(call);  // hung up while waiting for a free line: don't dial again
        return;
      }
      connectWebSocket(wsUrl, token);
    }, 3000);
  } else {
    showToast('All call lines are busy. Please try again in a minute.', 'error');
    cleanupAudio();
    state.isCallInProgress = false;
    dom.btnHangup.disabled = true;
    setStatus('Server busy');
    updateShelfLock();
    if (state.currentInspection) {
      renderResults(state.currentInspection, state.currentDisplayUrl);
    }
  }
}

// Ends the call at whatever stage it has reached. Live: the server is told and saves the result, which
// the socket's close then shows. Still opening: the connection is dropped and its close ends the call here.
// Still starting (no socket yet) or waiting to retry a busy line: the start stops at its next step.
export function hangup() {
  const call = state.currentActiveCall;
  if (call) call.hungUp = true;
  const ws = state.ws;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'hangup' }));
    ws.close();
  } else if (ws && ws.readyState === WebSocket.CONNECTING) {
    ws.close();
  }
  cleanupAudio();
  setStatus('Call ended');
  dom.btnHangup.disabled = true;
}

// A call hung up before it reached the agent. Nothing was said, so there is no result to wait for: the
// server's record stays "pending", which doesn't use up this buyer, and they can be called again at once.
function endCallBeforeConnect(call) {
  if (state.currentActiveCall !== call) return;  // already ended, or a newer call has started
  cleanupAudio();
  state.isCallInProgress = false;
  state.currentActiveCall = null;
  dom.btnHangup.disabled = true;
  setStatus('Call ended');
  appendNotice('You hung up before the call connected.');
  updateShelfLock();
  if (state.currentInspection) renderResults(state.currentInspection, state.currentDisplayUrl);
}

export function cleanupAudio() {
  if (state.micStream) {
    state.micStream.getTracks().forEach(t => t.stop());
    state.micStream = null;
  }
  if (state.audioCtx) {
    state.audioCtx.close().catch((e) => {
      console.warn('cleanupAudio', e);
    });
    state.audioCtx = null;
  }
  stopCallTimer();
  if (dom.waveformBox) dom.waveformBox.classList.remove('waveform-active');
}
