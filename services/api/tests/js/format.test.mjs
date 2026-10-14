// services/api/tests/js/format.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  computeImpact,
  rankItems,
  getStageColor,
  formatObserved,
  formatQuantity,
  formatChange,
  formatStockBasis,
  readingSummary,
  freshnessPosition,
  formatUncertainFields,
  formatDecisionLine,
  formatProfileLine,
  getFindBuyersLabel,
  getNextStepTargetLabel
} from '../../lastcall_api/static/js/format.js';

test('computeImpact: zero batches -> zero metrics', () => {
  const result = computeImpact({});
  assert.equal(result.revenue, 0);
  assert.deepEqual(result.placedByUnit, {});
  assert.deepEqual(result.donatedByUnit, {});
  assert.deepEqual(result.feedByUnit, {});
  assert.equal(result.callsMade, 0);
  assert.equal(result.dealsClosed, 0);
});

test('computeImpact: one deal batch -> revenue matches price*qty and placedByUnit updated', () => {
  const batches = {
    b1: {
      unit: 'kg',
      attempts: [
        {
          call_status: 'completed',
          outcome: 'deal',
          agreed_quantity: 15,
          agreed_price: 100,
          step: 'bulk_sale'
        }
      ]
    }
  };
  const result = computeImpact(batches);
  assert.equal(result.revenue, 1500);
  assert.deepEqual(result.placedByUnit, { kg: 15 });
  assert.equal(result.dealsClosed, 1);
  assert.equal(result.callsMade, 1);
});

test('computeImpact: donate batch -> revenue 0, donatedByUnit updated', () => {
  const batches = {
    b1: {
      unit: 'kg',
      attempts: [
        {
          call_status: 'completed',
          outcome: 'deal',
          agreed_quantity: 20,
          agreed_price: 0,
          step: 'donate'
        }
      ]
    }
  };
  const result = computeImpact(batches);
  assert.equal(result.revenue, 0);
  assert.deepEqual(result.donatedByUnit, { kg: 20 });
  assert.deepEqual(result.placedByUnit, { kg: 20 });
  assert.equal(result.dealsClosed, 1);
  assert.equal(result.callsMade, 1);
});

test('computeImpact: animal_feed batch -> revenue matches and feedByUnit updated', () => {
  const batches = {
    b1: {
      unit: 'kg',
      attempts: [
        {
          call_status: 'completed',
          outcome: 'deal',
          agreed_quantity: 30,
          agreed_price: 25,
          step: 'animal_feed'
        }
      ]
    }
  };
  const result = computeImpact(batches);
  assert.equal(result.revenue, 750);
  assert.deepEqual(result.feedByUnit, { kg: 30 });
  assert.deepEqual(result.placedByUnit, { kg: 30 });
  assert.equal(result.dealsClosed, 1);
  assert.equal(result.callsMade, 1);
});

test('computeImpact: declines -> callsMade incremented but dealsClosed and revenue untouched', () => {
  const batches = {
    b1: {
      unit: 'kg',
      attempts: [
        {
          call_status: 'completed',
          outcome: 'declined',
          agreed_quantity: 0,
          agreed_price: 0,
          step: 'bulk_sale'
        }
      ]
    }
  };
  const result = computeImpact(batches);
  assert.equal(result.revenue, 0);
  assert.deepEqual(result.placedByUnit, {});
  assert.equal(result.callsMade, 1);
  assert.equal(result.dealsClosed, 0);
});

test('computeImpact: multiple batches with different units aggregate into separate keys', () => {
  const batches = {
    b1: {
      unit: 'kg',
      attempts: [
        {
          call_status: 'completed',
          outcome: 'deal',
          agreed_quantity: 10,
          agreed_price: 50,
          step: 'bulk_sale'
        }
      ]
    },
    b2: {
      unit: 'crate',
      attempts: [
        {
          call_status: 'completed',
          outcome: 'deal',
          agreed_quantity: 3,
          agreed_price: 200,
          step: 'bulk_sale'
        }
      ]
    }
  };
  const result = computeImpact(batches);
  assert.equal(result.revenue, 1100);
  assert.deepEqual(result.placedByUnit, { kg: 10, crate: 3 });
  assert.equal(result.callsMade, 2);
  assert.equal(result.dealsClosed, 2);
});

