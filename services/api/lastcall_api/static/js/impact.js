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
  const { revenue, placedByUnit, donatedByUnit, feedByUnit, callsMade, dealsClosed } = computeImpact(state.currentBatchesMap);

  dom.impactRevenue.textContent = `Rs ${revenue.toLocaleString()}`;
  dom.impactRescued.textContent = quantities(placedByUnit) || '0';

  // How the placed stock went: the parts given to charities or sold as feed; the rest went to businesses
  const donated = quantities(donatedByUnit);
  const feed = quantities(feedByUnit);
  const ways = [donated && `${donated} donated`, feed && `${feed} as animal feed`].filter(Boolean);
  dom.impactPlacedDetail.textContent = ways.length > 0 ? ways.join(' · ') : (dealsClosed > 0 ? 'all sold to businesses' : '');

  dom.impactCalls.textContent = String(callsMade);
  dom.impactDeals.textContent = String(dealsClosed);

  if (dom.impactHint) {
    dom.impactHint.style.display = dealsClosed === 0 ? 'inline' : 'none';
  }
}
