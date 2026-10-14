// services/api/lastcall_api/static/js/setup.js

import { state } from './state.js';
import * as dom from './dom.js';
import { getStoredItem } from './storage.js';
import { icon } from './ui.js';

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

// Shelf photo picker: the sample photos as a list with thumbnails (right) and a large preview
// of the selected photo (left). An uploaded photo takes the preview.
let samples = [];
let selectedIdx = -1; // -1: an uploaded photo (or nothing yet)
let uploadPreviewUrl = null;

export async function loadSamples() {
  try {
    const resp = await fetch('/demo/samples');
    if (!resp.ok) return;
    samples = await resp.json();
  } catch (err) {
    console.warn('loadSamples', err);
    return;
  }

  dom.samplesList.replaceChildren();
  samples.forEach((sample, idx) => {
    // A native radio inside a label: one Tab stop for the group, arrow keys between photos
    const option = document.createElement('label');
    option.className = 'photo-option';
    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = 'shelfSample';
    radio.className = 'visually-hidden';
    option.appendChild(radio);

    const thumb = document.createElement('img');
    thumb.className = 'photo-option-thumb';
    thumb.src = sample.thumb || sample.url;
    thumb.alt = '';
    thumb.loading = 'lazy';
    option.appendChild(thumb);

    const text = document.createElement('span');
    text.className = 'photo-option-text';
    const name = document.createElement('span');
    name.className = 'photo-option-name';
    name.textContent = sample.label;
    text.appendChild(name);
    if (sample.ai_generated) {
      const meta = document.createElement('span');
      meta.className = 'photo-option-meta';
      meta.textContent = 'AI-generated image';
      text.appendChild(meta);
    }
    option.appendChild(text);

    const tick = document.createElement('span');
    tick.className = 'photo-option-check';
    tick.appendChild(icon('check'));
    option.appendChild(tick);

    radio.addEventListener('change', () => selectSample(idx));
    dom.samplesList.appendChild(option);
  });

  if (samples.length > 0) selectSample(Math.max(0, samples.findIndex(sample => sample.default)));
}

function selectSample(idx) {
  if (state.isCallInProgress || state.isInspecting) {
    markSelected(selectedIdx); // the photo can't change mid-call or mid-inspection
    return;
  }
  const sample = samples[idx];

  dom.shelfPhotoInput.value = '';
  clearUploadPreview();
  markSelected(idx);
  renderPhotoPreview(sample.thumb || sample.url, sample.label);

  state.activeSampleUrl = sample.url;
  state.activeSampleBlob = null;
  fetch(sample.url)
    .then(res => (res.ok ? res.blob() : null))
    .then(blob => {
      // A later selection wins: only keep the blob if this sample is still the selected one
      if (blob && state.activeSampleUrl === sample.url) state.activeSampleBlob = blob;
    })
    .catch(err => console.warn('selectSample blob fetch', err));
}

// Called when the judge picks a file: it becomes the selected photo.
export function showUploadedPhoto(file) {
  state.activeSampleBlob = null;
  state.activeSampleUrl = null;
  clearUploadPreview();
  uploadPreviewUrl = URL.createObjectURL(file);
  markSelected(-1);
  dom.uploadOption.classList.add('selected');
  dom.uploadFileName.textContent = `${file.name} · Change`;
  renderPhotoPreview(uploadPreviewUrl, 'Your photo');
}

function clearUploadPreview() {
  if (uploadPreviewUrl) URL.revokeObjectURL(uploadPreviewUrl);
  uploadPreviewUrl = null;
  dom.uploadOption.classList.remove('selected');
  dom.uploadFileName.textContent = 'Upload your own photo';
}

function markSelected(idx) {
  selectedIdx = idx;
  [...dom.samplesList.children].forEach((option, i) => {
    const selected = i === idx;
    option.classList.toggle('selected', selected);
    option.querySelector('input').checked = selected;
  });
}

// The selected photo, large, with its name on a soft gradient (an AI-generated photo's name says "AI").
function renderPhotoPreview(src, label) {
  const img = document.createElement('img');
  img.className = 'photo-preview-img';
  img.src = src;
  img.alt = '';
  img.decoding = 'async';

  const caption = document.createElement('figcaption');
  caption.className = 'photo-preview-caption';
  caption.textContent = label;

  dom.photoPreview.replaceChildren(img, caption);
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
      opt.textContent = b.name;
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
