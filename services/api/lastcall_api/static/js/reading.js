// services/api/lastcall_api/static/js/reading.js

import { state } from './state.js';
import * as dom from './dom.js';
import { setStoredItem, getOrCreateShelfId } from './storage.js';
import { rankItems, formatObserved, formatQuantity, STAFF_REASON_LABELS } from './format.js';
import { icon, showToast } from './ui.js';
import { updateShelfLock } from './lock.js';
import { updateProgressBar } from './setup.js';
import { triggerDecide, renderActiveDecision } from './decision.js';
import { renderActiveBuyers } from './buyers.js';
import { renderImpact } from './impact.js';

export async function handleInspect() {
  const code = dom.inspectAccessCodeEl.value.trim();
  if (!code) {
    dom.inspectError.textContent = 'Please enter the Demo Access Code.';
    dom.inspectError.style.display = 'block';
    dom.inspectAccessCodeEl.focus();
    showToast('Please enter the Demo Access Code.', 'error');
    return;
  }
  setStoredItem('lc_code', code);
  dom.inspectAccessCodeEl.value = code;

  let photoFile = null;
  let displayUrl = null;

  if (dom.shelfPhotoInput.files && dom.shelfPhotoInput.files.length > 0) {
    photoFile = dom.shelfPhotoInput.files[0];
    displayUrl = URL.createObjectURL(photoFile);
  } else if (state.activeSampleBlob) {
    photoFile = state.activeSampleBlob;
    displayUrl = state.activeSampleUrl;
  } else if (state.activeSampleUrl) {
    try {
      const sRes = await fetch(state.activeSampleUrl);
      if (sRes.ok) {
        photoFile = await sRes.blob();
        state.activeSampleBlob = photoFile;
        displayUrl = state.activeSampleUrl;
      }
    } catch (e) {
      console.warn('handleInspect sample fetch', e);
    }
  }

  if (!photoFile) {
    dom.inspectError.textContent = 'Please select a sample photo or upload a shelf photo.';
    dom.inspectError.style.display = 'block';
    showToast('Please select a sample photo or upload a shelf photo.', 'error');
    return;
  }

  dom.inspectError.style.display = 'none';
  dom.decideError.style.display = 'none';
  dom.decideError.textContent = '';
  dom.inspectLoading.style.display = 'flex';
  state.isInspecting = true;
  dom.btnInspect.disabled = true;

  state.currentInspection = null;
  state.currentLadderResult = null;
  state.priceOverrides = {};
  state.isDeciding = false;
  state.scoutResultsMap = {};
  state.scoutErrorsMap = {};
  state.scoutLoadingMap = {};
  state.scoutRequestCounters = {};
  state.currentBatchesMap = {};
  state.quantityInputs = {};
  state.quantityEdited = {};
  state.staffCheckedMap = {};
  state.currentActiveCall = null;
  updateShelfLock();

  const shelfId = getOrCreateShelfId();
  const formData = new FormData();
  formData.append('photo', photoFile, 'shelf_photo.jpg');
  formData.append('shelf_id', shelfId);

  const binKg = dom.binCapacityEl.value.trim();
  if (binKg) {
    formData.append('bin_capacity_kg', binKg);
  }

  try {
    const res = await fetch('/demo/inspect', {
      method: 'POST',
      headers: {
        'X-Demo-Access-Code': code
      },
      body: formData
    });

    if (res.status === 401) {
      throw new Error('Invalid access code.');
    } else if (res.status === 415) {
      throw new Error('Please upload a JPEG or PNG photo.');
    } else if (res.status === 413) {
      throw new Error('Image exceeds maximum upload size (8 MB).');
    } else if (res.status === 429) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Rate limit reached. Please try again later.');
    } else if (res.status === 502) {
      throw new Error('Inspection failed, please try again.');
    } else if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Inspection request failed (${res.status})`);
    }

    const data = await res.json();
    state.currentInspection = data;
    renderResults(data, displayUrl);
    if (data.photo_status === 'ok' && data.items && data.items.length > 0) {
      triggerDecide();
    }
  } catch (err) {
    dom.inspectError.textContent = err.message;
    dom.inspectError.style.display = 'block';
    showToast(err.message, 'error');
  } finally {
    state.isInspecting = false;
    dom.inspectLoading.style.display = 'none';
    dom.btnInspect.disabled = false;
    updateShelfLock();
  }
}

export function setActiveItem(itemKey) {
  if (state.isCallInProgress) return;
  state.activeItemKey = itemKey;

  if (state.currentInspection) {
    renderItemsList(state.currentInspection);
    highlightActiveBox(state.activeItemKey);
  }

  renderActiveDecision();
  renderActiveBuyers();
  updateProgressBar();
}

export function highlightActiveBox(itemKey) {
  const boxes = dom.bboxOverlay.querySelectorAll('.bbox-rect');
  boxes.forEach(b => {
    if (b.dataset.itemKey === itemKey) {
      b.classList.add('active');
    } else {
      b.classList.remove('active');
    }
  });
}

export function renderItemsList(data) {
  dom.itemsContainer.replaceChildren();
  const items = data.items || [];
  dom.itemsSummaryCount.textContent = `${items.length} items detected`;

  if (items.length === 0) {
    const emptyMsg = document.createElement('div');
    emptyMsg.className = 'font-mono text-muted p-4';
    emptyMsg.textContent = data.photo_status === 'no_produce' ? 'No produce detected in this shelf photo.' : 'No items found.';
    dom.itemsContainer.appendChild(emptyMsg);
    return;
  }

  const decisionsMap = {};
  if (state.currentLadderResult && state.currentLadderResult.decisions) {
    state.currentLadderResult.decisions.forEach(d => {
      decisionsMap[d.item_key] = d;
    });
  }

  const ranked = rankItems(items, decisionsMap);
  if (!state.activeItemKey || !ranked.some(i => i.item_key === state.activeItemKey)) {
    state.activeItemKey = ranked[0].item_key;
  }

  ranked.forEach(item => {
    const isActive = item.item_key === state.activeItemKey;
    const row = document.createElement('div');
    row.className = 'item-row' + (isActive ? ' active' : '');
    row.dataset.itemKey = item.item_key;

    // Header Row
    const header = document.createElement('div');
    header.className = 'item-row-header';

    const titleGroup = document.createElement('div');
    titleGroup.className = 'item-title-group';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'item-name';
    nameSpan.textContent = item.name;
    titleGroup.appendChild(nameSpan);

    const stageChip = document.createElement('span');
    stageChip.className = 'chip chip-neutral chip-stage';
    const dot = document.createElement('span');
    dot.className = `dot dot-${item.stage}`;
    stageChip.appendChild(dot);
    const stageCap = item.stage ? item.stage.charAt(0).toUpperCase() + item.stage.slice(1) : '';
    stageChip.appendChild(document.createTextNode(stageCap));
    titleGroup.appendChild(stageChip);

    if (item.stage_level) {
      const cleanLevel = String(item.stage_level).replace(/^L/i, '').toLowerCase();
      const lvlSpan = document.createElement('span');
      lvlSpan.className = 'item-stage-level';
      lvlSpan.textContent = `${cleanLevel} stage`;
      titleGroup.appendChild(lvlSpan);
    }

    if (item.needs_staff_check) {
      const alertChip = document.createElement('span');
      alertChip.className = 'chip chip-warning';
      alertChip.textContent = 'Staff Check';
      titleGroup.appendChild(alertChip);
    }

    if (item.zoom_source_group) {
      const zChip = document.createElement('span');
      zChip.className = 'chip chip-indigo';
      zChip.textContent = 'Zoomed';
      titleGroup.appendChild(zChip);
    }

    header.appendChild(titleGroup);

    // Degradation Score Indicator
    const scoreWrap = document.createElement('div');
    scoreWrap.className = 'item-score-block';

    const scoreNum = document.createElement('div');
    scoreNum.className = 'item-score-num';
    scoreNum.textContent = item.score != null ? String(Math.round(item.score)) : '—';
    scoreWrap.appendChild(scoreNum);

    const scoreBarTrack = document.createElement('div');
    scoreBarTrack.className = 'item-score-bar-track';

    const scoreFill = document.createElement('div');
    scoreFill.className = `item-score-bar-fill fill-${item.stage}`;
    scoreFill.style.width = Math.min(100, Math.max(0, item.score || 0)) + '%';
    scoreBarTrack.appendChild(scoreFill);
    scoreWrap.appendChild(scoreBarTrack);

    header.appendChild(scoreWrap);
    row.appendChild(header);

    // Active Details Drawer
    if (isActive) {
      const details = document.createElement('div');
      details.className = 'item-row-details';

      // Degradation Evidence
      if (item.degradation_evidence && item.degradation_evidence.length > 0) {
        const evBox = document.createElement('div');
        evBox.className = 'evidence-box';

        const evTitle = document.createElement('div');
        evTitle.className = 'evidence-title';
        evTitle.textContent = 'Observed Degradation Evidence:';
        evBox.appendChild(evTitle);

        const ul = document.createElement('ul');
        ul.className = 'evidence-list';
        item.degradation_evidence.forEach(ev => {
          const li = document.createElement('li');
          li.textContent = ev;
          ul.appendChild(li);
        });
        evBox.appendChild(ul);
        details.appendChild(evBox);
      }

      // Issues Chips
      if (item.issues && item.issues.length > 0) {
        const issuesWrap = document.createElement('div');
        issuesWrap.className = 'issues-chips';
        item.issues.forEach(iss => {
          const chip = document.createElement('span');
          chip.className = 'chip chip-neutral';
          chip.textContent = iss.replace(/_/g, ' ');
          issuesWrap.appendChild(chip);
        });
        details.appendChild(issuesWrap);
      }

      // Definition Grid: 2-column grid of Observed, Estimated stock, Confidence, Change
      const defGrid = document.createElement('div');
      defGrid.className = 'item-def-grid';

      const addGridItem = (lblText, valText) => {
        const cell = document.createElement('div');
        cell.className = 'item-def-cell';
        const lbl = document.createElement('div');
        lbl.className = 'item-def-label';
        lbl.textContent = lblText;
        cell.appendChild(lbl);
        const val = document.createElement('div');
        val.className = 'item-def-value';
        val.textContent = valText || '—';
        cell.appendChild(val);
        defGrid.appendChild(cell);
      };

      addGridItem('Observed', formatObserved(item.observed) || '—');
      addGridItem('Estimated stock', formatQuantity(item.quantity) || '—');

      let confWord = '—';
      if (item.confidence_level) {
        confWord = item.confidence_level.charAt(0).toUpperCase() + item.confidence_level.slice(1).toLowerCase() + ' confidence';
      } else if (item.confidence != null) {
        confWord = item.confidence >= 0.8 ? 'High confidence' : (item.confidence >= 0.6 ? 'Medium confidence' : 'Low confidence');
      }
      addGridItem('Confidence', confWord);
      addGridItem('Change', item.change_notes || '—');

      details.appendChild(defGrid);

      // Staff Check Reasons
      if (item.needs_staff_check && item.staff_reasons && item.staff_reasons.length > 0) {
        const alertDiv = document.createElement('div');
        alertDiv.className = 'staff-alert-banner flex items-center gap-2';
        alertDiv.appendChild(icon('warning'));
        const reasons = item.staff_reasons.map(r => STAFF_REASON_LABELS[r] || r.replace(/_/g, ' ')).join(', ');
        const txt = document.createTextNode(` Staff check required: ${reasons}`);
        alertDiv.appendChild(txt);
        details.appendChild(alertDiv);
      }

      row.appendChild(details);
    }

    row.addEventListener('click', () => {
      setActiveItem(item.item_key);
    });

    dom.itemsContainer.appendChild(row);
  });
}

export function renderResults(data, imgSrc) {
  if (imgSrc) {
    dom.inspectedImage.src = imgSrc;
    state.currentDisplayUrl = imgSrc;
  }
  dom.bboxOverlay.replaceChildren();

  // Bounding Boxes on photo (D1: transparent fill, stage-colored border, white pill label with dot)
  if (data && data.items && data.items.length > 0) {
    data.items.forEach(item => {
      if (!item.position) return;
      const box = document.createElement('div');
      box.className = `bbox-rect box-${item.stage}`;
      box.dataset.itemKey = item.item_key;
      box.style.top = (item.position.ymin * 100) + '%';
      box.style.left = (item.position.xmin * 100) + '%';
      box.style.width = ((item.position.xmax - item.position.xmin) * 100) + '%';
      box.style.height = ((item.position.ymax - item.position.ymin) * 100) + '%';

      if (item.worst_stage === 'spoiled' || item.worst_stage === 'unsafe') {
        box.classList.add('bbox-worst');
      }

      const label = document.createElement('span');
      label.className = 'bbox-label';
      const dot = document.createElement('span');
      dot.className = `dot dot-${item.stage}`;
      label.appendChild(dot);
      const nameTxt = document.createTextNode(item.name);
      label.appendChild(nameTxt);
      box.appendChild(label);

      box.addEventListener('click', (e) => {
        e.stopPropagation();
        setActiveItem(item.item_key);
      });

      dom.bboxOverlay.appendChild(box);
    });
  }

  // Status banners
  if (data && data.photo_status !== 'ok') {
    dom.inspectStatusBanner.textContent = `Photo status: ${data.photo_status}. ${data.photo_note || ''}`;
    dom.inspectStatusBanner.style.display = 'block';
  } else {
    dom.inspectStatusBanner.style.display = 'none';
  }

  const hasInstruction = data && ((data.photo_issues && data.photo_issues.includes('instruction_text')) ||
    (data.items && data.items.some(i => i.issues && i.issues.includes('instruction_text'))));
  dom.inspectInstructionBanner.style.display = hasInstruction ? 'block' : 'none';

  // Section Footer Metadata
  if (data && data.inspector) {
    dom.inspectFooter.replaceChildren();
    const meta = data.inspector;
    const callsOrCached = meta.from_cache
      ? 'stored reading reused'
      : `calls: ${meta.calls}`;
    const metaItems = [
      `Model: ${meta.model}`,
      `Latency: ${meta.latency_ms} ms`,
      callsOrCached,
      `Hedges: ${meta.hedges || 0}`,
      `Zoomed: ${meta.zoomed_groups}`
    ];

    metaItems.forEach(text => {
      const span = document.createElement('span');
      span.textContent = text;
      dom.inspectFooter.appendChild(span);
    });
    dom.inspectFooter.style.display = 'flex';
  } else {
    dom.inspectFooter.style.display = 'none';
  }

  if (data) {
    dom.sectionAiReading.style.display = 'block';
    renderItemsList(data);
    highlightActiveBox(state.activeItemKey);
    renderActiveDecision();
    renderActiveBuyers();
    renderImpact();
  }
  updateShelfLock();
  updateProgressBar();
}
