// services/api/lastcall_api/static/js/buyers.js

import { state } from './state.js';
import * as dom from './dom.js';
import { apiFetch, errorMessage, requireAccessCode } from './api.js';
import { getFindBuyersLabel, getNextStepTargetLabel } from './format.js';
import { icon, showToast } from './ui.js';
import { batchIdFor, loadBatchesForBranch } from './lock.js';
import { renderResults } from './reading.js';
import { startCallForItem } from './call.js';

export async function fetchScoutBuyers(itemKey, refresh = false) {
  if (!state.currentInspection || !state.currentInspection.inspection_id) return;
  if (!requireAccessCode()) return;
  const branchId = dom.branchSelect.value;
  if (!branchId) return;

  const currentCounter = (state.scoutRequestCounters[itemKey] || 0) + 1;
  state.scoutRequestCounters[itemKey] = currentCounter;
  state.scoutLoadingMap[itemKey] = true;
  state.scoutErrorsMap[itemKey] = null;
  renderResults(state.currentInspection, state.currentDisplayUrl);

  const payload = {
    inspection_id: state.currentInspection.inspection_id,
    item_key: itemKey,
    branch_id: branchId,
    refresh: refresh
  };

  try {
    const res = await apiFetch('/demo/scout', { method: 'POST', json: payload });

    if (state.scoutRequestCounters[itemKey] !== currentCounter) return;

    if (res.ok) {
      const data = await res.json();
      state.scoutResultsMap[itemKey] = data;
      state.scoutErrorsMap[itemKey] = null;
      const batchId = batchIdFor(itemKey);
      if (batchId && state.currentBatchesMap[itemKey]) {
        try {
          const bRes = await apiFetch(`/demo/batches/${encodeURIComponent(batchId)}`);
          if (bRes.ok) {
            state.currentBatchesMap[itemKey] = await bRes.json();
          }
        } catch (e) {
          console.warn('fetchScoutBuyers batch refresh', e);
        }
      }
    } else {
      state.scoutResultsMap[itemKey] = null;
      state.scoutErrorsMap[itemKey] = await errorMessage(res, 'Buyer search failed, please try again.');
    }
  } catch (err) {
    if (state.scoutRequestCounters[itemKey] !== currentCounter) return;
    state.scoutResultsMap[itemKey] = null;
    state.scoutErrorsMap[itemKey] = err.message || 'Buyer search failed, please try again.';
  } finally {
    if (state.scoutRequestCounters[itemKey] === currentCounter) {
      state.scoutLoadingMap[itemKey] = false;
      renderResults(state.currentInspection, state.currentDisplayUrl);
    }
  }
}

export function renderNextActionRow(container, batch, itemKey, buyers = [], showCallButton = false) {
  container.replaceChildren();

  if (batch && batch.next_action) {
    const act = batch.next_action;
    if (act.kind === 'call') {
      const rank = act.buyer_rank || ((batch.attempts ? batch.attempts.length : 0) + 1);
      const targetB = buyers.find(x => x.rank === rank) || buyers[rank - 1];
      const bName = targetB ? targetB.name : '';
      if (showCallButton) {
        const btnCall = document.createElement('button');
        btnCall.type = 'button';
        btnCall.className = 'btn-ai';
        btnCall.textContent = `Next buyer · #${rank}${bName ? ' ' + bName : ''}`;
        btnCall.disabled = state.isCallInProgress;
        const targetBId = targetB ? targetB.buyer_id : null;
        btnCall.addEventListener('click', () => {
          startCallForItem(itemKey, targetBId);
        });
        container.appendChild(btnCall);
      }
      // In the Buyers section the highlighted buyer card carries the call button, so nothing is shown here.
    } else if (act.kind === 'next_step') {
      const btnStep = document.createElement('button');
      btnStep.type = 'button';
      btnStep.className = 'btn-secondary';
      const label = getNextStepTargetLabel(batch);
      btnStep.textContent = `Next step: find ${label}`;
      btnStep.disabled = state.isCallInProgress;
      btnStep.addEventListener('click', () => {
        advanceBatchStep(batch.batch_id, itemKey);
      });
      container.appendChild(btnStep);
    } else if (act.kind === 'sold') {
      const chip = document.createElement('span');
      chip.className = 'chip chip-emerald';
      chip.textContent = 'All stock placed ✓';
      container.appendChild(chip);
    } else if (act.kind === 'compost_approval') {
      const chip = document.createElement('span');
      chip.className = 'chip chip-rose';
      chip.textContent = 'Compost: needs manager approval';
      container.appendChild(chip);
    } else if (act.kind === 'no_buyer') {
      const chip = document.createElement('span');
      chip.className = 'chip chip-slate';
      chip.textContent = 'No more buyers nearby';
      container.appendChild(chip);
    } else if (act.kind === 'needs_search') {
      const btnSearch = document.createElement('button');
      btnSearch.type = 'button';
      btnSearch.className = 'btn-secondary';
      btnSearch.textContent = 'Search again';
      btnSearch.disabled = state.isCallInProgress;
      btnSearch.addEventListener('click', () => {
        fetchScoutBuyers(itemKey, true);
      });
      container.appendChild(btnSearch);
    } else if (act.kind === 'busy') {
      const chip = document.createElement('span');
      chip.className = 'chip chip-amber';
      chip.textContent = 'Call in progress…';
      const btnRef = document.createElement('button');
      btnRef.type = 'button';
      btnRef.className = 'btn-secondary';
      btnRef.textContent = 'Refresh';
      btnRef.addEventListener('click', () => {
        loadBatchesForBranch();
      });
      container.appendChild(chip);
      container.appendChild(btnRef);
    }
  } else if (buyers && buyers.length > 0) {
    if (showCallButton) {
      const btnCall = document.createElement('button');
      btnCall.type = 'button';
      btnCall.className = 'btn-ai';
      btnCall.textContent = `Next buyer · #1 ${buyers[0].name}`;
      btnCall.disabled = state.isCallInProgress;
      btnCall.addEventListener('click', () => {
        startCallForItem(itemKey, buyers[0].buyer_id);
      });
      container.appendChild(btnCall);
    }
  }
}

