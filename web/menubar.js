const API = 'http://127.0.0.1:7070';
let currentMode = 'blacklist';
let currentType = 'standard';
let totalSecs = 0;
let countdownInterval = null;

const AudioManager = {
    settings: {},
    play: function(type) {
        const file = this.settings[`sound_${type}`];
        if (!file) return;
        const audio = new Audio('/sounds/' + encodeURIComponent(file));
        audio.play().catch(e => console.log('Audio error:', e));
    }
};

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
    
    // Info Grid
    infoMode: $('#mbInfoMode'),
    infoType: $('#mbInfoType'),
    infoExpires: $('#mbInfoExpires'),
    infoNext: $('#mbInfoNext'),
    infoNextTime: $('#mbInfoNextTime'),
    nextRow: $('#mbNextRow'),
    
    btnStart: $('#mbBtnStart'),
    btnStop: $('#mbBtnStop'),
    mbBtnRescue: $('#mbBtnRescue'),
    rescueDur: $('#rescueDur'),
    
    // Switchers
    modeChips: $$('.mode-chip'),
    typeChips: $$('.type-chip'),
    durChips: $$('.dur-chip'),
    pomoChips: $$('.pomo-chip'),
    
    // Sections
    standardSection: $('#standardSection'),
    pomoSection: $('#pomoSection'),
    
    // Inputs
    customMin: $('#customMin'),
    pomoFocus: $('#pomoFocus'),
    pomoBreak: $('#pomoBreak'),
    pomoCycles: $('#pomoCycles')
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

function fmtClock(secs) {
    const now = new Date();
    const future = new Date(now.getTime() + secs * 1000);
    let h = future.getHours();
    const m = future.getMinutes();
    const ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12;
    h = h ? h : 12; // the hour '0' should be '12'
    return `${h}:${String(m).padStart(2, '0')} ${ampm}`;
}

function updateRing(rem) {
    const circ = 565.48; // 2 * Math.PI * 90
    els.progress.style.strokeDasharray = circ;
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
        if (els.infoNextTime) els.infoNextTime.textContent = fmtClock(rem);
        updateRing(rem);
    }, 1000);
}

function renderStatus(data) {
    const active = data.active;
    
    if (active) {
        els.idleState.classList.add('hidden');
        els.activeState.classList.remove('hidden');
        
        // Populate Info Grid
        els.infoMode.textContent = data.session_type === 'rescue' ? 'RESCUE' : data.mode.toUpperCase();
        els.infoType.textContent = data.session_type.toUpperCase();
        els.infoExpires.textContent = data.expires_at || '--:--';
        
        els.badgeText.textContent = data.session_type === 'rescue' ? 'RESCUE' : 'ACTIVE';
        els.badge.classList.add('active');
        
        if (data.session_type === 'pomodoro') {
            totalSecs = data.pomo_phase_total || 1;
            startCountdown(data.pomo_phase_remaining || 0);
            els.label.textContent = data.pomo_phase.toUpperCase();
            
            els.nextRow.classList.remove('hidden');
            els.infoNext.textContent = (data.pomo_phase === 'focus' ? 'BREAK' : 'FOCUS');
            
            if (data.pomo_phase === 'break') {
                $('.timer-ring').classList.add('break');
            } else {
                $('.timer-ring').classList.remove('break');
            }
        } else {
            totalSecs = data.total_duration_seconds || data.remaining_seconds;
            startCountdown(data.remaining_seconds);
            els.label.textContent = 'REMAINING';
            els.nextRow.classList.add('hidden');
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
    // Mode switcher
    els.modeChips.forEach(btn => {
        btn.addEventListener('click', () => {
            els.modeChips.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentMode = btn.dataset.mode;
        });
    });

    // Type switcher
    els.typeChips.forEach(btn => {
        btn.addEventListener('click', () => {
            els.typeChips.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentType = btn.dataset.type;
            
            if (currentType === 'pomodoro') {
                els.standardSection.classList.add('hidden');
                els.pomoSection.classList.remove('hidden');
            } else {
                els.standardSection.classList.remove('hidden');
                els.pomoSection.classList.add('hidden');
            }
        });
    });

    // Duration chips
    els.durChips.forEach(btn => {
        btn.addEventListener('click', () => {
            els.durChips.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            els.customMin.value = '';
        });
    });

    els.customMin.addEventListener('input', () => {
        els.durChips.forEach(b => b.classList.remove('active'));
    });

    // Pomodoro chips
    els.pomoChips.forEach(btn => {
        btn.addEventListener('click', () => {
            els.pomoChips.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            els.pomoFocus.value = btn.dataset.focus;
            els.pomoBreak.value = btn.dataset.break;
        });
    });

    els.btnStart.addEventListener('click', async () => {
        els.btnStart.textContent = 'Starting...';
        
        let payload = { mode: currentMode, session_type: currentType };
        
        if (currentType === 'standard') {
            const activeDur = Array.from(els.durChips).find(c => c.classList.contains('active'));
            const custom = parseInt(els.customMin.value, 10);
            payload.duration = custom || (activeDur ? parseInt(activeDur.dataset.min, 10) : 60);
        } else {
            payload.focus_minutes = parseInt(els.pomoFocus.value, 10) || 25;
            payload.break_minutes = parseInt(els.pomoBreak.value, 10) || 5;
            payload.cycles = parseInt(els.pomoCycles.value, 10) || 4;
            payload.duration = (payload.focus_minutes + payload.break_minutes) * payload.cycles;
        }
        
        const res = await api('POST', '/api/start', payload);
        els.btnStart.textContent = '▶ Start Session';
        if (res.status === 'ok') {
            AudioManager.play('start');
            refresh();
        }
    });

    els.mbBtnRescue.addEventListener('click', async () => {
        els.mbBtnRescue.textContent = 'Activating...';
        const dur = parseInt(els.rescueDur.value, 10);
        const res = await api('POST', '/api/start', {
            duration: dur,
            mode: 'whitelist',
            session_type: 'rescue'
        });
        els.mbBtnRescue.textContent = 'Activate Rescue';
        if (res.status === 'ok') {
            AudioManager.play('rescue');
            refresh();
        }
    });

    els.btnStop.addEventListener('click', async () => {
        AudioManager.play('unlock');
        // Redirect to full UI for unlock passphrase
        window.open('http://127.0.0.1:7070', '_blank');
    });
}

let globalPollInterval = null;

window.onPopoverShow = () => {
    loadSettings();
    refresh();
    if (globalPollInterval) clearInterval(globalPollInterval);
    globalPollInterval = setInterval(refresh, 2000);
};

async function loadSettings() {
    try {
        const res = await api('GET', '/api/settings');
        if (res.settings) {
            AudioManager.settings = res.settings;
        }
    } catch (e) {
        console.error("Failed to load settings:", e);
    }
}

window.onPopoverHide = () => {
    if (globalPollInterval) clearInterval(globalPollInterval);
    if (countdownInterval) clearInterval(countdownInterval);
};

document.addEventListener('DOMContentLoaded', () => {
    initEvents();
});
