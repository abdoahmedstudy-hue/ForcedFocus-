/**
 * ForcedFocus Chrome Extension — Enhanced Popup Logic
 * Provides a rich user interface for controlling ForcedFocus sessions
 * with analytics, scheduling, and improved UX.
 */

const API = 'http://127.0.0.1:7070';
let mode = 'blacklist';
let duration = 120;
let countdown = null;
let totalSecs = 0;
let analytics = {
  blockedRequests: 0,
  allowedRequests: 0,
  startTime: Date.now()
};

let sessionType = 'standard';
let pomoFocusMin = 25;
let pomoBreakMin = 5;
let pomoCycles = 4;

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ── API ──────────────────────────────────────────────────────────────────────

async function api(method, path, body = null) {
  const opts = { 
    method, 
    headers: { 'Content-Type': 'application/json' },
    signal: AbortSignal.timeout(5000) // 5 second timeout
  };
  if (body) opts.body = JSON.stringify(body);
  
  try {
    const res = await fetch(API + path, opts);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    return await res.json();
  } catch (error) {
    console.error('[ForcedFocus] API Error:', error);
    throw error;
  }
}

async function checkServer() {
  try {
    const res = await fetch(API + '/api/status', { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch { 
    return false; 
  }
}

// ── Analytics ────────────────────────────────────────────────────────────────

async function updateAnalytics() {
  try {
    // Request analytics from background script
    const bgAnalytics = await chrome.runtime.sendMessage({ action: 'getAnalytics' });
    analytics = bgAnalytics || analytics;
    
    // Update UI elements
    if ($('#analyticsBlocked')) {
      $('#analyticsBlocked').textContent = analytics.blockedRequests.toLocaleString();
    }
    if ($('#analyticsAllowed')) {
      $('#analyticsAllowed').textContent = analytics.allowedRequests.toLocaleString();
    }
    
    // Calculate runtime
    const runtimeMs = Date.now() - analytics.startTime;
    const runtimeHours = Math.floor(runtimeMs / (1000 * 60 * 60));
    const runtimeMinutes = Math.floor((runtimeMs % (1000 * 60 * 60)) / (1000 * 60));
    
    if ($('#analyticsRuntime')) {
      $('#analyticsRuntime').textContent = `${runtimeHours}h ${runtimeMinutes}m`;
    }
  } catch (error) {
    console.warn('Could not fetch analytics:', error);
  }
}

async function resetAnalytics() {
  try {
    await chrome.runtime.sendMessage({ action: 'resetAnalytics' });
    analytics = {
      blockedRequests: 0,
      allowedRequests: 0,
      startTime: Date.now()
    };
    updateAnalytics();
  } catch (error) {
    console.error('Failed to reset analytics:', error);
  }
}

// ── Timer ────────────────────────────────────────────────────────────────────

function fmt(secs) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function updateRing(remaining) {
  const circ = 2 * Math.PI * 52; // 326.73
  const progress = totalSecs > 0 ? (1 - remaining / totalSecs) : 0;
  const ringProgress = $('#ringProgress');
  if (ringProgress) {
    ringProgress.style.strokeDashoffset = circ * (1 - progress);
  }
}

function startCountdown(secs) {
  if (countdown) clearInterval(countdown);
  let rem = secs;
  
  const timerValue = $('#timerValue');
  const timerLabel = $('#timerLabel');
  
  if (timerValue) timerValue.textContent = fmt(rem);
  if (timerLabel) timerLabel.textContent = 'REMAINING';
  
  updateRing(rem);
  
  countdown = setInterval(() => {
    rem--;
    if (rem <= 0) { 
      rem = 0; 
      clearInterval(countdown); 
      countdown = null; 
      refresh(); 
    }
    
    if (timerValue) timerValue.textContent = fmt(rem);
    updateRing(rem);
  }, 1000);
}

function stopCountdown() {
  if (countdown) { 
    clearInterval(countdown); 
    countdown = null; 
  }
  
  const timerValue = $('#timerValue');
  const timerLabel = $('#timerLabel');
  const ringProgress = $('#ringProgress');
  
  if (timerValue) timerValue.textContent = '00:00';
  if (timerLabel) timerLabel.textContent = 'READY';
  if (ringProgress) ringProgress.style.strokeDashoffset = 326.73;
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function renderStatus(data) {
  const active = data.active;
  const badge = $('#badge');
  
  // Badge
  if (badge) {
    badge.textContent = active ? (data.session_type === 'rescue' ? 'RESCUE' : data.mode.toUpperCase()) : 'Idle';
    badge.classList.toggle('active', active);
  }
  
  // Controls visibility
  const idleControls = $('#idleControls');
  const activeControls = $('#activeControls');
  const stopDialog = $('#stopDialog');
  
  if (idleControls) idleControls.classList.toggle('hidden', active);
  if (activeControls) activeControls.classList.toggle('hidden', !active);
  if (stopDialog) stopDialog.classList.add('hidden');
  
  if (active) {
    if (data.session_type === 'pomodoro') {
      totalSecs = data.pomo_phase_total || 1;
      startCountdown(data.pomo_phase_remaining || 0);
      
      const infoType = $('#infoType');
      if (infoType) infoType.textContent = 'Pomodoro';
      
      // Show pomodoro-specific elements
      const pomoPhaseRow = $('#pomoPhaseRow');
      const pomoCycleRow = $('#pomoCycleRow');
      
      if (pomoPhaseRow) pomoPhaseRow.style.display = 'flex';
      if (pomoCycleRow) pomoCycleRow.style.display = 'flex';
      
      const infoPhase = $('#infoPhase');
      if (infoPhase) {
        const dot = data.pomo_phase === 'break' ? 
          '<span class="phase-dot break"></span>' : 
          '<span class="phase-dot focus"></span>';
        infoPhase.innerHTML = `${dot} ${data.pomo_phase.toUpperCase()}`;
      }
      
      const infoCycle = $('#infoCycle');
      if (infoCycle) {
        infoCycle.textContent = `${data.pomo_current_cycle} / ${data.pomo_total_cycles}`;
      }
      
      const pomoNextRow = $('#pomoNextRow');
      const infoPomoNext = $('#infoPomoNext');
      
      if (data.pomo_phase_expiry_time) {
        if (pomoNextRow) pomoNextRow.style.display = 'flex';
        if (infoPomoNext) infoPomoNext.textContent = `${data.pomo_phase_expiry_time}`;
      } else {
        if (pomoNextRow) pomoNextRow.style.display = 'none';
      }
      
      const timerRing = $('.timer-ring');
      const timerLabel = $('#timerLabel');
      
      if (data.pomo_phase === 'break') {
        if (timerRing) timerRing.classList.add('break');
        if (timerLabel) timerLabel.textContent = 'BREAK';
      } else {
        if (timerRing) timerRing.classList.remove('break');
        if (timerLabel) timerLabel.textContent = 'FOCUS';
      }
    } else {
      totalSecs = data.total_duration_seconds || data.remaining_seconds;
      startCountdown(data.remaining_seconds);
      
      const infoType = $('#infoType');
      if (infoType) infoType.textContent = 'Standard';
      
      // Hide pomodoro-specific elements
      const pomoPhaseRow = $('#pomoPhaseRow');
      const pomoCycleRow = $('#pomoCycleRow');
      const pomoNextRow = $('#pomoNextRow');
      
      if (pomoPhaseRow) pomoPhaseRow.style.display = 'none';
      if (pomoCycleRow) pomoCycleRow.style.display = 'none';
      if (pomoNextRow) pomoNextRow.style.display = 'none';
      
      const timerRing = $('.timer-ring');
      if (timerRing) timerRing.classList.remove('break');
    }
    
    // Session mode/type info
    const infoMode = $('#infoMode');
    if (infoMode) {
      if (data.session_type === 'rescue') {
        infoMode.textContent = 'Rescue Throne 🛡️';
      } else {
        infoMode.textContent = data.mode;
      }
    }
    
    const infoExpires = $('#infoExpires');
    if (infoExpires) infoExpires.textContent = data.expires_at;
    
    // Unlock info
    const unlockRow = $('#unlockRow');
    const infoUnlock = $('#infoUnlock');
    
    if (data.pending_unlock) {
      if (unlockRow) unlockRow.style.display = 'flex';
      if (infoUnlock) infoUnlock.textContent = data.pending_unlock;
    } else {
      if (unlockRow) unlockRow.style.display = 'none';
    }
  } else {
    totalSecs = 0;
    stopCountdown();
    
    const timerRing = $('.timer-ring');
    if (timerRing) timerRing.classList.remove('break');
  }
}

async function refresh() {
  try {
    const data = await api('GET', '/api/status');
    if (data.status === 'ok') {
      renderStatus(data);
      updateAnalytics();
    }
  } catch (error) {
    console.error('Failed to refresh status:', error);
  }
}

// ── Event Handlers ───────────────────────────────────────────────────────────

function initEvents() {
  // Mode chips
  $$('.mode-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.mode-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      mode = btn.dataset.mode;
    });
  });
  
  // Session Type chips
  $$('.type-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.type-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      sessionType = btn.dataset.type;
      
      const standardControls = $('#standardControls');
      const pomoControls = $('#pomoControls');
      
      if (sessionType === 'pomodoro') {
        if (standardControls) standardControls.classList.add('hidden');
        if (pomoControls) pomoControls.classList.remove('hidden');
        updatePomoSummary();
      } else {
        if (standardControls) standardControls.classList.remove('hidden');
        if (pomoControls) pomoControls.classList.add('hidden');
      }
    });
  });
  
  // Duration chips
  $$('.dur-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.dur-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      duration = parseInt(btn.dataset.min);
      
      const customMin = $('#customMin');
      if (customMin) customMin.value = '';
    });
  });
  
  // Custom minutes input
  const customMin = $('#customMin');
  if (customMin) {
    customMin.addEventListener('input', () => {
      const val = parseInt(customMin.value);
      if (val > 0) {
        $$('.dur-chip').forEach(b => b.classList.remove('active'));
        duration = val;
      }
    });
  }
  
  // Pomodoro chips & inputs
  function updatePomoSummary() {
    const pomoFocus = $('#pomoFocus');
    const pomoBreak = $('#pomoBreak');
    const pomoCyclesInput = $('#pomoCycles');
    const pomoTotal = $('#pomoTotal');
    
    if (pomoFocus) pomoFocusMin = parseInt(pomoFocus.value) || 25;
    if (pomoBreak) pomoBreakMin = parseInt(pomoBreak.value) || 5;
    if (pomoCyclesInput) pomoCycles = parseInt(pomoCyclesInput.value) || 4;
    
    const total = (pomoFocusMin + pomoBreakMin) * pomoCycles;
    const h = Math.floor(total / 60);
    const m = total % 60;
    
    if (pomoTotal) {
      pomoTotal.textContent = `Total: ${h}h ${String(m).padStart(2,'0')}m`;
    }
  }
  
  $$('.pomo-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.pomo-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      
      const pomoFocus = $('#pomoFocus');
      const pomoBreak = $('#pomoBreak');
      
      if (pomoFocus) pomoFocus.value = btn.dataset.focus;
      if (pomoBreak) pomoBreak.value = btn.dataset.break;
      
      updatePomoSummary();
    });
  });
  
  ['#pomoFocus', '#pomoBreak', '#pomoCycles'].forEach(selector => {
    const element = $(selector);
    if (element) {
      element.addEventListener('input', () => {
        $$('.pomo-chip').forEach(b => b.classList.remove('active'));
        updatePomoSummary();
      });
    }
  });
  
  // Start button
  const btnStart = $('#btnStart');
  if (btnStart) {
    btnStart.addEventListener('click', async () => {
      btnStart.textContent = '⏳ Starting...';
      
      let payload = {};
      if (sessionType === 'pomodoro') {
        const totalMin = (pomoFocusMin + pomoBreakMin) * pomoCycles;
        totalSecs = totalMin * 60;
        payload = {
          duration: totalMin,
          mode: mode,
          session_type: 'pomodoro',
          focus_minutes: pomoFocusMin,
          break_minutes: pomoBreakMin,
          cycles: pomoCycles
        };
      } else {
        totalSecs = duration * 60;
        payload = { duration, mode, session_type: 'standard' };
      }
      
      try {
        const res = await api('POST', '/api/start', payload);
        btnStart.textContent = '▶ Start Blocking';
        if (res.status === 'ok') {
          await refresh();
        } else {
          alert(`Failed to start session: ${res.message}`);
        }
      } catch (error) {
        btnStart.textContent = '▶ Start Blocking';
        alert(`Failed to start session: ${error.message}`);
      }
    });
  }
  
  // Rescue button
  const btnRescue = $('#btnRescue');
  if (btnRescue) {
    btnRescue.addEventListener('click', async () => {
      btnRescue.textContent = '⏳ Activating...';
      
      const rescueDuration = $('#rescueDuration');
      const dur = rescueDuration ? (parseInt(rescueDuration.value, 10) || 10) : 10;
      
      const payload = {
        duration: dur,
        mode: 'whitelist',
        session_type: 'rescue'
      };
      
      try {
        const res = await api('POST', '/api/start', payload);
        btnRescue.innerHTML = '⚡ Activate Rescue';
        if (res.status === 'ok') {
          await refresh();
        } else {
          alert(`Failed to activate rescue: ${res.message}`);
        }
      } catch (error) {
        btnRescue.innerHTML = '⚡ Activate Rescue';
        alert(`Failed to activate rescue: ${error.message}`);
      }
    });
  }
  
  // Stop → show dialog
  const btnStop = $('#btnStop');
  if (btnStop) {
    btnStop.addEventListener('click', () => {
      const stopDialog = $('#stopDialog');
      const passInput = $('#passInput');
      const errMsg = $('#errMsg');
      
      if (stopDialog) stopDialog.classList.remove('hidden');
      if (passInput) {
        passInput.value = '';
        passInput.focus();
      }
      if (errMsg) errMsg.classList.add('hidden');
    });
  }
  
  // Cancel unlock
  const btnCancel = $('#btnCancel');
  if (btnCancel) {
    btnCancel.addEventListener('click', () => {
      const stopDialog = $('#stopDialog');
      if (stopDialog) stopDialog.classList.add('hidden');
    });
  }
  
  // Confirm unlock
  const btnConfirm = $('#btnConfirm');
  if (btnConfirm) {
    btnConfirm.addEventListener('click', async () => {
      const passInput = $('#passInput');
      const errMsg = $('#errMsg');
      
      const key = passInput ? passInput.value : '';
      if (!key) {
        if (errMsg) {
          errMsg.textContent = 'Enter passphrase.';
          errMsg.classList.remove('hidden');
        }
        return;
      }
      
      try {
        const res = await api('POST', '/api/stop', { key });
        if (res.status === 'pending' || res.status === 'ok') {
          const stopDialog = $('#stopDialog');
          if (stopDialog) stopDialog.classList.add('hidden');
          await refresh();
        } else {
          if (errMsg) {
            errMsg.textContent = res.message || 'Invalid passphrase.';
            errMsg.classList.remove('hidden');
          }
        }
      } catch (error) {
        if (errMsg) {
          errMsg.textContent = `Connection error: ${error.message}`;
          errMsg.classList.remove('hidden');
        }
      }
    });
  }
  
  // Enter key in passphrase
  const passInput = $('#passInput');
  if (passInput) {
    passInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const btnConfirm = $('#btnConfirm');
        if (btnConfirm) btnConfirm.click();
      }
    });
  }
  
  // Analytics reset
  const resetAnalyticsBtn = $('#resetAnalytics');
  if (resetAnalyticsBtn) {
    resetAnalyticsBtn.addEventListener('click', async () => {
      if (confirm('Are you sure you want to reset all analytics data?')) {
        await resetAnalytics();
      }
    });
  }
}

// ── Initialization ───────────────────────────────────────────────────────────

async function init() {
  const offline = $('#offline');
  const main = $('#main');
  
  const online = await checkServer();
  if (!online) {
    if (offline) offline.classList.remove('hidden');
    if (main) main.classList.add('hidden');
    return;
  }
  
  if (offline) offline.classList.add('hidden');
  if (main) main.classList.remove('hidden');
  
  initEvents();
  await refresh();
  
  // Poll every 2s for status updates
  setInterval(refresh, 2000);
  
  // Initial analytics update
  updateAnalytics();
}

document.addEventListener('DOMContentLoaded', init);