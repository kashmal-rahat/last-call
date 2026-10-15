// services/api/tests/js/call.test.mjs
//
// Hang up ends a call at whatever stage it has reached: while it is being created, while its connection
// opens, while a busy line waits to retry, and when it is live. The browser pieces the call uses
// (page elements, WebSocket, audio, microphone, fetch) are small fakes.

import test from 'node:test';
import assert from 'node:assert/strict';

// A page element that accepts whatever the renderers do with it; unset properties read as empty
function fakeElement() {
  const el = {
    style: {}, dataset: {}, children: [], childNodes: [], options: [], selectedIndex: 0,
    value: '', textContent: '', className: '', disabled: false,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  };
  return new Proxy(el, {
    get(target, prop) {
      if (prop in target) return target[prop];
      if (typeof prop === 'symbol' || prop === 'then') return undefined;
      return () => fakeElement();
    },
  });
}
globalThis.window = globalThis;
globalThis.document = {
  getElementById: () => fakeElement(),
  querySelectorAll: () => [],
  querySelector: () => null,
  createElement: () => fakeElement(),
  createElementNS: () => fakeElement(),
  createTextNode: () => fakeElement(),
  addEventListener() {},
};
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.matchMedia = () => ({ matches: true });

// What the call did, per test
let log;
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;
  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    log.sockets.push(this);
  }
  send(data) { this.sent.push(data); }
  close() { this.closeCalls = (this.closeCalls || 0) + 1; }
}
globalThis.WebSocket = FakeWebSocket;
globalThis.AudioContext = class {
  constructor() { this.audioWorklet = { addModule: async () => {} }; this.destination = {}; }
  createMediaStreamSource() { return { connect() {} }; }
  close() { return Promise.resolve(); }
};
globalThis.AudioWorkletNode = class { constructor() { this.port = {}; } connect() {} };
Object.defineProperty(globalThis, 'navigator', {
  value: { mediaDevices: { getUserMedia: async () => { log.microphone += 1; return { getTracks: () => [] }; } } },
  configurable: true,
});

const { state } = await import('../../lastcall_api/static/js/state.js');
const dom = await import('../../lastcall_api/static/js/dom.js');
const { startCallForItem, hangup, handleBusyRetry } =
  await import('../../lastcall_api/static/js/call.js');

const CALL = { call_id: 'call_1', batch_id: 'batch_1', ws_url: 'wss://voice.test/ws/call', token: 't', buyer: null, deal: null };

function reset() {
  log = { sockets: [], microphone: 0, requests: [] };
  dom.inspectAccessCodeEl.value = 'code';
  Object.assign(state, {
    currentInspection: { inspection_id: 'insp_1', items: [] },
    currentLadderResult: null,
    currentActiveCall: null,
    isCallInProgress: false,
    ws: null,
    retryCount: 0,
  });
  // Every request is recorded; /demo/calls answers when the test releases it
  let releaseCall;
  const callAnswered = new Promise(resolve => { releaseCall = resolve; });
  globalThis.fetch = async (url) => {
    log.requests.push(url);
    if (url === '/demo/calls') {
      await callAnswered;
      return { ok: true, status: 200, json: async () => CALL };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  };
  return { answerCall: () => releaseCall() };
}

// Lets pending promise callbacks run
const settle = () => new Promise(resolve => setImmediate(resolve));

test('hang up while the call is being created: no microphone, no connection, the page is free again', async () => {
  const { answerCall } = reset();
  const starting = startCallForItem('item_banana', 'places:a');
  await settle();
  assert.equal(state.isCallInProgress, true);

  hangup();
  answerCall();
  await starting;

  assert.equal(log.microphone, 0);
  assert.equal(log.sockets.length, 0);
  assert.equal(state.isCallInProgress, false);
  assert.equal(state.currentActiveCall, null);
});

test('hang up while the connection opens: it is dropped and the call ends here, with no result to wait for', async () => {
  const { answerCall } = reset();
  answerCall();
  await startCallForItem('item_banana', 'places:a');
  const [ws] = log.sockets;
  assert.equal(ws.readyState, FakeWebSocket.CONNECTING);

  hangup();
  assert.equal(ws.closeCalls, 1);
  ws.onclose({ code: 1006 });  // what the browser reports for a connection closed before it opened
  await settle();

  assert.equal(state.isCallInProgress, false);
  assert.equal(state.currentActiveCall, null);
  assert.ok(!log.requests.some(url => url.startsWith('/demo/batches/')), 'no polling for a result');
});

test('hang up on a live call: the server is told, so it saves the result', async () => {
  const { answerCall } = reset();
  answerCall();
  await startCallForItem('item_banana', 'places:a');
  const [ws] = log.sockets;
  ws.readyState = FakeWebSocket.OPEN;
  ws.onopen();

  hangup();

  assert.deepEqual(ws.sent.map(m => JSON.parse(m).type), ['auth', 'hangup']);
  assert.equal(ws.closeCalls, 1);
  assert.equal(state.currentActiveCall.hungUp, true);  // the socket's close then shows the saved result
});

test('hang up while a busy line waits to retry: it does not dial again', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  reset();
  state.isCallInProgress = true;
  state.currentActiveCall = { itemKey: 'item_banana', batchId: 'batch_1', callId: 'call_1', buyerId: 'places:a', hungUp: false };
  state.ws = { readyState: FakeWebSocket.CLOSED };

  handleBusyRetry(CALL.ws_url, CALL.token);
  hangup();
  t.mock.timers.tick(3000);

  assert.equal(log.sockets.length, 0);
  assert.equal(state.isCallInProgress, false);
});

test('without a hang-up, a busy line is retried', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  reset();
  state.currentActiveCall = { itemKey: 'item_banana', batchId: 'batch_1', callId: 'call_1', buyerId: 'places:a', hungUp: false };

  handleBusyRetry(CALL.ws_url, CALL.token);
  t.mock.timers.tick(3000);

  assert.equal(log.sockets.length, 1);
});

// A problem with the access code is shown at the code field, where the judge fixes it
test('a refused access code is shown at the code field, and the call does not start', async () => {
  reset();
  globalThis.fetch = async (url) => {
    log.requests.push(url);
    return { ok: false, status: 401, json: async () => ({ detail: 'Invalid access code' }) };
  };
  dom.accessCodeError.hidden = true;

  await startCallForItem('item_banana', 'places:a');

  assert.equal(dom.accessCodeError.hidden, false);
  assert.match(dom.accessCodeError.textContent, /isn't right/);
  assert.equal(log.sockets.length, 0);
  assert.equal(state.isCallInProgress, false);
});

test('a missing access code is asked for at the code field, with no request sent', async () => {
  reset();
  dom.inspectAccessCodeEl.value = '';
  dom.accessCodeError.hidden = true;

  await startCallForItem('item_banana', 'places:a');

  assert.equal(dom.accessCodeError.hidden, false);
  assert.match(dom.accessCodeError.textContent, /Enter the access code/);
  assert.equal(log.requests.length, 0);
});
