// services/api/lastcall_api/static/js/call.js

import { state } from './state.js';
import * as dom from './dom.js';
import { setStoredItem } from './storage.js';
import { showToast, scriptClass, icon, initials } from './ui.js';
import { updateShelfLock } from './lock.js';
import { renderResults } from './reading.js';
import { renderNextActionRow } from './buyers.js';
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
  const code = dom.inspectAccessCodeEl.value.trim();
  if (!code) {
    showToast('Please enter your Demo Access Code first.', 'error');
    dom.inspectAccessCodeEl.focus();
    return;
  }
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
  updateShelfLock();
  renderResults(state.currentInspection, state.currentDisplayUrl);

  const liveSection = dom.voiceSection;
  if (liveSection) {
    liveSection.style.display = 'block';
    liveSection.scrollIntoView({ behavior: 'smooth' });
  }

  dom.btnHangup.disabled = false;
  startCallTimer();
  setStatus('Starting session...', 'busy');
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

    const res = await fetch('/demo/calls', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Demo-Access-Code': code
      },
      body: JSON.stringify(payload)
    });

    if (res.status === 401) {
      throw new Error('Invalid access code.');
    } else if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || errData.error || `Failed to create call (${res.status})`);
    }

    const data = await res.json();
    state.currentActiveCall = {
      itemKey: itemKey,
      batchId: data.batch_id,
      callId: data.call_id,
      buyerId: data.buyer ? data.buyer.buyer_id : buyerId
    };

    // Populate Call info panel
    const bName = data.buyer ? data.buyer.name : 'Buyer';
    dom.callBuyerName.textContent = bName;
    renderCallerAvatar(bName);

    const itmName = data.deal ? data.deal.item : 'Produce';
    const dealQ = data.deal ? data.deal.quantity : (qty || '—');
    const dealU = data.deal ? data.deal.unit : 'kg';
    dom.callItemQty.textContent = `${itmName} · ${dealQ} ${dealU}`;

    if (data.deal && data.deal.opening != null) {
      dom.callOpeningQuote.textContent = `Rs ${data.deal.opening} / ${dealU}`;
    } else {
      dom.callOpeningQuote.textContent = 'Free donation';
    }

    if (data.deal && data.deal.floor != null) {
      dom.callFloorPrice.textContent = `Rs ${data.deal.floor} / ${dealU}`;
    } else {
      dom.callFloorPrice.textContent = 'None (donation)';
    }

    dom.callPickupWindow.textContent = (data.deal && data.deal.pickup_window) ? data.deal.pickup_window : 'Today';

    // Phone demo (Module 9): Twilio rings the presenter's SIM instead of using the microphone
    if (isPhoneMode()) {
      await startPhoneCall(data, code);
      return;
    }

    // Initialize AudioContext and microphone in order (24 kHz)
    state.audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    await state.audioCtx.audioWorklet.addModule('/static/capture-worklet.js');
    await state.audioCtx.audioWorklet.addModule('/static/playback-worklet.js');

    state.playbackNode = new AudioWorkletNode(state.audioCtx, 'playback-worklet');
    state.playbackNode.connect(state.audioCtx.destination);

    state.micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    });
    const micSource = state.audioCtx.createMediaStreamSource(state.micStream);
    state.captureNode = new AudioWorkletNode(state.audioCtx, 'capture-worklet');
    micSource.connect(state.captureNode);

    setStatus('Connecting audio...', 'busy');
    connectWebSocket(data.ws_url, data.token);

  } catch (err) {
    state.scoutErrorsMap[itemKey] = err.message;
    showToast(err.message, 'error');
    setStatus('Ready');
    dom.btnHangup.disabled = true;
    state.isCallInProgress = false;
    cleanupAudio();
    updateShelfLock();
    renderResults(state.currentInspection, state.currentDisplayUrl);
  }
}