export async function advanceBatchStep(batchId, itemKey) {
  if (!requireAccessCode()) return;
  try {
    const res = await apiFetch(`/demo/batches/${encodeURIComponent(batchId)}/next-step`, { method: 'POST' });
    if (res.ok) {
      const updated = await res.json();
      state.currentBatchesMap[itemKey] = updated;
      await fetchScoutBuyers(itemKey, false);
    } else {
      showToast(await errorMessage(res, 'Failed to advance step'), 'error');
    }
  } catch (e) {
    showToast(e.message || 'Failed to advance step', 'error');
  }
}

export function renderActiveBuyers() {
  if (!state.currentInspection || !state.activeItemKey || !state.currentLadderResult) {
    dom.sectionBuyers.style.display = 'none';
    return;
  }

  const decision = state.currentLadderResult.decisions
    ? state.currentLadderResult.decisions.find(d => d.item_key === state.activeItemKey)
    : null;

  if (!decision || !['bulk_sale', 'donate', 'animal_feed'].includes(decision.step)) {
    dom.sectionBuyers.style.display = 'none';
    return;
  }

  dom.sectionBuyers.style.display = 'block';

  const batch = state.currentBatchesMap[state.activeItemKey];
  const effectiveStep = (batch && batch.current_step) || decision.step;
  const branchName = dom.branchSelect.options[dom.branchSelect.selectedIndex]?.textContent.split('(')[0].trim() || 'Johar Town';

  dom.btnFindBuyers.textContent = getFindBuyersLabel(effectiveStep);
  const isCardLoading = !!state.scoutLoadingMap[state.activeItemKey];
  if (isCardLoading) {
    dom.btnFindBuyers.disabled = true;
    dom.btnFindBuyers.textContent = 'Searching Google Maps…';
  } else {
    dom.btnFindBuyers.disabled = state.isCallInProgress;
  }

  // Quantity control row
  dom.buyerQuantityControl.replaceChildren();
  if (batch) {
    const total = batch.total_quantity || 0;
    const placed = Math.max(0, Math.round((total - (batch.remaining_quantity || 0)) * 100) / 100);
    const wrap = document.createElement('div');
    wrap.className = 'stock-progress';
    const lbl = document.createElement('div');
    lbl.className = 'stock-progress-label';
    lbl.textContent = `${placed} of ${total} ${batch.unit || 'kg'} placed`;
    wrap.appendChild(lbl);
    const track = document.createElement('div');
    track.className = 'stock-progress-track';
    const fill = document.createElement('div');
    fill.className = 'stock-progress-fill';
    fill.style.width = (total > 0 ? Math.min(100, (placed / total) * 100) : 0) + '%';
    track.appendChild(fill);
    wrap.appendChild(track);
    dom.buyerQuantityControl.appendChild(wrap);
  } else {
    const lbl = document.createElement('span');
    lbl.className = 'buyer-qty-label';
    lbl.textContent = `Quantity (${decision.unit || 'kg'})`;
    dom.buyerQuantityControl.appendChild(lbl);

    const input = document.createElement('input');
    input.type = 'number';
    input.min = '0.1';
    input.step = 'any';
    input.className = 'input-number';

    const itemObj = state.currentInspection.items.find(i => i.item_key === state.activeItemKey);
    const low = (itemObj && itemObj.quantity && itemObj.quantity.low > 0) ? itemObj.quantity.low : 0;
    const high = (itemObj && itemObj.quantity && itemObj.quantity.high > 0) ? itemObj.quantity.high : 0;
    let defaultVal = '';
    if (low > 0) defaultVal = String(low);
    else if (high > 0) defaultVal = String(high);

    if (state.quantityInputs[state.activeItemKey] === undefined) {
      state.quantityInputs[state.activeItemKey] = defaultVal;
      state.quantityEdited[state.activeItemKey] = false;
    }

    input.value = state.quantityInputs[state.activeItemKey];
    input.disabled = state.isCallInProgress;

    input.addEventListener('input', () => {
      state.quantityInputs[state.activeItemKey] = input.value.trim();
      state.quantityEdited[state.activeItemKey] = true;
    });

    dom.buyerQuantityControl.appendChild(input);
  }

  // Staff check checkbox if decision on_hold
  if (decision.on_hold) {
    dom.buyerStaffCheckRow.style.display = 'block';
    dom.buyerStaffCheck.checked = !!state.staffCheckedMap[state.activeItemKey];
    dom.buyerStaffCheck.disabled = state.isCallInProgress;
    dom.buyerStaffCheck.onchange = () => {
      state.staffCheckedMap[state.activeItemKey] = dom.buyerStaffCheck.checked;
    };
  } else {
    dom.buyerStaffCheckRow.style.display = 'none';
  }

  // Error banner
  const itemError = state.scoutErrorsMap[state.activeItemKey];
  if (itemError) {
    dom.buyerErrorBanner.textContent = itemError;
    dom.buyerErrorBanner.style.display = 'block';
  } else {
    dom.buyerErrorBanner.style.display = 'none';
  }

  const scoutResult = state.scoutResultsMap[state.activeItemKey];
  const buyers = scoutResult ? (scoutResult.buyers || []) : [];

  dom.buyersHeadChip.textContent = `${buyers.length} buyers · ${branchName}`;

  // Next action row
  dom.buyerNextActionRow.replaceChildren();
  renderNextActionRow(dom.buyerNextActionRow, batch, state.activeItemKey, buyers);

  // Calling hours banner
  const hasClosedBuyer = buyers.some(b => b.open_now === false);
  if (scoutResult && (scoutResult.outside_calling_hours || (batch && batch.outside_calling_hours) || hasClosedBuyer)) {
    dom.buyerHoursBanner.style.display = 'block';
  } else {
    dom.buyerHoursBanner.style.display = 'none';
  }

  // Determine highlighted buyer card
  let highlightedBuyer = null;
  if (batch && batch.next_action) {
    if (batch.next_action.kind === 'call') {
      highlightedBuyer = buyers.find(b => b.rank === batch.next_action.buyer_rank) ||
                         buyers.find(b => b.buyer_id === batch.next_action.buyer_id) || null;
    } else {
      highlightedBuyer = null;
    }
  } else if (!batch) {
    highlightedBuyer = buyers.length > 0 ? buyers[0] : null;
  }


  // Buyers list: the next buyer as a highlighted card, the rest as rows
  dom.buyersListContainer.replaceChildren();
  if (scoutResult && buyers.length === 0) {
    const emptyMsg = document.createElement('div');
    emptyMsg.className = 'buyers-empty';
    emptyMsg.textContent = 'No suitable buyers found nearby';
    dom.buyersListContainer.appendChild(emptyMsg);
  } else if (buyers.length > 0) {
    const list = document.createElement('div');
    list.className = 'buyer-list';
    buyers.forEach(b => {
      const isNext = !!highlightedBuyer && b.buyer_id === highlightedBuyer.buyer_id;
      const att = (batch && batch.attempts)
        ? batch.attempts.findLast(a => a.buyer_id === b.buyer_id && a.call_status !== 'pending')
        : null;
      list.appendChild(buyerItem(b, isNext, att, batch ? (batch.unit || 'kg') : 'kg'));
    });
    dom.buyersListContainer.appendChild(list);
  }

  // Footer: one quiet line (the Google Maps attribution stays visible), then what was left out and why
  if (scoutResult) {
    dom.buyersFooter.replaceChildren();

    const line = document.createElement('div');
    line.className = 'buyers-footer';
    const meta = document.createElement('div');
    meta.className = 'buyers-footer-text';
    let timeStr = 'searched just now';
    if (scoutResult.searched_at) {
      const diffMins = Math.floor((Date.now() - new Date(scoutResult.searched_at).getTime()) / 60000);
      if (diffMins >= 1) timeStr = `searched ${diffMins} min ago`;
    }
    if (scoutResult.meta && scoutResult.meta.reused) timeStr += ', reused';
    const attr = document.createElement('span');
    attr.className = 'buyers-attribution';
    attr.textContent = 'Results from Google Maps';
    meta.append(attr, document.createTextNode(` · within 10 km · ${timeStr}`));
    line.appendChild(meta);

    const btnRefresh = document.createElement('button');
    btnRefresh.type = 'button';
    btnRefresh.className = 'btn-ghost btn-sm';
    btnRefresh.textContent = 'Refresh';
    btnRefresh.disabled = state.isCallInProgress;
    btnRefresh.addEventListener('click', () => {
      fetchScoutBuyers(state.activeItemKey, true);
    });
    line.appendChild(btnRefresh);
    dom.buyersFooter.appendChild(line);
    dom.buyersFooter.style.display = 'block';

    dom.buyersScreenedOutContainer.replaceChildren();
    const screenedOut = scoutResult.screened_out || [];
    // The listed screened-out businesses always count, even if the skip counts were to miss them
    const skipped = { ...(scoutResult.skipped || {}) };
    skipped.unlikely_fit = Math.max(skipped.unlikely_fit || 0, screenedOut.length);
    const notShown = notShownSummary(skipped);
    if (notShown && screenedOut.length > 0) {
      // Gemini's reasons open from the summary line
      const det = document.createElement('details');
      det.className = 'screened-out';
      const sum = document.createElement('summary');
      sum.textContent = notShown;
      det.appendChild(sum);
      const ul = document.createElement('ul');
      screenedOut.forEach(item => {
        const li = document.createElement('li');
        const nm = document.createElement('span');
        nm.className = 'screened-name';
        nm.dir = 'auto';
        nm.textContent = item.name;
        li.appendChild(nm);
        li.appendChild(document.createTextNode(` · ${(item.buyer_type || '').replace(/_/g, ' ')} · ${item.distance_km} km: ${item.why}`));
        ul.appendChild(li);
      });
      det.appendChild(ul);
      if (skipped.unlikely_fit > screenedOut.length) {
        const more = document.createElement('p');
        more.className = 'screened-more';
        more.textContent = `Showing the nearest ${screenedOut.length}.`;
        det.appendChild(more);
      }
      dom.buyersScreenedOutContainer.appendChild(det);
    } else if (notShown) {
      const p = document.createElement('p');
      p.className = 'screened-out';
      p.textContent = notShown;
      dom.buyersScreenedOutContainer.appendChild(p);
    }
  } else {
    dom.buyersFooter.style.display = 'none';
    dom.buyersScreenedOutContainer.replaceChildren();
  }
}

