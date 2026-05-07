/**
 * ForcedFocus Chrome Extension — Popup Logic
 */

const API = 'http://127.0.0.1:7070';
let mode = 'blacklist';
let duration = 120;
let countdown = null;
let totalSecs = 0;

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
    $('#badge').textContent = active ? data.mode.toUpperCase() : 'Idle';
    $('#badge').classList.toggle('active', active);

    // Controls
    $('#idleControls').classList.toggle('hidden', active);
    $('#activeControls').classList.toggle('hidden', !active);
    $('#stopDialog').classList.add('hidden');

    if (active) {
        totalSecs = data.total_duration_seconds || data.remaining_seconds;
        $('#infoMode').textContent = data.mode;
        $('#infoExpires').textContent = data.expires_at;
        startCountdown(data.remaining_seconds);

        if (data.pending_unlock) {
            $('#unlockRow').style.display = 'flex';
            $('#infoUnlock').textContent = data.pending_unlock;
        } else {
            $('#unlockRow').style.display = 'none';
        }
    } else {
        totalSecs = 0;
        stopCountdown();
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

    // Start
    $('#btnStart').addEventListener('click', async () => {
        $('#btnStart').textContent = '⏳ Starting...';
        totalSecs = duration * 60;
        const res = await api('POST', '/api/start', { duration, mode });
        $('#btnStart').textContent = '▶ Start Blocking';
        if (res.status === 'ok') refresh();
    });

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
