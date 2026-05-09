/**
 * ForcedFocus Chrome Extension — Popup Logic
 */

const API = 'http://127.0.0.1:7070';
let mode = 'blacklist';
let duration = 120;
let countdown = null;
let totalSecs = 0;

let sessionType = 'standard';
let pomoFocusMin = 25;
let pomoBreakMin = 5;
let pomoCycles = 4;

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ── API ──────────────────────────────────────────────────────────────────────

async function api(method, path, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(API + path, opts);
    return await res.json();
}

async function checkServer() {
    try {
        const res = await fetch(API + '/api/status', { signal: AbortSignal.timeout(2000) });
        return res.ok;
    } catch { return false; }
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
    $('#ringProgress').style.strokeDashoffset = circ * (1 - progress);
}

function startCountdown(secs) {
    if (countdown) clearInterval(countdown);
    let rem = secs;
    $('#timerValue').textContent = fmt(rem);
    $('#timerLabel').textContent = 'REMAINING';
    updateRing(rem);
    countdown = setInterval(() => {
        rem--;
        if (rem <= 0) { rem = 0; clearInterval(countdown); countdown = null; refresh(); }
        $('#timerValue').textContent = fmt(rem);
        updateRing(rem);
    }, 1000);
}

function stopCountdown() {
    if (countdown) { clearInterval(countdown); countdown = null; }
    $('#timerValue').textContent = '00:00';
    $('#timerLabel').textContent = 'READY';
    $('#ringProgress').style.strokeDashoffset = 326.73;
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderStatus(data) {
    const active = data.active;

    // Badge
    $('#badge').textContent = active ? (data.session_type === 'rescue' ? 'RESCUE' : data.mode.toUpperCase()) : 'Idle';
    $('#badge').classList.toggle('active', active);

    // Controls
    $('#idleControls').classList.toggle('hidden', active);
    $('#activeControls').classList.toggle('hidden', !active);
    $('#stopDialog').classList.add('hidden');

    if (active) {
        if (data.session_type === 'pomodoro') {
            totalSecs = data.pomo_phase_total || 1;
            startCountdown(data.pomo_phase_remaining || 0);
            
            $('#infoType').textContent = 'Pomodoro';
            $('#pomoPhaseRow').style.display = 'flex';
            $('#pomoCycleRow').style.display = 'flex';
            
            const dot = data.pomo_phase === 'break' ? '<span class="phase-dot break"></span>' : '<span class="phase-dot focus"></span>';
            $('#infoPhase').innerHTML = `${dot} ${data.pomo_phase.toUpperCase()}`;
            $('#infoCycle').textContent = `${data.pomo_current_cycle} / ${data.pomo_total_cycles}`;
            
            if (data.pomo_phase_expiry_time) {
                $('#pomoNextRow').style.display = 'flex';
                $('#infoPomoNext').textContent = `${data.pomo_phase_expiry_time}`;
            } else {
                $('#pomoNextRow').style.display = 'none';
            }
            
            if (data.pomo_phase === 'break') {
                $('.timer-ring').classList.add('break');
                $('#timerLabel').textContent = 'BREAK';
            } else {
                $('.timer-ring').classList.remove('break');
                $('#timerLabel').textContent = 'FOCUS';
            }
        } else {
            totalSecs = data.total_duration_seconds || data.remaining_seconds;
            startCountdown(data.remaining_seconds);
            $('#infoType').textContent = 'Standard';
            $('#pomoPhaseRow').style.display = 'none';
            $('#pomoCycleRow').style.display = 'none';
            $('#pomoNextRow').style.display = 'none';
            $('.timer-ring').classList.remove('break');
        }

        if (data.session_type === 'rescue') {
            $('#infoMode').textContent = 'Rescue Throne 🛡️';
        } else {
            $('#infoMode').textContent = data.mode;
        }
        $('#infoExpires').textContent = data.expires_at;

        if (data.pending_unlock) {
            $('#unlockRow').style.display = 'flex';
            $('#infoUnlock').textContent = data.pending_unlock;
        } else {
            $('#unlockRow').style.display = 'none';
        }
    } else {
        totalSecs = 0;
        stopCountdown();
        $('.timer-ring').classList.remove('break');
    }
}

async function refresh() {
    try {
        const data = await api('GET', '/api/status');
        if (data.status === 'ok') renderStatus(data);
    } catch {}
}

// ── Events ───────────────────────────────────────────────────────────────────

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
            if (sessionType === 'pomodoro') {
                $('#standardControls').classList.add('hidden');
                $('#pomoControls').classList.remove('hidden');
                updatePomoSummary();
            } else {
                $('#standardControls').classList.remove('hidden');
                $('#pomoControls').classList.add('hidden');
            }
        });
    });

    // Duration chips
    $$('.dur-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.dur-chip').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            duration = parseInt(btn.dataset.min);
            $('#customMin').value = '';
        });
    });

    // Custom minutes input
    $('#customMin').addEventListener('input', () => {
        const val = parseInt($('#customMin').value);
        if (val > 0) {
            $$('.dur-chip').forEach(b => b.classList.remove('active'));
            duration = val;
        }
    });

    // Pomodoro chips & inputs
    function updatePomoSummary() {
        pomoFocusMin = parseInt($('#pomoFocus').value) || 25;
        pomoBreakMin = parseInt($('#pomoBreak').value) || 5;
        pomoCycles = parseInt($('#pomoCycles').value) || 4;
        const total = (pomoFocusMin + pomoBreakMin) * pomoCycles;
        const h = Math.floor(total / 60);
        const m = total % 60;
        $('#pomoTotal').textContent = `Total: ${h}h ${String(m).padStart(2,'0')}m`;
    }

    $$('.pomo-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.pomo-chip').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            $('#pomoFocus').value = btn.dataset.focus;
            $('#pomoBreak').value = btn.dataset.break;
            updatePomoSummary();
        });
    });

    ['#pomoFocus', '#pomoBreak', '#pomoCycles'].forEach(id => {
        $(id).addEventListener('input', () => {
            $$('.pomo-chip').forEach(b => b.classList.remove('active'));
            updatePomoSummary();
        });
    });

    // Start
    $('#btnStart').addEventListener('click', async () => {
        $('#btnStart').textContent = '⏳ Starting...';
        
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
        
        const res = await api('POST', '/api/start', payload);
        $('#btnStart').textContent = '▶ Start Blocking';
        if (res.status === 'ok') refresh();
    });

    // Rescue
    const btnRescue = $('#btnRescue');
    if (btnRescue) {
        btnRescue.addEventListener('click', async () => {
            btnRescue.textContent = '⏳ Activating...';
            const dur = parseInt($('#rescueDuration').value, 10) || 10;
            const payload = {
                duration: dur,
                mode: 'whitelist',
                session_type: 'rescue'
            };
            const res = await api('POST', '/api/start', payload);
            btnRescue.innerHTML = '⚡ Activate Rescue';
            if (res.status === 'ok') refresh();
        });
    }

    // Stop → show dialog
    $('#btnStop').addEventListener('click', () => {
        $('#stopDialog').classList.remove('hidden');
        $('#passInput').value = '';
        $('#errMsg').classList.add('hidden');
        $('#passInput').focus();
    });

    // Cancel
    $('#btnCancel').addEventListener('click', () => {
        $('#stopDialog').classList.add('hidden');
    });

    // Confirm unlock
    $('#btnConfirm').addEventListener('click', async () => {
        const key = $('#passInput').value;
        if (!key) {
            $('#errMsg').textContent = 'Enter passphrase.';
            $('#errMsg').classList.remove('hidden');
            return;
        }
        const res = await api('POST', '/api/stop', { key });
        if (res.status === 'pending' || res.status === 'ok') {
            $('#stopDialog').classList.add('hidden');
            refresh();
        } else {
            $('#errMsg').textContent = res.message || 'Invalid passphrase.';
            $('#errMsg').classList.remove('hidden');
        }
    });

    // Enter key in passphrase
    $('#passInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') $('#btnConfirm').click();
    });
}

// ── Init ─────────────────────────────────────────────────────────────────────

async function init() {
    const online = await checkServer();
    if (!online) {
        $('#offline').classList.remove('hidden');
        $('#main').classList.add('hidden');
        return;
    }

    initEvents();
    await refresh();
    // Poll every 2s
    setInterval(refresh, 2000);
}

document.addEventListener('DOMContentLoaded', init);
