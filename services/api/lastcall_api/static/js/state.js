// services/api/lastcall_api/static/js/state.js

export const state = {
  activeSampleBlob: null,
  activeSampleUrl: null,
  currentInspection: null,
  currentLadderResult: null,
  currentDisplayUrl: null,
  activeItemKey: null,
  priceOverrides: {},
  isDeciding: false,
  decideRequestCounter: 0,
  scoutResultsMap: {},
  scoutErrorsMap: {},
  scoutLoadingMap: {},
  scoutRequestCounters: {},
  currentBatchesMap: {},
  staffCheckedMap: {},
  quantityInputs: {},
  quantityEdited: {},
  isCallInProgress: false,
  isInspecting: false,
  currentActiveCall: null,

  ws: null,
  audioCtx: null,
  micStream: null,
  captureNode: null,
  playbackNode: null,
  retryCount: 0,

  callTimerInterval: null,
  callStartTime: 0,
  waveformTimer: null
};

// The mart's time on the page (D74): the real time moved by the current decision's shift (0 for "Now" and
// without a decision). Once a shelf has calls its decision can't change (lock.js), so this is also the time of its
// batches and calls, whose pickup and call-back times the page shows.
export function martNow(now = new Date()) {
  const offsetS = (state.currentLadderResult && state.currentLadderResult.clock_offset_s) || 0;
  return new Date(now.getTime() + offsetS * 1000);
}