test('rankItems: sorts items with worst_stage unsafe/spoiled first, tie-breaks on severity', () => {
  const items = [
    { item_key: 'fresh_item', stage: 'fresh', position: { xmin: 0, ymin: 0, xmax: 0.1, ymax: 0.1 } },
    { item_key: 'spoiled_item', stage: 'spoiled', position: { xmin: 0, ymin: 0, xmax: 0.2, ymax: 0.2 } },
    { item_key: 'unsafe_item', stage: 'unsafe', position: { xmin: 0, ymin: 0, xmax: 0.1, ymax: 0.1 } }
  ];
  const ranked = rankItems(items);
  assert.equal(ranked[0].item_key, 'unsafe_item');
  assert.equal(ranked[1].item_key, 'spoiled_item');
  assert.equal(ranked[2].item_key, 'fresh_item');
});

test('getStageColor: returns expected hex string for known stages and fallback for unknown', () => {
  assert.equal(getStageColor('fresh'), '#10b981');
  assert.equal(getStageColor('ripening'), '#f59e0b');
  assert.equal(getStageColor('overripe'), '#f97316');
  assert.equal(getStageColor('spoiled'), '#ef4444');
  assert.equal(getStageColor('unsafe'), '#dc2626');
  assert.equal(getStageColor('unknown_custom'), '#9ca3af');
});

test('formatObserved: count vs weight vs pieces vs unknown branches', () => {
  assert.equal(formatObserved({ method: 'count', min: 5, max: 10 }), 'about 5–10 pieces');
  assert.equal(formatObserved({ method: 'count', min: 7, max: 7 }), 'about 7 pieces');
  assert.equal(formatObserved({ method: 'fill', min: 40, max: 60 }), 'about 40–60% full');
  assert.equal(formatObserved({ method: 'fill', min: 50, max: 50 }), 'about 50% full');
  assert.equal(formatObserved(null), '');
});

test('formatQuantity: formats min/max with unit or confidence', () => {
  assert.equal(formatQuantity({ low: 10, high: 15, unit: 'kg' }), '10–15 kg');
  assert.equal(formatQuantity({ low: 10, high: 10, unit: 'kg' }), '10 kg');
  assert.equal(formatQuantity(null), '');
});

test('formatUncertainFields: returns all fields agreed when array empty, uncertain: ... when present', () => {
  assert.equal(formatUncertainFields([]), 'all fields agreed');
  assert.equal(formatUncertainFields(null), 'all fields agreed');
  assert.equal(formatUncertainFields(['fresh.sellable_for']), 'uncertain: fresh shelf life');
});

test('formatDecisionLine: formats keep, discount, and other steps accurately', () => {
  assert.equal(formatDecisionLine({ step: 'keep' }), 'Stays at full price · re-checked at next photo');
  assert.equal(
    formatDecisionLine({
      step: 'discount',
      shelf_price: 150,
      discounted_price: 120,
      discount_pct: 20,
      unit: 'kg'
    }),
    'Rs 150 → Rs 120 / kg (−20%)'
  );
  assert.equal(
    formatDecisionLine({
      step: 'bulk_sale',
      buyer_types: ['juice_shop'],
      opening_price: 100,
      floor_price: 80,
      unit: 'kg'
    }),
    'Juice shops · Opening Rs 100/kg · floor Rs 80/kg (never told to buyers)'
  );
  assert.equal(formatDecisionLine({ step: 'donate' }), 'Free to charities');
  assert.equal(formatDecisionLine({ step: 'compost' }), 'Needs manager approval');
});

test('formatProfileLine: formats shelf life, batch, and sensitivity', () => {
  assert.equal(
    formatProfileLine({ name: 'banana', profile_source: 'manager' }),
    'Produce profile: banana · Manager profile'
  );
  assert.equal(
    formatProfileLine({ name: 'banana', profile_source: 'fallback' }),
    'Produce profile: banana · Generic fallback'
  );
  assert.equal(
    formatProfileLine({ name: 'banana', profile_source: 'gemini', profile_votes: 5, profile_uncertain_fields: [] }),
    'Produce profile: banana · Gemini, 5 votes · all fields agreed'
  );
});

