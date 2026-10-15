// services/api/lastcall_api/static/js/main.js

import * as dom from './dom.js';
import { state } from './state.js';
import { getStoredItem, setStoredItem, getOrCreateShelfId, resetShelfId } from './storage.js';
import { showToast, initInfoTips, scrollToSection } from './ui.js';
import { clearAccessCodeError } from './api.js';
import {
  updateClock,
  syncClosingTimeButtons,
  loadSamples,
  showUploadedPhoto,
  loadBranches,
  updateHeaderBranch
} from './setup.js';
import { isShelfLocked, updateShelfLock, loadBatchesForBranch } from './lock.js';
import { handleInspect, renderResults } from './reading.js';
import { triggerDecide, updateStepperFade } from './decision.js';
import { fetchScoutBuyers } from './buyers.js';
import { hangup, resetCallPanel } from './call.js';
import { renderImpact } from './impact.js';
import { initPhoneDemo } from './phone.js';

// Setup Event Listeners

// A trackpad keeps sending wheel events for a moment after a flick (momentum), even once the page is at the
// top, and each one cancels a smooth scroll in progress: the page slides back up. So a scroll the judge asks
// for while they are still arriving waits until none has come for 100 ms, and at most 1 s.
const MOMENTUM_GAP_MS = 100;
const MOMENTUM_MAX_WAIT_MS = 1000;
let lastWheelAt = -Infinity;  // performance.now(), the same clock as the checks below
let pendingScroll = null;     // one waiting scroll: clicking again while it waits doesn't add another
window.addEventListener('wheel', () => { lastWheelAt = performance.now(); }, { passive: true });

function scrollToSectionWhenStill(el) {
  clearTimeout(pendingScroll);
  const askedAt = performance.now();
  (function attempt() {
    const now = performance.now();
    const stillFor = now - lastWheelAt;
    if (stillFor >= MOMENTUM_GAP_MS || now - askedAt >= MOMENTUM_MAX_WAIT_MS) {
      pendingScroll = null;
      scrollToSection(el);
    } else {
      pendingScroll = setTimeout(attempt, MOMENTUM_GAP_MS - stillFor);
    }
  })();
}

// "Try the live demo": the page scrolls to the setup itself, with the same helper as its other scrolls, and
// leaves the address as /demo. Following the link's #inspectorSection (kept for a page without JS) put the
// fragment in the address, so every refresh, back or forward made the browser scroll again while loading.
if (dom.heroDemoLink) {
  dom.heroDemoLink.addEventListener('click', (e) => {
    e.preventDefault();
    scrollToSectionWhenStill(dom.inspectorSection);
  });
}
// An address that still carries the fragment (saved from before this change) is cleaned up and opens like
// any other visit
if (location.hash === '#inspectorSection') {
  history.replaceState(null, '', location.pathname + location.search);
}

// A refresh opens at the hero, not where the judge was: the reload clears the reading, buyers and calls,
// so the old position would point into a page that no longer has what was there
history.scrollRestoration = 'manual';

if (dom.btnNewShelf) {
  dom.btnNewShelf.addEventListener('click', (e) => {
    e.preventDefault();
    if (state.isCallInProgress || state.isInspecting) return;

    const newId = resetShelfId();
    if (dom.shelfIdDisplay) dom.shelfIdDisplay.textContent = newId;

    state.currentInspection = null;
    state.currentLadderResult = null;
    updateClock();  // back to the real time
    state.currentDisplayUrl = null;
    state.activeItemKey = null;
    state.priceOverrides = {};
    state.scoutResultsMap = {};
    state.scoutErrorsMap = {};
    state.scoutLoadingMap = {};
    state.scoutRequestCounters = {};
    state.currentBatchesMap = {};
    state.quantityInputs = {};
    state.quantityEdited = {};
    state.staffCheckedMap = {};
    state.currentActiveCall = null;

    // Hide results
    dom.inspectError.style.display = 'none';
    dom.decideError.style.display = 'none';
    dom.decideError.textContent = '';
    dom.inspectStatusBanner.style.display = 'none';
    dom.inspectInstructionBanner.style.display = 'none';
    dom.sectionAiReading.style.display = 'none';
    dom.sectionDecision.style.display = 'none';
    dom.sectionBuyers.style.display = 'none';
    dom.inspectFooter.style.display = 'none';
    dom.inspectLoading.style.display = 'none';
    dom.inspectedImage.src = '';
    dom.bboxOverlay.replaceChildren();
    dom.itemsContainer.replaceChildren();
    resetCallPanel();

    updateShelfLock();
    renderImpact();
  });
}

