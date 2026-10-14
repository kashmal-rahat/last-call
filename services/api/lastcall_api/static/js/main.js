// services/api/lastcall_api/static/js/main.js

import * as dom from './dom.js';
import { state } from './state.js';
import { getStoredItem, setStoredItem, getOrCreateShelfId, resetShelfId } from './storage.js';
import { showToast, initInfoTips } from './ui.js';
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
import { hangup } from './call.js';
import { renderImpact } from './impact.js';
import { initPhoneDemo } from './phone.js';

// Setup Event Listeners

if (dom.btnNewShelf) {
  dom.btnNewShelf.addEventListener('click', (e) => {
    e.preventDefault();
    if (state.isCallInProgress || state.isInspecting) return;

    const newId = resetShelfId();
    if (dom.shelfIdDisplay) dom.shelfIdDisplay.textContent = newId;

    state.currentInspection = null;
    state.currentLadderResult = null;
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
    dom.voiceSection.style.display = 'none';
    dom.inspectFooter.style.display = 'none';
    dom.inspectLoading.style.display = 'none';
    dom.inspectedImage.src = '';
    dom.bboxOverlay.replaceChildren();
    dom.itemsContainer.replaceChildren();

    if (dom.resultCard) {
      dom.resultCard.style.display = 'none';
      dom.resultCard.classList.remove('visible');
    }
    if (dom.resultContent) {
      dom.resultContent.replaceChildren();
    }
    if (dom.resultNextAction) {
      dom.resultNextAction.replaceChildren();
    }

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
    if (dom.resultCard) {
      dom.resultCard.style.display = 'none';
      dom.resultCard.classList.remove('visible');
    }
    if (dom.resultContent) {
      dom.resultContent.replaceChildren();
    }
    if (dom.resultNextAction) {
      dom.resultNextAction.replaceChildren();
    }
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
