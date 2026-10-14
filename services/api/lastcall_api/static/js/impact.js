import * as dom from './dom.js';
import { state } from './state.js';
import { computeImpact } from './format.js';

export function renderImpact() {
  const { revenue, placedByUnit, donatedByUnit, feedByUnit, callsMade, dealsClosed } = computeImpact(state.currentBatchesMap);

  function formatQty(n, unit) {
    const rounded = Math.round((n + Number.EPSILON) * 100) / 100;
    return `${rounded}\u00A0${unit}`;
  }

  if (dom.impactRevenue) {
    dom.impactRevenue.textContent = `Rs\u00A0${revenue.toLocaleString()}`;
  }

  if (dom.impactRescued) {
    const rescuedParts = Object.entries(placedByUnit).map(([u, q]) => formatQty(q, u));
    dom.impactRescued.textContent = rescuedParts.length > 0 ? rescuedParts.join(', ') : '0';
  }

  if (dom.impactDonated) {
    const donatedParts = Object.entries(donatedByUnit).map(([u, q]) => formatQty(q, u));
    dom.impactDonated.textContent = donatedParts.length > 0 ? donatedParts.join(', ') : '0';
  }

  if (dom.impactFeed) {
    const feedParts = Object.entries(feedByUnit).map(([u, q]) => formatQty(q, u));
    dom.impactFeed.textContent = feedParts.length > 0 ? feedParts.join(', ') : '0';
  }

  if (dom.impactCalls) {
    dom.impactCalls.textContent = String(callsMade);
  }

  if (dom.impactDeals) {
    dom.impactDeals.textContent = String(dealsClosed);
  }

  if (dom.impactHint) {
    if (dealsClosed === 0) {
      dom.impactHint.style.display = 'inline';
      dom.impactHint.textContent = 'Start a call to see the impact here. ';
    } else {
      dom.impactHint.style.display = 'none';
    }
  }
}
