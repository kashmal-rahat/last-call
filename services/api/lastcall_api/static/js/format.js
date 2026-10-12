// services/api/lastcall_api/static/js/format.js

export const STAFF_REASON_LABELS = {
  'spoiled_or_unsafe': 'spoiled or unsafe',
  'bad_pieces_in_group': 'some pieces bad',
  'low_confidence': 'low confidence',
  'unknown_produce': 'unknown produce',
  'mixed_crate': 'mixed crate',
  'model_flagged': 'flagged by AI',
  'safety_override': 'safety rule applied',
  'zoom_disagreement': 'close-up disagreed',
};

export const STAFF_ACTION_LABELS = {
  'remove_bad_pieces': 'remove bad pieces',
  'check_before_off_shelf': 'check before off-shelf',
  'identify_item': 'identify item',
  'approve_compost': 'approve compost',
  'enter_shelf_price': 'enter shelf price',
  'recheck_next_photo': 'recheck next photo',
};

// rankItems (from 63109cf verbatim)
export function rankItems(items, decisionsMap = null) {
  const stageSeverity = {
    'unsafe': 5,
    'spoiled': 4,
    'overripe': 3,
    'ripening': 2,
    'fresh': 1
  };

  function getTier(item) {
    if (decisionsMap && decisionsMap[item.item_key]) {
      const d = decisionsMap[item.item_key];
      if (d.step === 'compost') return 1;
      if (['bulk_sale', 'donate', 'animal_feed'].includes(d.step)) return 2;
      if (d.step === 'discount') return 3;
      if (d.on_hold || (d.staff_actions && d.staff_actions.length > 0) || item.needs_staff_check) return 4;
      if (d.step === 'keep') return 5;
      return 6;
    }
    if (['overripe', 'spoiled', 'unsafe'].includes(item.stage)) {
      return 1;
    }
    if (item.needs_staff_check) {
      return 2;
    }
    return 3;
  }

  function boxArea(pos) {
    if (!pos) return 0;
    return Math.max(0, (pos.ymax - pos.ymin) * (pos.xmax - pos.xmin));
  }

  return [...items].sort((a, b) => {
    const tierA = getTier(a);
    const tierB = getTier(b);
    if (tierA !== tierB) {
      return tierA - tierB;
    }
    const sevA = stageSeverity[a.stage] || 0;
    const sevB = stageSeverity[b.stage] || 0;
    if (sevA !== sevB) {
      return sevB - sevA;
    }
    return boxArea(b.position) - boxArea(a.position);
  });
}

// getStageColor (from 63109cf verbatim)
export function getStageColor(stage) {
  switch (stage) {
    case 'fresh': return '#10b981';
    case 'ripening': return '#f59e0b';
    case 'overripe': return '#f97316';
    case 'spoiled': return '#ef4444';
    case 'unsafe': return '#dc2626';
    default: return '#9ca3af';
  }
}

// formatObserved (from 63109cf verbatim)
export function formatObserved(obs) {
  if (!obs) return '';
  if (obs.method === 'count') {
    return obs.min === obs.max ? `about ${obs.min} pieces` : `about ${obs.min}–${obs.max} pieces`;
  }
  return obs.min === obs.max ? `about ${obs.min}% full` : `about ${obs.min}–${obs.max}% full`;
}

// formatQuantity (from 63109cf verbatim)
export function formatQuantity(qty) {
  if (!qty) return '';
  const unit = qty.unit || '';
  return qty.low === qty.high ? `${qty.low} ${unit}` : `${qty.low}–${qty.high} ${unit}`;
}

// formatUncertainFields (from 63109cf verbatim)
export function formatUncertainFields(fields) {
  if (!fields || fields.length === 0) return 'all fields agreed';
  const labelMap = {
    'fresh.sellable_for': 'fresh shelf life',
    'ripening.sellable_for': 'ripening shelf life',
    'overripe.sellable_for': 'overripe shelf life',
    'fresh.juice_shop': 'fresh juice shop',
    'ripening.juice_shop': 'ripening juice shop',
    'overripe.juice_shop': 'overripe juice shop',
    'fresh.restaurant': 'fresh restaurant',
    'ripening.restaurant': 'ripening restaurant',
    'overripe.restaurant': 'overripe restaurant',
    'fresh.bakery': 'fresh bakery',
    'ripening.bakery': 'ripening bakery',
    'overripe.bakery': 'overripe bakery',
    'fresh.charity': 'fresh charity',
    'ripening.charity': 'ripening charity',
    'overripe.charity': 'overripe charity',
    'overripe_ok_for_cattle': 'cattle overripe',
    'spoiled_ok_for_cattle': 'cattle spoiled',
  };
  const words = fields.map(f => labelMap[f] || f.replace('.', ' ').replace(/_/g, ' '));
  return 'uncertain: ' + words.join(', ');
}