if (dom.closingTimeButtons) {
  dom.closingTimeButtons.addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn || btn.disabled) return;
    dom.closingTimeSelect.value = btn.dataset.val;
    syncClosingTimeButtons();
    dom.closingTimeSelect.dispatchEvent(new Event('change'));
  });
}

if (dom.closingTimeSelect) {
  dom.closingTimeSelect.addEventListener('change', () => {
    syncClosingTimeButtons();
    updateClock();  // the header shows the picked time at once, not after the decision
    if (state.currentInspection && state.currentInspection.items && state.currentInspection.items.length > 0) {
      triggerDecide();
    }
  });
}

if (dom.branchSelect) {
  dom.branchSelect.addEventListener('change', () => {
    setStoredItem('lc_branch_id', dom.branchSelect.value);
    updateHeaderBranch();
    state.scoutResultsMap = {};
    state.scoutErrorsMap = {};
    state.scoutLoadingMap = {};
    state.currentBatchesMap = {};
    resetCallPanel();
    renderResults(state.currentInspection, state.currentDisplayUrl);
  });
}

if (dom.shelfPhotoInput) {
  dom.shelfPhotoInput.addEventListener('change', () => {
    if (dom.shelfPhotoInput.files.length > 0) {
      showUploadedPhoto(dom.shelfPhotoInput.files[0]);
    }
  });
}

if (dom.btnInspect) {
  dom.btnInspect.addEventListener('click', handleInspect);
}

if (dom.btnHangup) {
  dom.btnHangup.addEventListener('click', hangup);
}

// Decision steps: keep the edge fades in step with scrolling and the window's width
if (dom.ladderStepper) {
  dom.ladderStepper.addEventListener('scroll', updateStepperFade, { passive: true });
  window.addEventListener('resize', updateStepperFade);
}

if (dom.btnActiveItemRedecide) {
  dom.btnActiveItemRedecide.addEventListener('click', () => {
    if (isShelfLocked() || !state.activeItemKey) return;
    const val = parseInt(dom.activeItemShelfPriceInput.value.trim(), 10);
    if (!isNaN(val) && val > 0 && val <= 100000) {
      state.priceOverrides[state.activeItemKey] = val;
      triggerDecide();
    } else {
      showToast('Please enter a valid shelf price (1 to 100,000 Rs).', 'error');
    }
  });
}

if (dom.btnFindBuyers) {
  dom.btnFindBuyers.addEventListener('click', () => {
    if (state.activeItemKey) {
      fetchScoutBuyers(state.activeItemKey, false);
    }
  });
}

// Access Code
const savedCode = getStoredItem('lc_code', '');
if (savedCode && dom.inspectAccessCodeEl) {
  dom.inspectAccessCodeEl.value = savedCode;
}
if (dom.inspectAccessCodeEl) {
  dom.inspectAccessCodeEl.addEventListener('input', () => {
    clearAccessCodeError();
    setStoredItem('lc_code', dom.inspectAccessCodeEl.value.trim());
  });
}

// Initial Startup
async function init() {
  if (dom.shelfIdDisplay) {
    dom.shelfIdDisplay.textContent = getOrCreateShelfId();
  }
  updateClock();
  setInterval(updateClock, 60000);

  loadSamples();
  initInfoTips();
  initPhoneDemo();
  await loadBranches();
  const branchId = dom.branchSelect ? dom.branchSelect.value : null;
  if (branchId) {
    await loadBatchesForBranch();
  }
  updateHeaderBranch();
  syncClosingTimeButtons();
  renderImpact();
}

init();
