// services/api/lastcall_api/static/js/ui.js

export function scriptClass(text) {
  return /[؀-ۿ]/.test(text || '') ? 'urdu' : '';
}

export function icon(name) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.75');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.classList.add('inline-icon', `icon-${name}`);

  const appendPath = (d) => {
    const p = document.createElementNS(ns, 'path');
    p.setAttribute('d', d);
    svg.appendChild(p);
  };
  const appendCircle = (cx, cy, r) => {
    const c = document.createElementNS(ns, 'circle');
    c.setAttribute('cx', cx);
    c.setAttribute('cy', cy);
    c.setAttribute('r', r);
    svg.appendChild(c);
  };
  const appendRect = (x, y, w, h, rx) => {
    const r = document.createElementNS(ns, 'rect');
    r.setAttribute('x', x);
    r.setAttribute('y', y);
    r.setAttribute('width', w);
    r.setAttribute('height', h);
    if (rx) r.setAttribute('rx', rx);
    svg.appendChild(r);
  };

  switch (name) {
    case 'pin':
      appendPath('M12 2a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7z');
      appendCircle('12', '9', '2.5');
      break;
    case 'phone':
      appendPath('M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z');
      break;
    case 'lock':
      appendRect('3', '11', '18', '11', '2');
      appendPath('M7 11V7a5 5 0 0 1 10 0v4');
      break;
    case 'warning':
      appendPath('m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z');
      appendPath('M12 9v4');
      appendPath('M12 17h.01');
      break;
    case 'check':
      appendPath('M20 6 9 17l-5-5');
      break;
    case 'message':
      appendPath('M7.9 20A9 9 0 1 0 4 16.1L2 22Z');
      break;
    case 'leaf':
      appendPath('M11 20A7 7 0 0 1 4 13c0-4 3-7 7-7 4 0 9 2 9 7 0 4-3 7-9 7Z');
      appendPath('M11 6c0 6 2 9 9 11');
      break;
    case 'clock':
      appendCircle('12', '12', '10');
      appendPath('M12 6v6l4 2');
      break;
    case 'x':
      appendPath('M18 6 6 18');
      appendPath('m6 6 12 12');
      break;
    case 'sparkle':
      appendPath('M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z');
      appendPath('M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15z');
      break;
    case 'external':
      appendPath('M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6');
      appendPath('m15 3 6 0 0 6');
      appendPath('m10 14 11-11');
      break;
    default:
      appendCircle('12', '12', '8');
      break;
  }
  return svg;
}

// Brings a section to the top of the screen, below the sticky header (its CSS scroll-margin-top);
// smooth, or instant when the visitor has asked for reduced motion
export function scrollToSection(el) {
  if (!el) return;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  el.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
}

export function showToast(message, kind = 'info') {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${kind}`;
  toast.setAttribute('role', 'status');
  toast.setAttribute('aria-live', 'polite');
  toast.textContent = message;

  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('toast-fading');
    setTimeout(() => {
      toast.remove();
    }, 300);
  }, 5000);
}

// Two-letter initials for an avatar, from the Latin-script words of a business name.
export function initials(name) {
  const words = (name || '').split(/\s+/).filter(w => /[A-Za-z]/.test(w));
  const letters = words.slice(0, 2).map(w => w.replace(/[^A-Za-z]/g, '').charAt(0).toUpperCase()).join('');
  return letters || (name || '?').trim().charAt(0).toUpperCase() || '?';
}

// Field help (toggletips). Hover or keyboard focus shows the text (CSS); a tap or click pins it
// open (aria-expanded); Esc dismisses it and a click elsewhere closes it (WCAG 1.4.13). One open at a time.
export function initInfoTips() {
  const tips = [...document.querySelectorAll('.info-tip')];
  const close = (tip) => {
    tip.classList.remove('open');
    tip.querySelector('.info-tip-btn').setAttribute('aria-expanded', 'false');
  };

  tips.forEach(tip => {
    const btn = tip.querySelector('.info-tip-btn');
    btn.addEventListener('click', () => {
      const opening = !tip.classList.contains('open');
      tips.forEach(close);
      tip.classList.remove('dismissed');
      if (opening) {
        tip.classList.add('open');
        btn.setAttribute('aria-expanded', 'true');
      }
    });
    // A dismissed tip shows again once the pointer or focus has left it
    tip.addEventListener('mouseleave', () => tip.classList.remove('dismissed'));
    btn.addEventListener('blur', () => tip.classList.remove('dismissed'));
  });

  document.addEventListener('click', (e) => {
    tips.forEach(tip => { if (!tip.contains(e.target)) close(tip); });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    tips.forEach(tip => {
      if (tip.classList.contains('open') || tip.matches(':hover, :focus-within')) {
        close(tip);
        tip.classList.add('dismissed');
      }
    });
  });
}