// Plain words for the Scout's skip reasons (server SkipReason values)
const SKIP_LABELS = {
  no_phone: 'without a phone',
  not_operational: 'closed for good',
  too_far: 'too far',
  do_not_call: 'asked not to be called',
  cooldown: 'called recently',
  duplicate_phone: 'duplicates',
  not_screened: 'not screened',
  unlikely_fit: 'screened out by Gemini',
};

// "26 not shown: 16 without a phone, 1 closed for good and 9 screened out by Gemini" ('' when none)
function notShownSummary(skipped) {
  const parts = Object.entries(skipped || {}).filter(([, n]) => n > 0);
  if (parts.length === 0) return '';
  const total = parts.reduce((sum, [, n]) => sum + n, 0);
  const words = parts.map(([k, n]) => `${n} ${SKIP_LABELS[k] || k.replace(/_/g, ' ')}`);
  const list = words.length > 1 ? `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}` : words[0];
  return `${total} not shown: ${list}`;
}

function capitalise(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
}

// One buyer: rank, name (with hours only when not open), Gemini's reason, one quiet facts line, the action.
// Labels that every row would repeat ("Open now", "Likely fit") are left out; only the exceptions show.
function buyerItem(b, isNext, att, unit) {
  const item = document.createElement('div');
  item.className = 'buyer-item' + (isNext ? ' is-next' : '') + (att ? ' is-called' : '');

  const rank = document.createElement('div');
  rank.className = 'buyer-rank';
  rank.textContent = String(b.rank);
  item.appendChild(rank);

  const body = document.createElement('div');
  body.className = 'buyer-body';

  if (isNext) {
    const eyebrow = document.createElement('div');
    eyebrow.className = 'buyer-eyebrow';
    eyebrow.textContent = 'Next to call';
    body.appendChild(eyebrow);
  }

  const line1 = document.createElement('div');
  line1.className = 'buyer-line1';
  const name = document.createElement('span');
  name.className = 'buyer-name';
  name.dir = 'auto';
  name.textContent = b.name;
  line1.appendChild(name);
  if (b.open_now !== true) {
    const hours = document.createElement('span');
    hours.className = 'buyer-hours' + (b.open_now === false ? ' is-closed' : '');
    hours.textContent = b.open_now === false ? 'Closed now' : 'Hours unknown';
    line1.appendChild(hours);
  }
  body.appendChild(line1);

  if (b.fit_why || b.fit === 'possible') {
    const ai = document.createElement('p');
    ai.className = 'buyer-ai';
    ai.appendChild(icon('sparkle'));
    const text = document.createElement('span');
    text.textContent = [b.fit === 'possible' ? 'Possible fit' : '', b.fit_why].filter(Boolean).join(' · ');
    ai.appendChild(text);
    body.appendChild(ai);
  }

  const meta = document.createElement('div');
  meta.className = 'buyer-line2';
  const addMeta = text => {
    const span = document.createElement('span');
    span.className = 'buyer-meta-item';
    span.textContent = text;
    meta.appendChild(span);
  };
  addMeta(capitalise((b.buyer_type || '').replace(/_/g, ' ')));
  addMeta(`${b.distance_km} km`);
  addMeta(b.phone_masked || 'No phone');
  if (b.maps_uri && b.maps_uri.startsWith('https://')) {
    const link = document.createElement('a');
    link.className = 'buyer-maps-link';
    link.href = b.maps_uri;
    link.target = '_blank';
    link.rel = 'noopener';
    link.appendChild(document.createTextNode('Google Maps'));
    link.appendChild(icon('external'));
    meta.appendChild(link);
  }
  body.appendChild(meta);
  item.appendChild(body);

  const side = document.createElement('div');
  side.className = 'buyer-side';
  if (att && !isNext) {
    // A finished call shows its outcome. The next buyer always gets the button, even after an earlier
    // "call back", as before
    side.appendChild(buyerStatusChip(att, unit));
  } else {
    // The next buyer gets the page's main button; any other buyer can still be called (you play the buyer)
    const callBtn = document.createElement('button');
    callBtn.type = 'button';
    callBtn.className = isNext ? 'btn-primary' : 'btn-ghost btn-sm';
    if (isNext) callBtn.appendChild(icon('phone'));
    callBtn.appendChild(document.createTextNode(isNext ? 'Start call' : 'Call'));
    callBtn.setAttribute('aria-label', `${isNext ? 'Start call' : 'Call'}: ${b.name}`);
    callBtn.disabled = state.isCallInProgress;
    callBtn.addEventListener('click', () => {
      startCallForItem(state.activeItemKey, b.buyer_id);
    });
    side.appendChild(callBtn);
  }
  item.appendChild(side);
  return item;
}

