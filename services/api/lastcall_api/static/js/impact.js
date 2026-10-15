import * as dom from './dom.js';
import { state } from './state.js';
import { computeImpact } from './format.js';

// "2.5 dozen, 3 kg": one quantity per unit (items can be sold by different units), zeros left out
function quantities(byUnit) {
  return Object.entries(byUnit)
    .filter(([, q]) => q > 0)
    .map(([unit, q]) => `${Math.round((q + Number.EPSILON) * 100) / 100} ${unit}`)
    .join(', ');
}

export function renderImpact() {
  if (!dom.impactRevenue) return;
  // Shown with the other results: before a reading there is nothing to count (and sections 2–5 are hidden)
  dom.sectionImpact.style.display = state.currentInspection ? 'block' : 'none';
  const { revenue, placedByUnit, callsMade, dealsClosed } = computeImpact(state.currentBatchesMap);

  dom.impactRevenue.textContent = `Rs ${revenue.toLocaleString()}`;
  dom.impactRescued.textContent = quantities(placedByUnit) || '0';

  dom.impactCalls.textContent = String(callsMade);
  dom.impactDeals.textContent = String(dealsClosed);

  if (dom.impactHint) {
    dom.impactHint.style.display = dealsClosed === 0 ? 'inline' : 'none';
  }
}
