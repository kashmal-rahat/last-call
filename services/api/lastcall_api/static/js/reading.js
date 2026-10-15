// services/api/lastcall_api/static/js/reading.js

import { state } from './state.js';
import * as dom from './dom.js';
import { accessCode, apiFetch, errorMessage } from './api.js';
import { setStoredItem, getOrCreateShelfId } from './storage.js';
import {
  rankItems, formatQuantity, formatChange, formatStockBasis, freshnessPosition, readingSummary,
  FRESHNESS_STAGES, STAFF_REASON_LABELS,
} from './format.js';
import { icon, scrollToSection } from './ui.js';
import { updateShelfLock } from './lock.js';
import { triggerDecide, renderActiveDecision } from './decision.js';
import { renderActiveBuyers } from './buyers.js';
import { renderImpact } from './impact.js';
import { resetCallPanel } from './call.js';

export async function handleInspect() {
  const code = accessCode();
  if (!code) {
    dom.inspectError.textContent = 'Please enter the Demo Access Code.';
    dom.inspectError.style.display = 'block';
    dom.inspectAccessCodeEl.focus();
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
  resetCallPanel();  // the old call belonged to the previous reading
  updateShelfLock();

  const scrollYAtStart = window.scrollY;
  let readingShown = false;

  const shelfId = getOrCreateShelfId();
  const formData = new FormData();
  formData.append('photo', photoFile, 'shelf_photo.jpg');
  formData.append('shelf_id', shelfId);

  try {
    const res = await apiFetch('/demo/inspect', { method: 'POST', form: formData });

    if (res.status === 401) {
      throw new Error("Invalid access code. You'll find it in our submission deck.");
    } else if (res.status === 415) {
      throw new Error('Please upload a JPEG or PNG photo.');
    } else if (res.status === 413) {
      throw new Error('Image exceeds maximum upload size (8\u00A0MB).');
    } else if (res.status === 429) {
      throw new Error(await errorMessage(res, 'Rate limit reached. Please try again later.'));
    } else if (res.status === 503) {
      // Gemini busy or slow (the server says so); a 503 from elsewhere gets a neutral message, not a guess
      throw new Error(await errorMessage(res, 'The service is busy right now. Please try again in a minute.'));
    } else if (res.status === 502) {
      throw new Error('Inspection failed, please try again.');
    } else if (!res.ok) {
      throw new Error(await errorMessage(res, `Inspection request failed (${res.status})`));
    }

    const data = await res.json();
    state.currentInspection = data;
    renderResults(data, displayUrl);
    readingShown = true;
    if (data.photo_status === 'ok' && data.items && data.items.length > 0) {
      triggerDecide();
    }
  } catch (err) {
    dom.inspectError.textContent = err.message;
    dom.inspectError.style.display = 'block';
  } finally {
    state.isInspecting = false;
    dom.inspectLoading.style.display = 'none';
    dom.btnInspect.disabled = false;
    updateShelfLock();
  }
  // After the loading box is gone, so the layout above the reading no longer shifts
  if (readingShown) revealReading(scrollYAtStart);
}

// Takes the judge to the new reading by focusing its heading (the usual pattern after new content:
// keyboard and screen-reader users land there too). Left alone if they scrolled elsewhere while waiting.
function revealReading(scrollYAtStart) {
  if (Math.abs(window.scrollY - scrollYAtStart) > 40) return;
  const top = dom.sectionAiReading.getBoundingClientRect().top;
  if (top < 0 || top > 120) {  // 120: already just under the sticky header (scroll-margin-top 80 px)
    scrollToSection(dom.sectionAiReading);
  }
  dom.readingHeading.focus({ preventScroll: true });
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

  ranked.forEach((item, idx) => {
    const isActive = item.item_key === state.activeItemKey;
    const row = document.createElement('div');
    row.className = 'item-row' + (isActive ? ' active' : '');
    row.dataset.itemKey = item.item_key;
    const detailsId = `itemDetails${idx}`;

    // Header (a disclosure button, so the keyboard can open items): name, stage chip, level; score on the right
    const header = document.createElement('button');
    header.type = 'button';
    header.className = 'item-row-header';
    header.setAttribute('aria-expanded', isActive ? 'true' : 'false');
    if (isActive) header.setAttribute('aria-controls', detailsId);

    const head = document.createElement('div');
    head.className = 'item-head';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'item-name';
    nameSpan.textContent = displayName(item.name);
    head.appendChild(nameSpan);

    // The verdict, in the header of every item: "● Overripe · mid stage" (the open card's scale shows where)
    const stageChip = document.createElement('span');
    stageChip.className = 'chip chip-stage';
    const dot = document.createElement('span');
    dot.className = `dot dot-${item.stage}`;
    stageChip.appendChild(dot);
    stageChip.appendChild(document.createTextNode(displayName(item.stage || '')));
    if (item.stage_level) {
      const lvl = document.createElement('span');
      lvl.className = 'chip-stage-level';
      lvl.textContent = ` · ${String(item.stage_level).toLowerCase()} stage`;
      stageChip.appendChild(lvl);
    }
    head.appendChild(stageChip);

    if (item.needs_staff_check) {
      const alertChip = document.createElement('span');
      alertChip.className = 'chip chip-amber';
      alertChip.textContent = 'Staff check';
      head.appendChild(alertChip);
    }
    header.appendChild(head);

    const scoreWrap = document.createElement('div');
    scoreWrap.className = 'item-score-block';
    const scoreNum = document.createElement('div');
    scoreNum.className = 'item-score-num';
    scoreNum.textContent = item.score != null ? String(Math.round(item.score)) : '—';
    if (item.score != null) {
      const outOf = document.createElement('span');
      outOf.className = 'item-score-outof';
      outOf.textContent = '/100';
      scoreNum.appendChild(outOf);
    }
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

    // Active item: evidence, issue tags, facts grid, staff check
    if (isActive) {
      const details = document.createElement('div');
      details.className = 'item-row-details';
      details.id = detailsId;

      if (item.evidence) {
        const ev = document.createElement('p');
        ev.className = 'item-evidence';
        ev.textContent = item.evidence;
        details.appendChild(ev);
      }

      if (item.zoomed) {
        const zoomNote = document.createElement('p');
        zoomNote.className = 'item-zoom-note';
        zoomNote.append(icon('sparkle'), 'Zoomed in for a closer look');
        details.appendChild(zoomNote);
      }

      const scale = renderFreshnessScale(item);
      if (scale) details.appendChild(scale);

      const defGrid = document.createElement('div');
      defGrid.className = 'item-def-grid';
      const addGridItem = (lblText, valText, detailText = '', valClass = '') => {
        const cell = document.createElement('div');
        cell.className = 'item-def-cell';
        const lbl = document.createElement('div');
        lbl.className = 'item-def-label';
        lbl.textContent = lblText;
        cell.appendChild(lbl);
        const val = document.createElement('div');
        val.className = 'item-def-value';
        val.textContent = valText || '—';
        if (valClass) val.classList.add(valClass);
        cell.appendChild(val);
        if (detailText) {
          const sub = document.createElement('div');
          sub.className = 'item-def-detail';
          sub.textContent = detailText;
          cell.appendChild(sub);
        }
        defGrid.appendChild(cell);
      };
      addGridItem('Stock', formatQuantity(item.quantity) || '—', formatStockBasis(item.observed));
      const confWord = item.confidence_level ? displayName(item.confidence_level.toLowerCase()) : '—';
      addGridItem('Confidence', confWord);
      const change = formatChange(item, Boolean(data.previous_inspection_id));
      addGridItem('Since last photo', change.value, change.detail, `trend-${change.trend}`);
      details.appendChild(defGrid);

      if (item.needs_staff_check) {
        const alertDiv = document.createElement('div');
        alertDiv.className = 'item-staff-alert';
        alertDiv.appendChild(icon('warning'));
        const reasons = (item.staff_check_reasons || [])
          .map(r => STAFF_REASON_LABELS[r] || r.replace(/_/g, ' '));
        const text = document.createElement('span');
        text.textContent = item.check_reason || (reasons.length ? `Staff check: ${reasons.join(', ')}` : 'Staff check needed');
        alertDiv.appendChild(text);
        details.appendChild(alertDiv);
      }

      row.appendChild(details);
    }

    row.addEventListener('click', () => {
      setActiveItem(item.item_key);
    });
    // Keyboard: the list is rebuilt, so put focus back on the item just opened
    header.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      setActiveItem(item.item_key);
      dom.itemsContainer.querySelector(`[data-item-key="${CSS.escape(item.item_key)}"] .item-row-header`)?.focus();
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
      const nameTxt = document.createTextNode(displayName(item.name));
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

  // Section footer: how the reading was made, in words
  if (data && data.inspector) {
    const line = document.createElement('span');
    line.textContent = readingSummary(data.inspector);
    dom.inspectFooter.replaceChildren(icon('sparkle'), line);
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
}

// Fresh → Unsafe in the stage colours, the item's stage solid and a marker where it sits (early/mid/late).
// One picture of what the score means; screen readers get the same as a sentence.
function renderFreshnessScale(item) {
  const pos = freshnessPosition(item.stage, item.stage_level);
  if (pos == null) return null;

  const scale = document.createElement('div');
  scale.className = 'freshness-scale';
  scale.setAttribute('role', 'img');
  const level = item.stage_level ? `, ${item.stage_level} stage` : '';
  const score = item.score != null ? `, score ${Math.round(item.score)} of 100` : '';
  scale.setAttribute('aria-label', `Freshness: ${item.stage}${level}${score}`);

  const track = document.createElement('div');
  track.className = 'freshness-track';
  const labels = document.createElement('div');
  labels.className = 'freshness-labels';
  FRESHNESS_STAGES.forEach(stage => {
    const current = stage === item.stage ? ' is-current' : '';
    const seg = document.createElement('span');
    seg.className = `freshness-seg seg-${stage}${current}`;
    track.appendChild(seg);
    const lbl = document.createElement('span');
    lbl.className = `freshness-label${current}${current ? ` label-${stage}` : ''}`;
    lbl.textContent = displayName(stage);
    labels.appendChild(lbl);
  });
  const marker = document.createElement('span');
  marker.className = `freshness-marker marker-${item.stage}`;
  marker.style.left = `${(pos * 100).toFixed(1)}%`;
  track.appendChild(marker);

  scale.append(track, labels);
  return scale;
}

// Produce names and words arrive in lower case; capitalise the first letter for display only.
function displayName(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
}