// Outcome of a finished call, in plain words
function buyerStatusChip(att, unit) {
  const chip = document.createElement('span');
  if (att.call_status !== 'completed') {
    chip.className = 'chip chip-indigo';
    chip.textContent = 'In progress…';
    return chip;
  }
  if (att.outcome === 'deal' || att.outcome === 'partial_deal') {
    chip.className = 'chip chip-emerald';
    if (att.step === 'donate' || att.agreed_price === 0) {
      chip.textContent = `Donated ${att.agreed_quantity || 0} ${unit}`;
    } else {
      const priceStr = att.agreed_price == null ? '—' : att.agreed_price;
      chip.textContent = `Deal ${att.agreed_quantity || 0} ${unit} @ Rs ${priceStr}`;
    }
  } else if (att.outcome === 'call_back') {
    chip.className = 'chip chip-amber';
    chip.textContent = att.callback_at
      ? `Call back ${new Date(att.callback_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Karachi' })}`
      : 'Call back';
  } else if (att.outcome === 'do_not_call') {
    chip.className = 'chip chip-rose';
    chip.textContent = 'Asked not to be called';
  } else {
    const labels = { declined: 'Declined', no_answer: 'No answer', wants_photo: 'Wants a photo', wants_manager: 'Wants the manager' };
    chip.className = 'chip';
    chip.textContent = labels[att.outcome] || capitalise((att.outcome || 'Completed').replace(/_/g, ' '));
  }
  return chip;
}

