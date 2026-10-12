// services/api/lastcall_api/static/js/setup.js

import { state } from './state.js';
import * as dom from './dom.js';
import { getStoredItem } from './storage.js';

// Clock update (Karachi PKT, UTC+5)
export function updateClock() {
  try {
    const now = new Date();
    const formatter = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Asia/Karachi',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });
    dom.headerTime.textContent = `${formatter.format(now)} PKT`;
  } catch (e) {
    const d = new Date();
    dom.headerTime.textContent = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')} PKT`;
  }
}

// Segmented Buttons for Closing Window
export function syncClosingTimeButtons() {
  const currentVal = dom.closingTimeSelect.value;
  const buttons = dom.closingTimeButtons.querySelectorAll('button');
  buttons.forEach(btn => {
    const isActive = btn.dataset.val === currentVal;
    if (isActive) {
      btn.classList.add('active');
      btn.setAttribute('aria-pressed', 'true');
    } else {
      btn.classList.remove('active');
      btn.setAttribute('aria-pressed', 'false');
    }
  });
}

// Populate Samples
export async function loadSamples() {
  try {
    const resp = await fetch('/demo/samples');
    if (!resp.ok) return;
    const samples = await resp.json();
    dom.samplesList.replaceChildren();

    samples.forEach((sample, idx) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'sample-thumbnail-card' + (idx === 0 ? ' active' : '');

      const img = document.createElement('img');
      img.className = 'sample-thumb-img';
      img.src = sample.url;
      img.alt = sample.label || `Sample ${idx + 1}`;
      card.appendChild(img);

      const info = document.createElement('div');
      info.className = 'sample-thumb-info';
      info.textContent = sample.label || `Sample ${idx + 1}`;
      card.appendChild(info);

      card.addEventListener('click', async () => {
        if (state.isCallInProgress || state.isInspecting) return;
        document.querySelectorAll('.sample-thumbnail-card').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        dom.shelfPhotoInput.value = '';
        state.activeSampleUrl = sample.url;
        try {
          const imgRes = await fetch(sample.url);
          state.activeSampleBlob = await imgRes.blob();
        } catch (err) {
          console.warn('loadSamples blob fetch', err);
        }
      });

      dom.samplesList.appendChild(card);
      if (idx === 0) {
        card.click();
      }
    });
  } catch (err) {
    console.warn('loadSamples', err);
  }
}

export async function loadBranches() {
  try {
    const res = await fetch('/demo/branches');
    if (!res.ok) return;
    const data = await res.json();
    dom.branchSelect.replaceChildren();
    (data.branches || []).forEach(b => {
      const opt = document.createElement('option');
      opt.value = b.branch_id;
      opt.textContent = `${b.name} (${b.location})`;
      if (b.branch_id === data.default_branch_id) {
        opt.selected = true;
      }
      dom.branchSelect.appendChild(opt);
    });

    const storedBranch = getStoredItem('lc_branch_id', 'johar_town');
    if (storedBranch && (data.branches || []).some(b => b.branch_id === storedBranch)) {
      dom.branchSelect.value = storedBranch;
    }
    updateHeaderBranch();
  } catch (e) {
    console.warn('loadBranches', e);
  }
}

export function updateHeaderBranch() {
  const selected = dom.branchSelect.options[dom.branchSelect.selectedIndex];
  if (selected) {
    const branchName = selected.textContent.split('(')[0].trim();
    dom.headerBranchChip.textContent = branchName;
  }
}
