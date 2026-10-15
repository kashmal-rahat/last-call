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

test('header clock: a preset shows its time, plain, explained on hover and to screen readers', () => {
  state.currentLadderResult = { clock_offset_s: EVENING };
  updateClock();
  const [note] = dom.headerTime.children;
  assert.match(dom.headerTime.textContent, /^\d\d:\d\d PKT$/);
  assert.equal(dom.headerTime.title, 'Set by Time until closing');
  assert.equal(note.className, 'visually-hidden');
  assert.equal(note.textContent, ' (Set by Time until closing)');

  // "Now" (or no decision): the real time, with no explanation
  state.currentLadderResult = null;
  dom.headerTime.children = [];
  const before = `${formatPktClock(new Date())} PKT`;
  updateClock();
  const after = `${formatPktClock(new Date())} PKT`;
  assert.equal(dom.headerTime.title, '');
  assert.equal(dom.headerTime.children.length, 0);
  assert.ok([before, after].includes(dom.headerTime.textContent));  // the minute may turn in between
});

test('a call-back is "today" on the mart\'s day, even when the real date has moved on', () => {
  // Decided "12 h left" at real 23:50 (the mart at 11:00); 25 minutes later the real date is the 17th
  const realNow = new Date('2026-10-17T00:15:00+05:00');
  const martTime = new Date('2026-10-16T11:25:00+05:00');
  const callback = '2026-10-16T17:00:00+05:00';
  assert.equal(formatCallbackTime(callback, martTime), '17:00');
  assert.notEqual(formatCallbackTime(callback, realNow), '17:00');  // what the page showed before D74
});