// formatDecisionLine (from 63109cf verbatim, uses discounted_price and discount_pct)
export function formatDecisionLine(decision) {
  if (decision.step === 'keep') {
    return 'Stays at full price · re-checked at next photo';
  }
  if (decision.step === 'discount') {
    if (decision.shelf_price != null && decision.discounted_price != null) {
      return `Rs ${decision.shelf_price} → Rs ${decision.discounted_price} / ${decision.unit} (−${decision.discount_pct}%)`;
    }
    return `Needs shelf price (−${decision.discount_pct || 0}%)`;
  }
  if (decision.step === 'bulk_sale' || decision.step === 'animal_feed') {
    const buyerTypeLabels = {
      'juice_shop': 'juice shops',
      'restaurant': 'restaurants',
      'bakery': 'bakeries',
      'charity': 'charities',
      'dairy_farm': 'dairy farms'
    };
    let buyers = (decision.buyer_types || []).map(b => buyerTypeLabels[b] || b.replace('_', ' ')).join(', ');
    if (!buyers && decision.step === 'animal_feed') buyers = 'dairy farms';
    if (buyers) buyers = buyers.charAt(0).toUpperCase() + buyers.slice(1);

    let pricePart = '';
    if (decision.opening_price != null && decision.floor_price != null) {
      pricePart = `Opening Rs ${decision.opening_price}/${decision.unit} · floor Rs ${decision.floor_price}/${decision.unit} (never told to buyers)`;
    } else {
      pricePart = 'Needs shelf price';
    }

    let nextPart = '';
    if (decision.next_steps && decision.next_steps.length > 0) {
      nextPart = ` · Next: ${decision.next_steps.map(s => s.replace('_', ' ')).join(' → ')}`;
    }
    return `${buyers ? buyers + ' · ' : ''}${pricePart}${nextPart}`;
  }
  if (decision.step === 'donate') {
    let line = 'Free to charities';
    if (decision.next_steps && decision.next_steps.length > 0) {
      line += ' · Next: ' + decision.next_steps.map(s => s.replace('_', ' ')).join(' → ');
    }
    return line;
  }
  if (decision.step === 'compost') {
    return 'Needs manager approval';
  }
  return decision.step;
}

// formatProfileLine (from 63109cf verbatim)
export function formatProfileLine(decision) {
  const pName = decision.name || 'produce';
  if (decision.profile_source === 'manager') {
    return `Produce profile: ${pName} · Manager profile`;
  }
  if (decision.profile_source === 'fallback') {
    return `Produce profile: ${pName} · Generic fallback`;
  }
  const votes = decision.profile_votes || 5;
  const uncText = formatUncertainFields(decision.profile_uncertain_fields);
  return `Produce profile: ${pName} · Gemini, ${votes} votes · ${uncText}`;
}

export function getFindBuyersLabel(step) {
  if (step === 'donate') return 'Find charities on Google Maps';
  if (step === 'animal_feed') return 'Find cattle farms on Google Maps';
  return 'Find buyers on Google Maps';
}

// getNextStepTargetLabel (from 63109cf verbatim)
export function getNextStepTargetLabel(batch) {
  if (batch && batch.plans && batch.step_index + 1 < batch.plans.length) {
    const nextPlan = batch.plans[batch.step_index + 1];
    if (nextPlan.step === 'donate') return 'charities';
    if (nextPlan.step === 'animal_feed') return 'cattle farms';
    return nextPlan.step.replace(/_/g, ' ');
  }
  return 'next step';
}

// computeImpact (pure impact calculation per Step 9)
export function computeImpact(batchesMap) {
  let revenue = 0;
  const placedByUnit = {};
  const donatedByUnit = {};
  const feedByUnit = {};
  let dealsClosed = 0;
  let callsMade = 0;

  for (const k in batchesMap) {
    const b = batchesMap[k];
    if (!b || !b.attempts) continue;

    b.attempts.forEach(att => {
      if (att.call_status === 'completed') {
        callsMade++;
        if (att.outcome === 'deal' || att.outcome === 'partial_deal') {
          dealsClosed++;
          const u = b.unit || 'kg';
          const qty = att.agreed_quantity || 0;

          if (att.step === 'donate') {
            donatedByUnit[u] = (donatedByUnit[u] || 0) + qty;
          } else if (att.step === 'animal_feed') {
            feedByUnit[u] = (feedByUnit[u] || 0) + qty;
            revenue += (att.agreed_price || 0) * qty;
          } else {
            revenue += (att.agreed_price || 0) * qty;
          }
          placedByUnit[u] = (placedByUnit[u] || 0) + qty;
        }
      }
    });
  }

  for (const u in placedByUnit) {
    placedByUnit[u] = Math.round((placedByUnit[u] + Number.EPSILON) * 100) / 100;
  }
  for (const u in donatedByUnit) {
    donatedByUnit[u] = Math.round((donatedByUnit[u] + Number.EPSILON) * 100) / 100;
  }
  for (const u in feedByUnit) {
    feedByUnit[u] = Math.round((feedByUnit[u] + Number.EPSILON) * 100) / 100;
  }

  return {
    revenue: Math.round(revenue),
    placedByUnit,
    donatedByUnit,
    feedByUnit,
    callsMade,
    dealsClosed
  };
}