export function connectWebSocket(wsUrl, token) {
  state.ws = new WebSocket(wsUrl);
  state.ws.binaryType = 'arraybuffer';

  let speechEndTs = 0;
  let waitingForAgentAudio = false;

  state.ws.onopen = () => {
    setStatus('Authenticating...', 'busy');
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
            setStatus('Live Call', 'live');
          }
          appendMessage(data.speaker, data.text);
        } else if (data.type === 'interrupted') {
          state.playbackNode.port.postMessage({ type: 'clear' });
          appendNotice('Interrupted');
        } else if (data.type === 'tool') {
          appendNotice(`Tool: ${data.name} (${data.decision || 'executing'})`);
        } else if (data.type === 'busy') {
          appendNotice('Server capacity reached. Retrying...');
          handleBusyRetry(wsUrl, token);
        }
      } catch (e) {
        console.warn('connectWebSocket message parse', e);
      }
    }
  };

  state.ws.onclose = async (event) => {
    if (event.code === 1013) {
      setStatus('Server Busy');
      return;
    }

    cleanupAudio();
    dom.btnHangup.disabled = true;

    if (event.code === 4401 || event.code === 4409 || event.code === 4423 || (event.code >= 4000 && event.code < 5000)) {
      state.isCallInProgress = false;
      updateShelfLock();
      if (event.code === 4401) {
        setStatus('Auth Failed');
        showToast('WebSocket Auth failed (Code 4401)', 'error');
      } else if (event.code === 4409) {
        setStatus('Token Expired / Reused');
        showToast('Session token already used or expired (Code 4409)', 'error');
      } else if (event.code === 4423) {
        setStatus('Batch Locked');
        showToast('Call already in progress on this batch (Code 4423)', 'error');
      } else {
        setStatus('Call Failed');
        showToast(`Call closed with error code ${event.code}`, 'error');
      }
      if (state.currentInspection) renderResults(state.currentInspection, state.currentDisplayUrl);
      return;
    }

    setStatus('Call Ended');
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
    setStatus('Connection Error');
  };
}

export async function pollBatchUntilCompleted(batchId, callId) {
  const code = dom.inspectAccessCodeEl.value.trim();
  setStatus('Saving call result...', 'busy');
  let attemptFound = false;
  let batchData = null;

  for (let i = 0; i < 8; i++) {
    await new Promise(r => setTimeout(r, 1000));
    try {
      const res = await fetch(`/demo/batches/${encodeURIComponent(batchId)}`, {
        headers: code ? { 'X-Demo-Access-Code': code } : {}
      });
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
  setStatus('Call Ended');

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
        ? `Donated ${attempt.agreed_quantity || 0} ${unit}`
        : `Deal agreed · ${attempt.agreed_quantity || 0} ${unit} at Rs ${attempt.agreed_price == null ? '—' : attempt.agreed_price} / ${unit}`;
    } else {
      const labels = {
        declined: 'Buyer declined',
        call_back: 'Buyer asked for a call back',
        no_answer: 'No answer',
        do_not_call: 'Buyer asked not to be called again',
        wants_photo: 'Buyer wants a photo first',
        wants_manager: 'Buyer wants to speak to the manager'
      };
      title = labels[attempt.outcome] || (attempt.outcome || 'Call finished').replace(/_/g, ' ');
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
    const parts = [`${batchData.remaining_quantity} of ${batchData.total_quantity} ${unit} left`];
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
    setTimeout(() => {
      connectWebSocket(wsUrl, token);
    }, 3000);
  } else {
    showToast('Server is currently at maximum concurrency. Please try again later.', 'error');
    cleanupAudio();
    state.isCallInProgress = false;
    dom.btnHangup.disabled = true;
    setStatus('Server Busy');
    updateShelfLock();
    if (state.currentInspection) {
      renderResults(state.currentInspection, state.currentDisplayUrl);
    }
  }
}

export function hangup() {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: 'hangup' }));
    state.ws.close();
  }
  cleanupAudio();
  setStatus('Call Ended');
  dom.btnHangup.disabled = true;
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
