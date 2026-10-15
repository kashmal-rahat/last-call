// services/api/tests/js/clock.test.mjs
//
// D74: the page shows the mart's time. With a Time until closing preset that is the time the preset stands for
// (the decision's clock_offset_s), still ticking; with "Now" the real time. Always shown in Pakistan time.

import test from 'node:test';
import assert from 'node:assert/strict';

// Just enough page for setup.js: elements that keep their text, title and children
function fakeElement() {
  return {
    textContent: '', title: '', className: '', children: [], style: {}, dataset: {},
    appendChild(child) { this.children.push(child); return child; },
    addEventListener() {},
    querySelectorAll: () => [],
  };
}
const elements = {};
globalThis.document = {
  getElementById: (id) => (elements[id] ||= fakeElement()),
  createElement: () => fakeElement(),
  createElementNS: () => fakeElement(),
  querySelectorAll: () => [],
};
globalThis.localStorage = { getItem: () => null, setItem() {} };

const { state, martNow } = await import('../../lastcall_api/static/js/state.js');
const { formatPktClock, formatCallbackTime } = await import('../../lastcall_api/static/js/format.js');
const { updateClock } = await import('../../lastcall_api/static/js/setup.js');
const dom = await import('../../lastcall_api/static/js/dom.js');

const EVENING = 17 * 3600;  // "4 h left" decided at 02:00: the mart at 19:00
const REAL_2AM = new Date('2026-10-16T02:00:00+05:00');

test('formatPktClock: Pakistan time whatever the device time zone', () => {
  assert.equal(formatPktClock(new Date('2026-10-15T21:00:00Z')), '02:00');
  assert.equal(formatPktClock(new Date('2026-10-16T13:05:00Z')), '18:05');
});

test('martNow: the real time moved by the current decision\'s shift; unchanged without one', () => {
  state.currentLadderResult = null;
  assert.equal(martNow(REAL_2AM).getTime(), REAL_2AM.getTime());
  state.currentLadderResult = { clock_offset_s: 0 };
  assert.equal(martNow(REAL_2AM).getTime(), REAL_2AM.getTime());
  state.currentLadderResult = { clock_offset_s: EVENING };
  assert.equal(formatPktClock(martNow(REAL_2AM)), '19:00');
  state.currentLadderResult = null;
});

// The Time until closing options as the page has them (index.html): hours and the time each one sets
const OPTIONS = { '': null, '12': '11:00', '4': '19:00', '1': '22:00' };
function select(hours) {
  dom.closingTimeSelect.selectedOptions = [{ value: hours, dataset: OPTIONS[hours] ? { time: OPTIONS[hours] } : {} }];
}
function header() {
  dom.headerTime.children = [];
  updateClock();
  return dom.headerTime.textContent;
}
// The real time now, in Pakistan; the minute may turn while a test runs, so both readings are accepted
function realNowEither(run) {
  const before = `${formatPktClock(new Date())} PKT`;
  const shown = run();
  const after = `${formatPktClock(new Date())} PKT`;
  assert.ok([before, after].includes(shown), shown);
}

test('header clock: a picked preset shows its time at once and holds it until there is a decision', () => {
  state.currentLadderResult = null;
  select('4');  // the page opens on 19:00 (D65)
  assert.equal(header(), '19:00 PKT');
  assert.equal(dom.headerTime.title, 'Set by Time until closing');
  const [note] = dom.headerTime.children;
  assert.equal(note.className, 'visually-hidden');
  assert.equal(note.textContent, ' (Set by Time until closing)');

  select('12');
  assert.equal(header(), '11:00 PKT');
});

test('header clock: with a decision for the picked preset, it ticks on the decision\'s time', () => {
  // Decided "19:00" 25 minutes ago: the mart is now at 19:25
  const decidedOffset = (new Date('2026-10-16T19:00:00+05:00') - new Date(Date.now() - 25 * 60 * 1000)) / 1000;
  state.currentLadderResult = { hours_until_closing: 4, clock_offset_s: decidedOffset };
  select('4');
  assert.ok(['19:25 PKT', '19:26 PKT'].includes(header()));
  assert.equal(dom.headerTime.title, 'Set by Time until closing');
});

test('header clock: a new preset shows its time while its decision is on the way', () => {
  state.currentLadderResult = { hours_until_closing: 4, clock_offset_s: EVENING };  // the old decision
  select('1');
  assert.equal(header(), '22:00 PKT');
  select('');  // "Now", while the 19:00 decision is still the current one
  realNowEither(header);
  assert.equal(dom.headerTime.title, '');
});

test('header clock: "Now" shows the real time with no explanation, before and after its decision', () => {
  select('');
  state.currentLadderResult = null;
  realNowEither(header);
  state.currentLadderResult = { hours_until_closing: 20.5, clock_offset_s: 0 };
  realNowEither(header);
  assert.equal(dom.headerTime.title, '');
  assert.equal(dom.headerTime.children.length, 0);
  state.currentLadderResult = null;
});

test('a call-back is "today" on the mart\'s day, even when the real date has moved on', () => {
  // Decided "12 h left" at real 23:50 (the mart at 11:00); 25 minutes later the real date is the 17th
  const realNow = new Date('2026-10-17T00:15:00+05:00');
  const martTime = new Date('2026-10-16T11:25:00+05:00');
  const callback = '2026-10-16T17:00:00+05:00';
  assert.equal(formatCallbackTime(callback, martTime), '17:00');
  assert.notEqual(formatCallbackTime(callback, realNow), '17:00');  // what the page showed before D74
});
