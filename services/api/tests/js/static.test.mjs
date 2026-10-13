// services/api/tests/js/static.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Provide minimal browser mocks for Node test environment when importing frontend modules
if (typeof globalThis.document === 'undefined') {
  globalThis.document = {
    getElementById: (id) => ({ id, style: {}, classList: { add() {}, remove() {}, contains() {} } }),
    querySelectorAll: () => [],
    createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {} }),
    createElementNS: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {}, setAttribute() {} }),
  };
}
if (typeof globalThis.window === 'undefined') {
  globalThis.window = globalThis;
}
if (typeof globalThis.localStorage === 'undefined') {
  globalThis.localStorage = {
    getItem: () => null,
    setItem: () => {}
  };
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const staticDir = path.resolve(__dirname, '../../lastcall_api/static');
const jsDir = path.join(staticDir, 'js');
const indexHtmlPath = path.join(staticDir, 'index.html');
const indexHtmlContent = fs.readFileSync(indexHtmlPath, 'utf8');

test('index.html: contains exactly ONE <script> tag with type="module" and src="/static/js/main.js"', () => {
  const scriptMatches = [...indexHtmlContent.matchAll(/<script\b([^>]*)>/gi)];
  assert.equal(scriptMatches.length, 1, `Expected exactly 1 <script> tag, found ${scriptMatches.length}`);
  const attrs = scriptMatches[0][1];
  assert.ok(/type=["']module["']/i.test(attrs), 'Script tag must have type="module"');
  assert.ok(/src=["']\/static\/js\/main\.js["']/i.test(attrs), 'Script tag must have src="/static/js/main.js"');
});

test('index.html: has ZERO style="..." attributes', () => {
  const styleMatches = [...indexHtmlContent.matchAll(/\bstyle\s*=\s*["'][^"']*["']/gi)];
  assert.equal(styleMatches.length, 0, `Expected 0 style="..." attributes, found ${styleMatches.length}`);
});

test('index.html: has required accessibility attributes', () => {
  // closing-time-btn buttons have aria-pressed
  const closingBtns = [...indexHtmlContent.matchAll(/<button[^>]*class=["'][^"']*closing-time-btn[^"']*["'][^>]*>/gi)];
  assert.ok(closingBtns.length > 0, 'Found closing-time-btn buttons');
  for (const btn of closingBtns) {
    assert.ok(/aria-pressed=["'](true|false)["']/i.test(btn[0]), `closing-time-btn missing aria-pressed: ${btn[0]}`);
  }

  // every <input> and <select> has an associated <label> or aria-label
  const inputsAndSelects = [...indexHtmlContent.matchAll(/<(input|select)\b([^>]*)>/gi)];
  for (const tag of inputsAndSelects) {
    const tagName = tag[1].toLowerCase();
    const attrs = tag[2];
    const idMatch = attrs.match(/id=["']([^"']+)["']/i);
    const hasAriaLabel = /aria-label=["'][^"']+["']/i.test(attrs);
    const hasAriaLabelledBy = /aria-labelledby=["'][^"']+["']/i.test(attrs);

    let hasAssociatedLabel = false;
    if (idMatch) {
      const id = idMatch[1];
      const labelRegex = new RegExp(`<label[^>]*for=["']${id}["']`, 'i');
      hasAssociatedLabel = labelRegex.test(indexHtmlContent);
    }

    assert.ok(
      hasAssociatedLabel || hasAriaLabel || hasAriaLabelledBy,
      `Element <${tagName} ${attrs}> lacks an associated <label for="..."> or aria-label`
    );
  }
});

test('static/js/: all imports use relative .js extension or builtins', () => {
  const jsFiles = fs.readdirSync(jsDir).filter(f => f.endsWith('.js'));
  const importRegex = /(?:import\s+(?:[\w*\s{},]+from\s+)?['"]([^'"]+)['"])|(?:export\s+(?:[\w*\s{},]+from\s+)?['"]([^'"]+)['"])/g;

  for (const file of jsFiles) {
    const content = fs.readFileSync(path.join(jsDir, file), 'utf8');
    const matches = [...content.matchAll(importRegex)];
    for (const m of matches) {
      const specifier = m[1] || m[2];
      if (!specifier) continue;
      if (specifier.startsWith('./') || specifier.startsWith('../')) {
        assert.ok(specifier.endsWith('.js'), `Import ${specifier} in ${file} must end with .js`);
      }
    }
  }
});

test('static/js/: every exported symbol in the Step 9 table exists', async () => {
  const expectedExports = {
    'storage.js': ['getStoredItem', 'setStoredItem', 'generateShelfId', 'getOrCreateShelfId', 'resetShelfId'],
    'state.js': ['state'],
    'format.js': [
      'rankItems',
      'getStageColor',
      'formatObserved',
      'formatQuantity',
      'formatUncertainFields',
      'formatDecisionLine',
      'formatProfileLine',
      'getFindBuyersLabel',
      'getNextStepTargetLabel',
      'STAFF_REASON_LABELS',
      'STAFF_ACTION_LABELS',
      'computeImpact'
    ],
    'ui.js': ['icon', 'showToast'],
    'setup.js': [
      'updateClock',
      'syncClosingTimeButtons',
      'loadSamples',
      'loadBranches',
      'updateHeaderBranch'
    ],
    'lock.js': ['batchIdFor', 'loadBatchesForBranch', 'isShelfLocked', 'updateShelfLock'],
    'reading.js': ['handleInspect', 'setActiveItem', 'highlightActiveBox', 'renderItemsList', 'renderResults'],
    'decision.js': ['triggerDecide', 'renderActiveDecision'],
    'buyers.js': ['fetchScoutBuyers', 'renderNextActionRow', 'advanceBatchStep', 'renderActiveBuyers'],
    'call.js': [
      'setStatus',
      'appendMessage',
      'appendNotice',
      'startCallTimer',
      'stopCallTimer',
      'triggerWaveformAnimation',
      'startCallForItem',
      'connectWebSocket',
      'pollBatchUntilCompleted',
      'renderCallResult',
      'renderCallPendingResult',
      'handleBusyRetry',
      'hangup',
      'cleanupAudio'
    ],
    'impact.js': ['renderImpact'],
    'phone.js': ['isPhoneMode', 'initPhoneDemo', 'startPhoneCall']
  };

  for (const [modName, syms] of Object.entries(expectedExports)) {
    const modPath = path.join(jsDir, modName);
    const mod = await import(`file://${modPath}`);
    for (const sym of syms) {
      assert.ok(
        sym in mod,
        `Expected symbol '${sym}' to be exported by ${modName}`
      );
    }
  }
});

test('static/js/: .style. is used ONLY for display, top, left, width, height', () => {
  const allowedProps = new Set(['display', 'top', 'left', 'width', 'height']);
  const jsFiles = fs.readdirSync(jsDir).filter(f => f.endsWith('.js'));
  const violations = [];

  for (const file of jsFiles) {
    const content = fs.readFileSync(path.join(jsDir, file), 'utf8');
    const matches = [...content.matchAll(/\.style\.([a-zA-Z]+)/g)];
    for (const m of matches) {
      const prop = m[1];
      if (!allowedProps.has(prop)) {
        violations.push({ file, prop });
      }
    }
  }

  assert.deepEqual(violations, [], `Disallowed .style property access found: ${JSON.stringify(violations)}`);
});
