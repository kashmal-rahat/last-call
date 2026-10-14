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
  if (step === 'bulk_sale') return 'Find juice shops & bakeries';
  if (step === 'animal_feed') return 'Find cattle farms';
  if (step === 'donate') return 'Find charities';
  return 'Find buyers';
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

// "Since last photo": the change as a value, a trend for its colour, and a quiet detail ("since 20:30"). matching.py writes change_note as
// "dropped 9 points since the last photo (today 20:30)[; worst pieces now spoiled]".
export function formatChange(item, hadPreviousPhoto) {
  if (item.change_since_last == null) {
    return { value: hadPreviousPhoto ? 'New on this shelf' : 'First photo of this shelf', trend: 'none', detail: '' };
  }
  const delta = Number(item.change_since_last);
  const points = Math.abs(delta) === 1 ? 'point' : 'points';
  const value = delta < 0 ? `−${Math.abs(delta)} ${points}` : delta > 0 ? `+${delta} ${points}` : 'No change';
  const trend = delta < 0 ? 'down' : delta > 0 ? 'up' : 'flat';
  const note = item.change_note || '';
  const when = note.match(/\(([^)]+)\)/);
  const worse = note.match(/;\s*(worst pieces now \w+)/);
  const since = when ? `since ${when[1].replace(/^today /, '')}` : ''; // "today 20:30" -> "20:30"
  const detail = [since, worse ? worse[1] : ''].filter(Boolean).join(' · ');
  return { value, trend, detail };
}

// What the stock estimate is based on, for the line under it: "25–34 pieces" or "container 60–80% full".
export function formatStockBasis(obs) {
  if (!obs) return '';
  const range = obs.min === obs.max ? `${obs.min}` : `${obs.min}–${obs.max}`;
  return obs.method === 'count' ? `${range} pieces` : `container ${range}% full`;
}

// Where an item sits on the Fresh → Unsafe scale (0 to 1): its stage's fifth, and early/mid/late inside it.
export const FRESHNESS_STAGES = ['fresh', 'ripening', 'overripe', 'spoiled', 'unsafe'];
export function freshnessPosition(stage, level) {
  const idx = FRESHNESS_STAGES.indexOf(stage);
  if (idx < 0) return null;
  const within = { early: 0.2, mid: 0.5, late: 0.8 }[level] ?? 0.5;
  return (idx + within) / FRESHNESS_STAGES.length;
}

// The reading's footer in words: "Read by Gemini 3.8 Flash · 7.4 s · 2 calls · 1 zoomed in", or the cached case.
// The raw numbers stay in the API response.
export function readingSummary(meta) {
  const model = (meta.model || 'Gemini')
    .split('-')
    .map(w => (/^[a-z]/.test(w) ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ');
  if (meta.from_cache) return `Read by ${model} · same photo as before, stored reading reused`;
  const parts = [`Read by ${model}`, `${(meta.latency_ms / 1000).toFixed(1)} s`];
  parts.push(`${meta.calls} ${meta.calls === 1 ? 'call' : 'calls'}`);
  if (meta.zoomed_groups) parts.push(`${meta.zoomed_groups} zoomed in`);
  if (meta.hedges) parts.push(`${meta.hedges} hedged`);
  return parts.join(' · ');
}