test('getFindBuyersLabel: bulk_sale -> juice shops & bakeries, animal_feed -> cattle farms, donate -> charities, default -> buyers', () => {
  assert.equal(getFindBuyersLabel('bulk_sale'), 'Find juice shops & bakeries');
  assert.equal(getFindBuyersLabel('animal_feed'), 'Find cattle farms');
  assert.equal(getFindBuyersLabel('donate'), 'Find charities');
  assert.equal(getFindBuyersLabel('unknown'), 'Find buyers');
});

test('getNextStepTargetLabel: donate -> charities, animal_feed -> cattle farms, other -> underscored replaced', () => {
  const batchDonate = {
    step_index: 0,
    plans: [{ step: 'bulk_sale' }, { step: 'donate' }]
  };
  assert.equal(getNextStepTargetLabel(batchDonate), 'charities');

  const batchFeed = {
    step_index: 0,
    plans: [{ step: 'bulk_sale' }, { step: 'animal_feed' }]
  };
  assert.equal(getNextStepTargetLabel(batchFeed), 'cattle farms');

  const batchOther = {
    step_index: 0,
    plans: [{ step: 'bulk_sale' }, { step: 'compost_bin' }]
  };
  assert.equal(getNextStepTargetLabel(batchOther), 'compost bin');
});

test('formatChange: "Since last photo" as a value, a trend and a detail', () => {
  assert.deepEqual(formatChange({ change_since_last: null }, false), { value: 'First photo of this shelf', trend: 'none', detail: '' });
  assert.deepEqual(formatChange({ change_since_last: null }, true), { value: 'New on this shelf', trend: 'none', detail: '' });
  assert.deepEqual(
    formatChange({ score: 46, change_since_last: -9, change_note: 'dropped 9 points since the last photo (today 20:30)' }, true),
    { value: '−9 points', trend: 'down', detail: 'since 20:30' },
  );
  assert.deepEqual(
    formatChange({ score: 46, change_since_last: -42, change_note: 'dropped 42 points since the last photo (12 Oct 09:15); worst pieces now spoiled' }, true),
    { value: '−42 points', trend: 'down', detail: 'since 12 Oct 09:15 · worst pieces now spoiled' },
  );
  assert.deepEqual(
    formatChange({ score: 81, change_since_last: 1, change_note: 'up 1 points since the last photo (yesterday 18:00)' }, true),
    { value: '+1 point', trend: 'up', detail: 'since yesterday 18:00' },
  );
  assert.deepEqual(
    formatChange({ score: 88, change_since_last: 0, change_note: 'no change since the last photo (today 10:00)' }, true),
    { value: 'No change', trend: 'flat', detail: 'since 10:00' },
  );
});

test('formatStockBasis: how the stock estimate was made', () => {
  assert.equal(formatStockBasis({ method: 'count', min: 25, max: 34 }), '25–34 pieces');
  assert.equal(formatStockBasis({ method: 'count', min: 7, max: 7 }), '7 pieces');
  assert.equal(formatStockBasis({ method: 'fill_level', min: 60, max: 80 }), 'container 60–80% full');
  assert.equal(formatStockBasis(null), '');
});

test('freshnessPosition: stage fifth plus early/mid/late, Fresh on the left', () => {
  assert.equal(freshnessPosition('fresh', 'early'), 0.04);
  assert.equal(freshnessPosition('overripe', 'mid'), 0.5);
  assert.equal(freshnessPosition('unsafe', 'late'), 0.96);
  assert.equal(freshnessPosition('ripening', undefined), 0.3);
  assert.equal(freshnessPosition('unknown', 'mid'), null);
});

test('readingSummary: the reading footer in words', () => {
  assert.equal(
    readingSummary({ model: 'gemini-3.8-flash', latency_ms: 7412, calls: 2, zoomed_groups: 1, hedges: 0, from_cache: false }),
    'Read by Gemini 3.8 Flash · 7.4 s · 2 calls · 1 zoomed in',
  );
  assert.equal(
    readingSummary({ model: 'gemini-3.8-flash', latency_ms: 60004, calls: 1, zoomed_groups: 0, hedges: 1, from_cache: false }),
    'Read by Gemini 3.8 Flash · 60.0 s · 1 call · 1 hedged',
  );
  assert.equal(
    readingSummary({ model: 'gemini-3.8-flash', latency_ms: 40, calls: 0, zoomed_groups: 0, hedges: 0, from_cache: true }),
    'Read by Gemini 3.8 Flash · same photo as before, stored reading reused',
  );
});
