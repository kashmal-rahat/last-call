// services/api/lastcall_api/static/js/decision.js

import { state } from './state.js';
import * as dom from './dom.js';
import { accessCode, apiFetch, errorMessage } from './api.js';
import { formatDecisionLine, formatProfileLine, STAFF_ACTION_LABELS } from './format.js';
import { icon } from './ui.js';
import { renderResults } from './reading.js';

// One cell of the price strip: a quiet label over the price, "Rs 180 /dozen"
function priceCell(label, value, unit = '', iconName = null) {
  const cell = document.createElement('div');
  cell.className = 'price-cell';

  const lbl = document.createElement('div');
  lbl.className = 'price-cell-label';
  if (iconName) lbl.appendChild(icon(iconName));
  lbl.appendChild(document.createTextNode(label));

  const val = document.createElement('div');
  val.className = 'price-cell-value';
  val.textContent = value;
  if (unit) {
    const u = document.createElement('span');
    u.className = 'price-cell-unit';
    u.textContent = '/' + unit;
    val.appendChild(u);
  }

  cell.append(lbl, val);
  return cell;
}

// On a phone the six steps don't fit: scroll the row (never the page) so the chosen step is in the middle
function centreActiveStep() {
  const trail = dom.ladderStepper;
  const active = trail.querySelector('.step-active');
  if (active && trail.scrollWidth > trail.clientWidth) {
    trail.scrollLeft = active.offsetLeft - (trail.clientWidth - active.offsetWidth) / 2;
  }
  updateStepperFade();
}

// Fade the edge that has more steps beyond it, so the row reads as one that scrolls
export function updateStepperFade() {
  const trail = dom.ladderStepper;
  const hidden = trail.scrollWidth - trail.clientWidth;
  trail.classList.toggle('fade-start', hidden > 1 && trail.scrollLeft > 1);
  trail.classList.toggle('fade-end', hidden > 1 && trail.scrollLeft < hidden - 1);
}

export async function triggerDecide() {
  if (!state.currentInspection || !state.currentInspection.inspection_id) return;
  if (!accessCode()) return;

  const thisRequestId = ++state.decideRequestCounter;
  state.isDeciding = true;
  state.scoutResultsMap = {};
  state.scoutErrorsMap = {};
  state.scoutLoadingMap = {};
  dom.decideError.style.display = 'none';
  dom.decideError.textContent = '';
  renderResults(state.currentInspection, state.currentDisplayUrl);

  const hoursVal = dom.closingTimeSelect.value ? parseFloat(dom.closingTimeSelect.value) : null;
  const payload = {
    inspection_id: state.currentInspection.inspection_id,
    hours_until_closing: hoursVal,
    price_overrides: Object.keys(state.priceOverrides).length > 0 ? state.priceOverrides : null
  };

  try {
    const res = await apiFetch('/demo/decide', { method: 'POST', json: payload });

    if (thisRequestId !== state.decideRequestCounter) return;

    if (res.ok) {
      state.currentLadderResult = await res.json();
      dom.decideError.style.display = 'none';
      dom.decideError.textContent = '';
    } else {
      state.currentLadderResult = null;
      dom.decideError.textContent = await errorMessage(
        res,
        res.status === 429 ? 'Hourly limit reached. Please try again later.' : 'Decision failed, please try again.'
      );
      dom.decideError.style.display = 'block';
    }
  } catch (err) {
    if (thisRequestId !== state.decideRequestCounter) return;
    state.currentLadderResult = null;
    dom.decideError.textContent = err.message || 'Decision failed, please try again.';
    dom.decideError.style.display = 'block';
  } finally {
    if (thisRequestId === state.decideRequestCounter) {
      state.isDeciding = false;
      renderResults(state.currentInspection, state.currentDisplayUrl);
    }
  }
}

