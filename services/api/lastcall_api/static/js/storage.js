// services/api/lastcall_api/static/js/storage.js

export function getStoredItem(key, defaultVal = '') {
  try {
    const val = localStorage.getItem(key);
    return val !== null ? val : defaultVal;
  } catch (e) {
    console.warn('getStoredItem', e);
    return defaultVal;
  }
}

export function setStoredItem(key, val) {
  try {
    localStorage.setItem(key, val);
  } catch (e) {
    console.warn('setStoredItem', e);
  }
}

export function generateShelfId() {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  let randStr = '';
  for (let i = 0; i < 8; i++) {
    randStr += chars[bytes[i] % chars.length];
  }
  return 'demo_' + randStr;
}

export function getOrCreateShelfId() {
  let id = getStoredItem('lc_shelf_id', '');
  if (!id || !/^demo_[a-z0-9]{8}$/.test(id)) {
    id = generateShelfId();
    setStoredItem('lc_shelf_id', id);
  }
  return id;
}

export function resetShelfId() {
  const id = generateShelfId();
  setStoredItem('lc_shelf_id', id);
  return id;
}
