// services/api/lastcall_api/static/js/buyers.js

import { state } from './state.js';
import * as dom from './dom.js';
import { getFindBuyersLabel, getNextStepTargetLabel } from './format.js';
import { icon, showToast } from './ui.js';
import { batchIdFor, loadBatchesForBranch } from './lock.js';
import { renderResults } from './reading.js';
import { startCallForItem } from './call.js';

export async function fetchScoutBuyers(itemKey, refresh = false) {
  if (!state.currentInspection || !state.currentInspection.inspection_id) return;
  const code = dom.inspectAccessCodeEl.value.trim();
  if (!code) {
    showToast('Please enter your Demo Access Code first.', 'error');
    dom.inspectAccessCodeEl.focus();
    return;
  }
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
    const res = await fetch('/demo/scout', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Demo-Access-Code': code
      },
      body: JSON.stringify(payload)
    });

    if (state.scoutRequestCounters[itemKey] !== currentCounter) return;

    if (res.ok) {
      const data = await res.json();
      state.scoutResultsMap[itemKey] = data;
      state.scoutErrorsMap[itemKey] = null;
      const batchId = batchIdFor(itemKey);
      if (batchId && state.currentBatchesMap[itemKey]) {
        try {
          const bRes = await fetch(`/demo/batches/${encodeURIComponent(batchId)}`, {
            headers: { 'X-Demo-Access-Code': code }
          });
          if (bRes.ok) {
            state.currentBatchesMap[itemKey] = await bRes.json();
          }
        } catch (e) {
          console.warn('fetchScoutBuyers batch refresh', e);
        }
      }
    } else {
      state.scoutResultsMap[itemKey] = null;
      const errData = await res.json().catch(() => ({}));
      const rawDetail = errData.detail;
      const detail = (typeof rawDetail === 'string' && rawDetail.trim())
        ? rawDetail.trim()
        : 'Buyer search failed, please try again.';
      state.scoutErrorsMap[itemKey] = detail;
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

export function renderNextActionRow(container, batch, itemKey, buyers = []) {
  container.replaceChildren();

  if (batch && batch.next_action) {
    const act = batch.next_action;
    if (act.kind === 'call') {
      const rank = act.buyer_rank || ((batch.attempts ? batch.attempts.length : 0) + 1);
      const targetB = buyers.find(x => x.rank === rank) || buyers[rank - 1];
      const bId = targetB ? targetB.buyer_id : null;
      const bName = targetB ? targetB.name : '';
      const btnCall = document.createElement('button');
      btnCall.type = 'button';
      btnCall.className = 'btn-primary';
      btnCall.textContent = (batch.attempts && batch.attempts.length > 0)
        ? `Next buyer (#${rank}${bName ? ' ' + bName : ''})`
        : `Start calling #${rank}${bName ? ' ' + bName : ''}`;
      btnCall.disabled = state.isCallInProgress;
      btnCall.addEventListener('click', () => {
        startCallForItem(itemKey, bId);
      });
      container.appendChild(btnCall);
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
    const btnCall = document.createElement('button');
    btnCall.type = 'button';
    btnCall.className = 'btn-primary';
    btnCall.textContent = `Start calling #1 ${buyers[0].name}`;
    btnCall.disabled = state.isCallInProgress;
    btnCall.addEventListener('click', () => {
      startCallForItem(itemKey, buyers[0].buyer_id);
    });
    container.appendChild(btnCall);
  }
}

export async function advanceBatchStep(batchId, itemKey) {
  const code = dom.inspectAccessCodeEl.value.trim();
  if (!code) {
    showToast('Please enter your Demo Access Code first.', 'error');
    dom.inspectAccessCodeEl.focus();
    return;
  }
  try {
    const res = await fetch(`/demo/batches/${encodeURIComponent(batchId)}/next-step`, {
      method: 'POST',
      headers: {
        'X-Demo-Access-Code': code
      }
    });
    if (res.ok) {
      const updated = await res.json();
      state.currentBatchesMap[itemKey] = updated;
      await fetchScoutBuyers(itemKey, false);
    } else {
      const errData = await res.json().catch(() => ({}));
      showToast(errData.detail || 'Failed to advance step', 'error');
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
    const badge = document.createElement('span');
    badge.className = 'chip chip-slate font-mono';
    badge.textContent = `Remaining: ${batch.remaining_quantity} of ${batch.total_quantity} ${batch.unit || 'kg'}`;
    dom.buyerQuantityControl.appendChild(badge);
  } else {
    const lbl = document.createElement('span');
    lbl.textContent = `Quantity (${decision.unit || 'kg'}):`;
    dom.buyerQuantityControl.appendChild(lbl);

    const input = document.createElement('input');
    input.type = 'number';
    input.min = '0.1';
    input.step = 'any';
    input.className = 'price-override-input qty-input';

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

  const otherBuyers = buyers.filter(b => !highlightedBuyer || b.buyer_id !== highlightedBuyer.buyer_id);

  // Buyers Cards Container
  dom.buyersListContainer.replaceChildren();
  if (scoutResult && buyers.length === 0) {
    const emptyMsg = document.createElement('div');
    emptyMsg.className = 'font-mono text-muted py-6';
    emptyMsg.textContent = 'No suitable buyers found nearby';
    dom.buyersListContainer.appendChild(emptyMsg);
  } else if (buyers.length > 0) {
    // Highlighted Next to Call Card (if present)
    if (highlightedBuyer) {
      const nextCard = document.createElement('div');
      nextCard.className = 'buyer-card-top-pick';

      // Header
      const topPickHead = document.createElement('div');
      topPickHead.className = 'top-pick-head flex justify-between items-center flex-wrap gap-2';

      const bTitleGroup = document.createElement('div');
      bTitleGroup.className = 'flex items-center gap-2 flex-wrap';

      const rankBadge = document.createElement('span');
      rankBadge.className = 'chip chip-indigo';
      rankBadge.textContent = `#${highlightedBuyer.rank || 1} · Next to call`;
      bTitleGroup.appendChild(rankBadge);

      const bName = document.createElement('span');
      bName.className = 'buyer-heading-name';
      bName.dir = 'auto';
      bName.textContent = highlightedBuyer.name;
      bTitleGroup.appendChild(bName);

      const typeChip = document.createElement('span');
      typeChip.className = 'chip chip-slate';
      typeChip.textContent = (highlightedBuyer.buyer_type || '').replace(/_/g, ' ');
      bTitleGroup.appendChild(typeChip);

      const fitChip = document.createElement('span');
      if (highlightedBuyer.fit === 'likely') {
        fitChip.className = 'chip chip-emerald';
        fitChip.textContent = 'Likely';
      } else {
        fitChip.className = 'chip chip-slate';
        fitChip.textContent = 'Possible';
      }
      bTitleGroup.appendChild(fitChip);

      topPickHead.appendChild(bTitleGroup);

      const openStatus = document.createElement('span');
      if (highlightedBuyer.open_now === true) {
        openStatus.className = 'chip chip-emerald';
        openStatus.textContent = 'Open now';
      } else if (highlightedBuyer.open_now === false) {
        openStatus.className = 'chip chip-rose';
        openStatus.textContent = 'Closed now';
      } else {
        openStatus.className = 'chip chip-slate';
        openStatus.textContent = 'Hours unknown';
      }
      topPickHead.appendChild(openStatus);
      nextCard.appendChild(topPickHead);

      // Meta Row: distance, masked phone, maps link
      const metaRow = document.createElement('div');
      metaRow.className = 'buyer-meta-row flex gap-4 text-sm flex-wrap items-center';

      const distEl = document.createElement('span');
      distEl.className = 'flex items-center gap-1';
      distEl.appendChild(icon('pin'));
      distEl.appendChild(document.createTextNode(` ${highlightedBuyer.distance_km} km`));
      metaRow.appendChild(distEl);

      const phoneEl = document.createElement('span');
      phoneEl.className = 'buyer-phone-masked flex items-center gap-1';
      phoneEl.appendChild(icon('phone'));
      phoneEl.appendChild(document.createTextNode(` ${highlightedBuyer.phone_masked || 'No phone'}`));
      metaRow.appendChild(phoneEl);

      if (highlightedBuyer.maps_uri && highlightedBuyer.maps_uri.startsWith('https://')) {
        const mapsLink = document.createElement('a');
        mapsLink.className = 'buyer-maps-link flex items-center gap-1';
        mapsLink.href = highlightedBuyer.maps_uri;
        mapsLink.target = '_blank';
        mapsLink.rel = 'noopener';
        mapsLink.appendChild(document.createTextNode('View on Google Maps '));
        mapsLink.appendChild(icon('external'));
        metaRow.appendChild(mapsLink);
      }

      nextCard.appendChild(metaRow);

      // Facts line (reason) & fit_why
      const factsRow = document.createElement('div');
      factsRow.className = 'buyer-facts-row flex flex-col gap-1 text-xs text-secondary';

      if (highlightedBuyer.reason) {
        const rEl = document.createElement('div');
        rEl.textContent = highlightedBuyer.reason;
        factsRow.appendChild(rEl);
      }

      if (highlightedBuyer.fit_why) {
        const fitEl = document.createElement('div');
        fitEl.className = 'text-emerald-dark font-medium';
        fitEl.textContent = highlightedBuyer.fit_why;
        factsRow.appendChild(fitEl);
      }

      if (factsRow.childNodes.length > 0) {
        nextCard.appendChild(factsRow);
      }

      // Call button
      const callBtn = document.createElement('button');
      callBtn.type = 'button';
      callBtn.className = 'btn-ai self-start';
      callBtn.textContent = 'Start call · you play the buyer';
      callBtn.disabled = state.isCallInProgress;
      callBtn.addEventListener('click', () => {
        startCallForItem(state.activeItemKey, highlightedBuyer.buyer_id);
      });
      nextCard.appendChild(callBtn);

      dom.buyersListContainer.appendChild(nextCard);
    }

    // Other buyers in rank order (including already-called ones)
    otherBuyers.forEach(b => {
      const bRow = document.createElement('div');
      bRow.className = 'buyer-card-row';

      const mainCol = document.createElement('div');
      mainCol.className = 'buyer-row-main flex flex-col gap-1 flex-1';

      // Line 1: Header (rank, name, type chip, open/closed status, fit chip)
      const line1 = document.createElement('div');
      line1.className = 'flex items-center gap-2 flex-wrap';

      const rNum = document.createElement('span');
      rNum.className = 'chip chip-slate font-mono';
      rNum.textContent = `#${b.rank}`;
      line1.appendChild(rNum);

      const nameS = document.createElement('span');
      nameS.className = 'font-bold';
      nameS.dir = 'auto';
      nameS.textContent = b.name;
      line1.appendChild(nameS);

      const typeChip = document.createElement('span');
      typeChip.className = 'chip chip-slate';
      typeChip.textContent = (b.buyer_type || '').replace(/_/g, ' ');
      line1.appendChild(typeChip);

      const openStatus = document.createElement('span');
      if (b.open_now === true) {
        openStatus.className = 'chip chip-emerald';
        openStatus.textContent = 'Open now';
      } else if (b.open_now === false) {
        openStatus.className = 'chip chip-rose';
        openStatus.textContent = 'Closed now';
      } else {
        openStatus.className = 'chip chip-slate';
        openStatus.textContent = 'Hours unknown';
      }
      line1.appendChild(openStatus);

      const fitChip = document.createElement('span');
      if (b.fit === 'likely') {
        fitChip.className = 'chip chip-emerald';
        fitChip.textContent = 'Likely';
      } else {
        fitChip.className = 'chip chip-slate';
        fitChip.textContent = 'Possible';
      }
      line1.appendChild(fitChip);

      mainCol.appendChild(line1);

      // Line 2: Details (distance, masked phone on one line, maps link)
      const line2 = document.createElement('div');
      line2.className = 'flex items-center gap-3 flex-wrap text-sm';

      const distEl = document.createElement('span');
      distEl.className = 'flex items-center gap-1';
      distEl.appendChild(icon('pin'));
      distEl.appendChild(document.createTextNode(` ${b.distance_km} km`));
      line2.appendChild(distEl);

      const phoneEl = document.createElement('span');
      phoneEl.className = 'buyer-phone-masked flex items-center gap-1';
      phoneEl.appendChild(icon('phone'));
      phoneEl.appendChild(document.createTextNode(` ${b.phone_masked || 'No phone'}`));
      line2.appendChild(phoneEl);

      if (b.maps_uri && b.maps_uri.startsWith('https://')) {
        const mapsLink = document.createElement('a');
        mapsLink.className = 'buyer-maps-link flex items-center gap-1';
        mapsLink.href = b.maps_uri;
        mapsLink.target = '_blank';
        mapsLink.rel = 'noopener';
        mapsLink.appendChild(document.createTextNode('View on Google Maps '));
        mapsLink.appendChild(icon('external'));
        line2.appendChild(mapsLink);
      }

      mainCol.appendChild(line2);

      // Line 3: Facts line (reason) & fit_why
      const line3 = document.createElement('div');
      line3.className = 'flex flex-col gap-1 text-xs text-secondary';

      if (b.reason) {
        const reasonEl = document.createElement('div');
        reasonEl.textContent = b.reason;
        line3.appendChild(reasonEl);
      }

      if (b.fit_why) {
        const fitWhyEl = document.createElement('div');
        fitWhyEl.className = 'text-emerald-dark font-medium';
        fitWhyEl.textContent = b.fit_why;
        line3.appendChild(fitWhyEl);
      }

      if (line3.childNodes.length > 0) {
        mainCol.appendChild(line3);
      }

      bRow.appendChild(mainCol);

      // Right Column: Row status chips in plain words or "Play this buyer"
      const rightCol = document.createElement('div');
      rightCol.className = 'buyer-row-action flex items-center gap-2 flex-shrink-0';

      const att = (batch && batch.attempts)
        ? batch.attempts.findLast(a => a.buyer_id === b.buyer_id && a.call_status !== 'pending')
        : null;
      if (att && att.call_status !== 'pending') {
        const chip = document.createElement('span');
        if (att.call_status === 'completed') {
          if (att.outcome === 'deal' || att.outcome === 'partial_deal') {
            chip.className = 'chip chip-emerald';
            if (att.step === 'donate' || att.agreed_price === 0) {
              chip.textContent = `Donated ${att.agreed_quantity || 0} ${batch.unit || 'kg'}`;
            } else {
              const priceStr = att.agreed_price == null ? '—' : att.agreed_price;
              chip.textContent = `Deal ${att.agreed_quantity || 0} ${batch.unit || 'kg'} @ Rs ${priceStr}`;
            }
          } else if (att.outcome === 'declined') {
            chip.className = 'chip chip-rose';
            chip.textContent = 'Declined';
          } else if (att.outcome === 'call_back') {
            chip.className = 'chip chip-amber';
            const cbTime = att.callback_at ? ` ${att.callback_at}` : (att.notes ? ` ${att.notes}` : '');
            chip.textContent = `Call back${cbTime}`;
          } else if (att.outcome === 'no_answer') {
            chip.className = 'chip chip-slate';
            chip.textContent = 'No answer';
          } else if (att.outcome === 'do_not_call') {
            chip.className = 'chip chip-rose';
            chip.textContent = 'Asked not to be called';
          } else if (att.outcome === 'wants_photo') {
            chip.className = 'chip chip-rose';
            chip.textContent = 'Wants photo';
          } else if (att.outcome === 'wants_manager') {
            chip.className = 'chip chip-rose';
            chip.textContent = 'Wants manager';
          } else {
            chip.className = 'chip chip-slate';
            chip.textContent = (att.outcome || 'Completed').replace(/_/g, ' ');
          }
        } else {
          chip.className = 'chip chip-indigo';
          chip.textContent = 'In progress…';
        }
        rightCol.appendChild(chip);
      } else {
        const playBtn = document.createElement('button');
        playBtn.type = 'button';
        playBtn.className = 'btn-ghost btn-play-buyer';
        playBtn.textContent = 'Play this buyer';
        playBtn.disabled = state.isCallInProgress;
        playBtn.addEventListener('click', () => {
          startCallForItem(state.activeItemKey, b.buyer_id);
        });
        rightCol.appendChild(playBtn);
      }

      bRow.appendChild(rightCol);
      dom.buyersListContainer.appendChild(bRow);
    });
  }

  // Footer with plain-word non-zero skipped counts and Refresh button
  if (scoutResult) {
    dom.buyersFooter.replaceChildren();

    const skipMap = {
      no_phone: 'no phone',
      too_far: 'too far',
      unlikely_buyer: 'unlikely',
      unlikely: 'unlikely',
      no_name: 'no name',
      closed: 'closed',
      dnc: 'on do-not-call list',
      cooldown: 'called recently',
      not_screened: 'not screened'
    };
    const skippedParts = [];
    if (scoutResult.skipped) {
      for (const [k, count] of Object.entries(scoutResult.skipped)) {
        if (count > 0) {
          skippedParts.push(`${count} ${skipMap[k] || k.replace(/_/g, ' ')}`);
        }
      }
    }

    if (skippedParts.length > 0) {
      const skipLine = document.createElement('div');
      skipLine.className = 'font-mono text-muted text-sm w-full mb-2';
      skipLine.textContent = `Skipped: ${skippedParts.join(' · ')}`;
      dom.buyersFooter.appendChild(skipLine);
    }

    const footerMeta = document.createElement('div');
    footerMeta.className = 'flex justify-between items-center w-full flex-wrap gap-2';

    const metaLeft = document.createElement('div');
    metaLeft.className = 'flex items-center flex-wrap gap-1';

    const attrStrong = document.createElement('strong');
    attrStrong.textContent = 'Results from Google Maps';
    metaLeft.appendChild(attrStrong);

    const nearSpan = document.createElement('span');
    nearSpan.textContent = ` · Near ${scoutResult.branch_name} · within 10 km`;
    metaLeft.appendChild(nearSpan);

    let timeStr = 'Searched just now';
    if (scoutResult.searched_at) {
      const diffMs = Date.now() - new Date(scoutResult.searched_at).getTime();
      const diffMins = Math.floor(diffMs / 60000);
      if (diffMins >= 1) timeStr = `Searched ${diffMins} min ago`;
    }
    if (scoutResult.meta && scoutResult.meta.reused) timeStr += ' · reused';
    const tSpan = document.createElement('span');
    tSpan.textContent = ` · ${timeStr}`;
    metaLeft.appendChild(tSpan);

    footerMeta.appendChild(metaLeft);

    const btnRefresh = document.createElement('button');
    btnRefresh.type = 'button';
    btnRefresh.className = 'btn-ghost btn-scout-refresh';
    btnRefresh.textContent = 'Refresh';
    btnRefresh.disabled = state.isCallInProgress;
    btnRefresh.addEventListener('click', () => {
      fetchScoutBuyers(state.activeItemKey, true);
    });
    footerMeta.appendChild(btnRefresh);

    dom.buyersFooter.appendChild(footerMeta);
    dom.buyersFooter.style.display = 'flex';

    // Screened out details
    dom.buyersScreenedOutContainer.replaceChildren();
    const screenedOut = scoutResult.screened_out || [];
    if (screenedOut.length > 0) {
      const det = document.createElement('details');
      det.className = 'font-mono text-xs text-muted';
      const sum = document.createElement('summary');
      sum.className = 'cursor-pointer';
      sum.textContent = `Screened out by Gemini (${screenedOut.length})`;
      det.appendChild(sum);

      const ul = document.createElement('ul');
      ul.className = 'mt-2 pl-5';
      screenedOut.forEach(item => {
        const li = document.createElement('li');
        li.textContent = `${item.name} · ${(item.buyer_type || '').replace(/_/g, ' ')} · ${item.distance_km} km — ${item.why}`;
        ul.appendChild(li);
      });
      det.appendChild(ul);
      dom.buyersScreenedOutContainer.appendChild(det);
    }
  } else {
    dom.buyersFooter.style.display = 'none';
    dom.buyersScreenedOutContainer.replaceChildren();
  }
}
