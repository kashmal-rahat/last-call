// services/api/lastcall_api/static/js/decision.js

import { state } from './state.js';
import * as dom from './dom.js';
import { accessCode, apiFetch, errorMessage } from './api.js';
import { formatDecisionLine, formatProfileLine, STAFF_ACTION_LABELS } from './format.js';
import { icon } from './ui.js';
import { renderResults } from './reading.js';

export function createPriceCard(label, valText, unitText, extraClass = '', iconName = null) {
  const card = document.createElement('div');
  card.className = 'price-card' + (extraClass ? ' ' + extraClass : '');

  const lbl = document.createElement('div');
  lbl.className = 'price-card-label';
  if (iconName) {
    lbl.appendChild(icon(iconName));
    lbl.appendChild(document.createTextNode(' ' + label));
  } else {
    lbl.textContent = label;
  }
  card.appendChild(lbl);

  const val = document.createElement('div');
  val.className = 'price-card-value';
  val.textContent = valText;

  if (unitText) {
    const unitSpan = document.createElement('span');
    unitSpan.className = 'price-card-unit';
    unitSpan.textContent = ' /' + unitText;
    val.appendChild(document.createTextNode(' '));
    val.appendChild(unitSpan);
  }
  card.appendChild(val);
  return card;
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

  // Price Cards
  dom.decisionPriceCards.replaceChildren();
  const unitStr = decision.unit || 'kg';

  if (decision.step === 'discount') {
    const c1 = createPriceCard('Shelf price', 'Rs ' + (decision.shelf_price != null ? decision.shelf_price : '—'), unitStr);
    const discPct = decision.discount_pct != null ? decision.discount_pct : 0;
    const discPrice = decision.discounted_price != null ? decision.discounted_price : '—';
    const c2 = createPriceCard(`Discounted (−${discPct}%)`, 'Rs ' + discPrice, unitStr, 'card-emerald');
    dom.decisionPriceCards.appendChild(c1);
    dom.decisionPriceCards.appendChild(c2);
  } else if (['bulk_sale', 'animal_feed'].includes(decision.step)) {
    const c1 = createPriceCard('Shelf price', 'Rs ' + (decision.shelf_price != null ? decision.shelf_price : '—'), unitStr);
    const c2 = createPriceCard('AI opening offer', 'Rs ' + (decision.opening_price != null ? decision.opening_price : '—'), unitStr, 'card-indigo');
    const c3 = createPriceCard('Floor · never told to the AI', 'Rs ' + (decision.floor_price != null ? decision.floor_price : '—'), unitStr, 'card-emerald', 'lock');
    dom.decisionPriceCards.appendChild(c1);
    dom.decisionPriceCards.appendChild(c2);
    dom.decisionPriceCards.appendChild(c3);
  } else if (decision.step === 'donate') {
    const c1 = createPriceCard('Donation', 'Free to charities', '', 'card-indigo');
    dom.decisionPriceCards.appendChild(c1);
  } else if (decision.step === 'keep') {
    const c1 = createPriceCard('Stays at full price', 'Rs ' + (decision.shelf_price != null ? decision.shelf_price : '—'), unitStr, 'card-emerald');
    dom.decisionPriceCards.appendChild(c1);
  } else {
    const c1 = createPriceCard(decision.step || 'Status', decision.reason || '—', '');
    dom.decisionPriceCards.appendChild(c1);
  }

  dom.decisionReasonLine.textContent = decision.reason || formatDecisionLine(decision);
  dom.decisionProfileLine.textContent = formatProfileLine(decision);

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
    decision.staff_actions.forEach(act => {
      const b = document.createElement('span');
      b.className = 'chip';
      b.textContent = STAFF_ACTION_LABELS[act] || act.replace(/_/g, ' ');
      dom.decisionBadgesRow.appendChild(b);
    });
  }

  // Shelf price override input
  dom.activeItemShelfPriceInput.placeholder = decision.shelf_price ? String(decision.shelf_price) : 'Enter price';
  if (state.priceOverrides[decision.item_key]) {
    dom.activeItemShelfPriceInput.value = String(state.priceOverrides[decision.item_key]);
  } else {
    dom.activeItemShelfPriceInput.value = '';
  }
}
