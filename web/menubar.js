const API = 'http://127.0.0.1:7070';
let currentMode = 'blacklist';
let totalSecs = 0;
let countdownInterval = null;

const $ = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);

const els = {
    badge: $('#mbBadge'),
    badgeText: $('.status-text'),
    activeState: $('#activeState'),
    idleState: $('#idleState'),
    progress: $('#mbProgress'),
    time: $('#mbTime'),
    label: $('#mbLabel'),
    modeDisplay: $('#mbMode'),
    expiresDisplay: $('#mbExpires'),
    btnStart: $('#mbBtnStart'),
    btnStop: $('#mbBtnStop'),
    btnRescue: $('#mbBtnRescue'),
    durSelect: $('#mbDurSelect'),
    rescueDur: $('#mbRescueDur'),
    modeBtns: $$('.mode-btn')
};

async function api(method, path, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    try {
        const res = await fetch(API + path, opts);
        return await res.json();
    } catch {
        return { status: 'error', message: 'Offline' };
    }
}

function fmt(secs) {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function updateRing(rem) {
    const circ = 2 * Math.PI * 90; // 565.48
    const prog = totalSecs > 0 ? (1 - rem / totalSecs) : 0;
    els.progress.style.strokeDashoffset = circ * (1 - prog);
}

function startCountdown(rem) {
    if (countdownInterval) clearInterval(countdownInterval);
    els.time.textContent = fmt(rem);
    updateRing(rem);
    countdownInterval = setInterval(() => {
        rem--;
        if (rem <= 0) { rem = 0; clearInterval(countdownInterval); refresh(); }
        els.time.textContent = fmt(rem);
        updateRing(rem);
    }, 1000);
}

function renderStatus(data) {
    const active = data.active;
    
    if (active) {
        els.idleState.classList.add('hidden');
        els.activeState.classList.remove('hidden');
        
        let typeStr = data.session_type === 'rescue' ? 'Rescue Throne 🛡️' : data.mode.toUpperCase();
        els.modeDisplay.textContent = typeStr;
        els.expiresDisplay.textContent = `Expires: ${data.expires_at}`;
        
        els.badgeText.textContent = data.session_type === 'rescue' ? 'RESCUE' : 'ACTIVE';
        els.badge.classList.add('active');
        
        if (data.session_type === 'pomodoro') {
            totalSecs = data.pomo_phase_total || 1;
            startCountdown(data.pomo_phase_remaining || 0);
            els.label.textContent = data.pomo_phase.toUpperCase();
            if (data.pomo_phase === 'break') {
                $('.timer-ring').classList.add('break');
            } else {
                $('.timer-ring').classList.remove('break');
            }
        } else {
            totalSecs = data.total_duration_seconds || data.remaining_seconds;
            startCountdown(data.remaining_seconds);
            els.label.textContent = 'REMAINING';
            $('.timer-ring').classList.remove('break');
        }
        
    } else {
        els.idleState.classList.remove('hidden');
        els.activeState.classList.add('hidden');
        els.badgeText.textContent = 'Idle';
        els.badge.classList.remove('active');
        if (countdownInterval) clearInterval(countdownInterval);
    }
}

async function refresh() {
    const data = await api('GET', '/api/status');
    if (data.status === 'ok') {
        renderStatus(data);
    } else {
        els.badgeText.textContent = 'Offline';
        els.badge.classList.remove('active');
    }
}

function initEvents() {
    els.modeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            els.modeBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentMode = btn.dataset.mode;
        });
    });

    els.btnStart.addEventListener('click', async () => {
        els.btnStart.textContent = 'Starting...';
        const dur = parseInt(els.durSelect.value, 10);
        let payload = { duration: dur, mode: currentMode, session_type: 'standard' };
        
        if (dur === 25) { // Simple Pomodoro preset mapping for popover
            payload = {
                duration: 120, // arbitrary
                mode: currentMode,
                session_type: 'pomodoro',
                focus_minutes: 25,
                break_minutes: 5,
                cycles: 4
            };
        }
        
        const res = await api('POST', '/api/start', payload);
        els.btnStart.innerHTML = '<span class="btn-icon">▶</span> Start';
        if (res.status === 'ok') refresh();
    });

    els.btnRescue.addEventListener('click', async () => {
        els.btnRescue.textContent = 'Activating...';
        const dur = parseInt(els.rescueDur.value, 10);
        const res = await api('POST', '/api/start', {
            duration: dur,
            mode: 'whitelist',
            session_type: 'rescue'
        });
        els.btnRescue.textContent = '⚡ Activate';
        if (res.status === 'ok') refresh();
    });

    els.btnStop.addEventListener('click', async () => {
        // Since menubar is compact, we bypass the passphrase modal for 'stop' 
        // OR we can just open the main UI. For now, let's trigger a stop with empty key.
        // It will fail if a key is required, but it's okay for testing.
        // The proper way is to open `localhost:7070` to enter the kill switch.
        window.open('http://127.0.0.1:7070', '_blank');
    });
}

let globalPollInterval = null;

window.onPopoverShow = () => {
    refresh();
    if (globalPollInterval) clearInterval(globalPollInterval);
    globalPollInterval = setInterval(refresh, 2000);
};

window.onPopoverHide = () => {
    if (globalPollInterval) clearInterval(globalPollInterval);
    if (countdownInterval) clearInterval(countdownInterval);
};

document.addEventListener('DOMContentLoaded', () => {
    initEvents();
    // We do NOT start polling here.
    // The Swift wrapper calls window.onPopoverShow() when the view appears.
    // This saves CPU by ensuring JS is 100% idle when hidden.
});
