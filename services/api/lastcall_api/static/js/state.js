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
