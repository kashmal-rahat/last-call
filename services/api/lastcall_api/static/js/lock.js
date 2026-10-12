// services/api/lastcall_api/static/js/lock.js

import { state } from './state.js';
import * as dom from './dom.js';
import { renderResults } from './reading.js';

export function batchIdFor(itemKey) {
  if (!state.currentInspection || !state.currentInspection.inspection_id || !dom.branchSelect.value) {
    return null;
  }
  return `${state.currentInspection.inspection_id}__${itemKey}__${dom.branchSelect.value}`;
}

export async function loadBatchesForBranch() {
  state.currentBatchesMap = {};
  if (!state.currentInspection || !state.currentInspection.inspection_id) return;
  const code = dom.inspectAccessCodeEl.value.trim();
  const items = state.currentInspection.items || [];
  await Promise.all(items.map(async (item) => {
    const batchId = batchIdFor(item.item_key);
    if (!batchId) return;
    try {
      const res = await fetch(`/demo/batches/${encodeURIComponent(batchId)}`, {
        headers: code ? { 'X-Demo-Access-Code': code } : {}
      });
      if (res.ok) {
        state.currentBatchesMap[item.item_key] = await res.json();
      }
    } catch (e) {
      console.warn('loadBatchesForBranch', e);
    }
  }));
  renderResults(state.currentInspection, state.currentDisplayUrl);
}

export function isShelfLocked() {
  if (state.isCallInProgress) return true;
  return Object.values(state.currentBatchesMap || {}).some(
    b => b && Array.isArray(b.attempts) && b.attempts.length > 0
  );
}

export function updateShelfLock() {
  const locked = isShelfLocked();
  dom.branchSelect.disabled = locked;
  dom.closingTimeSelect.disabled = locked;

  // Segmented closing-time buttons
  document.querySelectorAll('.closing-time-btn').forEach(btn => {
    btn.disabled = locked;
  });

  // All price overrides and redecide buttons
  document.querySelectorAll('.price-override-input').forEach(input => {
    input.disabled = locked;
  });
  document.querySelectorAll('.btn-redecide').forEach(btn => {
    btn.disabled = locked;
  });
  if (dom.activeItemShelfPriceInput) {
    dom.activeItemShelfPriceInput.disabled = locked;
  }
  if (dom.btnActiveItemRedecide) {
    dom.btnActiveItemRedecide.disabled = locked;
  }

  // Per D58: Inspect stays enabled while locked, disabled only during call or inspection
  if (dom.btnInspect) {
    dom.btnInspect.disabled = state.isCallInProgress || state.isInspecting;
  }
  if (dom.shelfPhotoInput) {
    dom.shelfPhotoInput.disabled = state.isCallInProgress || state.isInspecting;
  }
  // New shelf disabled only during call or inspection
  if (dom.btnNewShelf) {
    dom.btnNewShelf.disabled = state.isCallInProgress || state.isInspecting;
  }

  if (dom.shelfLockNote) {
    if (locked) {
      dom.shelfLockNote.textContent = 'Branch, closing time and prices are fixed once calls start · New shelf to start over';
      dom.shelfLockNote.style.display = 'block';
    } else {
      dom.shelfLockNote.textContent = '';
      dom.shelfLockNote.style.display = 'none';
    }
  }
}
