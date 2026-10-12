// services/api/lastcall_api/static/js/call.js

import { state } from './state.js';
import * as dom from './dom.js';
import { setStoredItem } from './storage.js';
import { showToast, scriptClass } from './ui.js';
import { updateShelfLock } from './lock.js';
import { renderResults } from './reading.js';
import { renderNextActionRow } from './buyers.js';

export function setStatus(text, type = '') {
  if (dom.statusText) dom.statusText.textContent = text;
  let chipClass = 'chip chip-slate';
  if (type === 'live') chipClass = 'chip chip-emerald';
  else if (type === 'busy') chipClass = 'chip chip-amber';
  else if (type === 'error') chipClass = 'chip chip-rose';
  if (dom.statusBadge) dom.statusBadge.className = 'status-badge ' + chipClass + ' ' + type;
}

export function appendMessage(speaker, text) {
  const msg = document.createElement('div');
  msg.className = 'transcript-bubble ' + (speaker === 'agent' ? 'agent' : 'buyer');

  const speakerSpan = document.createElement('div');
  speakerSpan.className = 'msg-speaker';
  speakerSpan.textContent = speaker === 'agent' ? 'AI Assistant (Mart)' : 'You (Buyer)';

  const textSpan = document.createElement('div');
  const sClass = scriptClass(text);
  if (sClass) textSpan.className = sClass;
  textSpan.textContent = text;

  msg.appendChild(speakerSpan);
  msg.appendChild(textSpan);
  dom.transcript.appendChild(msg);
  dom.transcript.scrollTop = dom.transcript.scrollHeight;
}

export function appendNotice(text) {
  const notice = document.createElement('div');
  notice.className = 'transcript-notice';
  notice.textContent = text;
  dom.transcript.appendChild(notice);
  dom.transcript.scrollTop = dom.transcript.scrollHeight;
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
    dom.callBuyerName.textContent = `${bName} (from Google Maps)`;

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
      dom.callFloorPrice.textContent = `floor Rs ${data.deal.floor} / ${dealU} (never told to the AI)`;
    } else {
      dom.callFloorPrice.textContent = 'None (donation)';
    }

    dom.callPickupWindow.textContent = (data.deal && data.deal.pickup_window) ? data.deal.pickup_window : 'Today';

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
    const summary = document.createElement('div');
    if (attempt.outcome === 'deal' || attempt.outcome === 'partial_deal') {
      if (attempt.step === 'donate' || attempt.agreed_price === 0) {
        summary.textContent = `Donated ${attempt.agreed_quantity || 0} ${batchData.unit || 'kg'}`;
      } else {
        const priceStr = attempt.agreed_price == null ? '—' : attempt.agreed_price;
        summary.textContent = `Deal agreed: ${attempt.agreed_quantity || 0} ${batchData.unit || 'kg'} @ Rs ${priceStr} / ${batchData.unit || 'kg'}`;
      }
    } else if (attempt.outcome === 'declined') {
      summary.textContent = 'Outcome: Declined by buyer';
    } else if (attempt.outcome === 'call_back') {
      summary.textContent = `Outcome: Call back ${attempt.callback_at ? 'at ' + attempt.callback_at : ''}`;
    } else if (attempt.outcome === 'no_answer') {
      summary.textContent = 'Outcome: No answer';
    } else if (attempt.outcome === 'do_not_call') {
      summary.textContent = 'Outcome: Buyer asked not to be called';
    } else {
      summary.textContent = `Outcome: ${(attempt.outcome || 'Completed').replace(/_/g, ' ')}`;
    }
    dom.resultContent.appendChild(summary);

    const stockInfo = document.createElement('div');
    stockInfo.className = 'call-stock-info';
    stockInfo.textContent = `Remaining batch stock: ${batchData.remaining_quantity} of ${batchData.total_quantity} ${batchData.unit || 'kg'}`;
    dom.resultContent.appendChild(stockInfo);
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
  btnRef.className = 'btn-secondary';
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