export function renderActiveDecision() {
  if (!state.currentInspection || !state.activeItemKey || !state.currentLadderResult) {
    dom.sectionDecision.style.display = 'none';
    return;
  }

  const decision = state.currentLadderResult.decisions
    ? state.currentLadderResult.decisions.find(d => d.item_key === state.activeItemKey)
    : null;

  if (!decision) {
    dom.sectionDecision.style.display = 'none';
    return;
  }

  dom.sectionDecision.style.display = 'block';

  // Header Chips
  const activeItemObj = state.currentInspection.items.find(i => i.item_key === state.activeItemKey);
  if (dom.decisionSectionSubtitle) {
    const raw = activeItemObj ? activeItemObj.name : 'this produce';
    const itmName = raw.charAt(0).toUpperCase() + raw.slice(1);
    dom.decisionSectionSubtitle.textContent = `What happens to ${itmName}, with prices set by the mart's rules.`;
  }

  // Hours to closing as used by the decision (real clock, or the closing-time choice)
  const hoursLeft = state.currentLadderResult.hours_until_closing;
  dom.decisionRunwayChip.textContent = hoursLeft != null
    ? `${hoursLeft < 1 ? hoursLeft.toFixed(1) : Math.round(hoursLeft)} h to closing`
    : '';

  // Stepper
  const steps = dom.ladderStepper.querySelectorAll('.ladder-step');
  steps.forEach(st => {
    st.classList.remove('step-active', 'step-next', 'step-disabled');
    const sName = st.dataset.step;
    if (decision.step === sName) {
      st.classList.add('step-active');
    } else if (decision.next_steps && decision.next_steps.includes(sName)) {
      st.classList.add('step-next');
    } else if (decision.allowed_steps && !decision.allowed_steps.includes(sName)) {
      st.classList.add('step-disabled');
    }
  });
  centreActiveStep();

  // Price strip: the prices this step uses, all derived from the shelf price (D41)
  const unitStr = decision.unit || 'kg';
  const rs = v => (v != null ? `Rs ${v}` : '—');
  const needsPrice = decision.shelf_price == null && ['keep', 'discount', 'bulk_sale', 'animal_feed'].includes(decision.step);
  let cells = [];
  if (needsPrice) {
    const cell = priceCell('Shelf price', 'Price not set');
    cell.classList.add('is-unset');
    const hint = document.createElement('p');
    hint.className = 'price-cell-hint';
    // Also covers an item that is on the list in the other unit (kg vs dozen): prices are never converted (D4)
    hint.textContent = `No price per ${unitStr} on the mart's list yet. Enter it below.`;
    cell.appendChild(hint);
    cells = [cell];
  } else if (decision.step === 'keep') {
    cells = [priceCell('Stays at full price', rs(decision.shelf_price), unitStr)];
  } else if (decision.step === 'discount') {
    cells = [
      priceCell('Shelf price', rs(decision.shelf_price), unitStr),
      priceCell(`Discounted · ${decision.discount_pct ?? 0}% off`, rs(decision.discounted_price), unitStr),
    ];
  } else if (['bulk_sale', 'animal_feed'].includes(decision.step)) {
    cells = [
      priceCell('Shelf price', rs(decision.shelf_price), unitStr),
      priceCell('AI opening offer', rs(decision.opening_price), unitStr),
      priceCell('Floor · never told to the AI', rs(decision.floor_price), unitStr, 'lock'),
    ];
  } else if (decision.step === 'donate') {
    cells = [priceCell('Donation', 'Free to charities')];
  }
  // Compost has no price: the sentence above says why, and the strip stays hidden (:empty)
  dom.decisionPriceCards.replaceChildren(...cells);

  dom.decisionReasonLine.textContent = decision.reason || formatDecisionLine(decision);
  dom.decisionProfileLine.replaceChildren(icon('sparkle'), document.createTextNode(formatProfileLine(decision)));

  dom.decisionBadgesRow.replaceChildren();
  if (decision.on_hold) {
    const b = document.createElement('span');
    b.className = 'chip chip-amber';
    b.appendChild(icon('warning'));
    b.appendChild(document.createTextNode(' On hold until staff check'));
    dom.decisionBadgesRow.appendChild(b);
  }

  if (decision.needs_approval) {
    const b = document.createElement('span');
    b.className = 'chip chip-rose';
    b.textContent = 'Needs manager approval';
    dom.decisionBadgesRow.appendChild(b);
  }

  if (decision.staff_actions && decision.staff_actions.length > 0) {
    // Skip actions the page already says: the status chips above and the strip's "Price not set"
    const shown = new Set([
      ...(decision.on_hold ? ['check_before_off_shelf'] : []),
      ...(decision.needs_approval ? ['approve_compost'] : []),
      ...(needsPrice ? ['enter_shelf_price'] : []),
    ]);
    decision.staff_actions.filter(act => !shown.has(act)).forEach(act => {
      const b = document.createElement('span');
      b.className = 'chip';
      b.textContent = STAFF_ACTION_LABELS[act] || act.replace(/_/g, ' ');
      dom.decisionBadgesRow.appendChild(b);
    });
  }

  // Shelf price override: the current price is shown in the strip, so the row only offers a change.
  // Compost has no price to change (donate keeps it: the market value goes into Impact)
  dom.decisionPriceOverrideRow.style.display = decision.step === 'compost' ? 'none' : '';
  const hasPrice = decision.shelf_price != null;
  dom.activeItemShelfPriceLabel.textContent = hasPrice ? 'Change shelf price (Rs)' : 'Shelf price (Rs)';
  dom.activeItemShelfPriceInput.placeholder = hasPrice ? 'New price' : 'Enter price';
  if (state.priceOverrides[decision.item_key]) {
    dom.activeItemShelfPriceInput.value = String(state.priceOverrides[decision.item_key]);
  } else {
    dom.activeItemShelfPriceInput.value = '';
  }
}
