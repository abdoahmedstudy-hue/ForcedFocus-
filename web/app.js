/**
 * ForcedFocus — Web UI Client
 * Handles countdown timer, API calls, domain management, and UI state.
 */

const API = '';
let currentMode = 'blacklist';
let selectedDuration = 120;
let countdownInterval = null;
let pollInterval = null;
let totalSessionSeconds = 0;

// ── DOM Elements ─────────────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {
    statusBadge:      $('#statusBadge'),
    timerSection:     $('#timerSection'),
    timerRing:        $('#timerRing'),
    timerProgress:    $('#timerProgress'),
    timerValue:       $('#timerValue'),
    timerLabel:       $('#timerLabel'),
    modeDisplay:      $('#modeDisplay'),
    expiresDisplay:   $('#expiresDisplay'),
    modeCard:         $('#modeCard'),
    durationCard:     $('#durationCard'),
    btnStart:         $('#btnStart'),
    btnStop:          $('#btnStop'),
    unlockInfo:       $('#unlockInfo'),
    blacklistInput:   $('#blacklistInput'),
    whitelistInput:   $('#whitelistInput'),
    blacklistDomains: $('#blacklistDomains'),
    whitelistDomains: $('#whitelistDomains'),
    blacklistCount:   $('#blacklistCount'),
    whitelistCount:   $('#whitelistCount'),
    stopModal:        $('#stopModal'),
    passphraseInput:  $('#passphraseInput'),
    modalError:       $('#modalError'),
    toast:            $('#toast'),
    customMinutes:    $('#customMinutes'),
};

// ── API Helpers ──────────────────────────────────────────────────────────────

async function api(method, path, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    try {
        const res = await fetch(API + path, opts);
        return await res.json();
    } catch (err) {
        return { status: 'error', message: 'Network error: ' + err.message };
    }
}

// ── Toast ────────────────────────────────────────────────────────────────────

function showToast(msg, duration = 3000) {
    els.toast.textContent = msg;
    els.toast.classList.remove('hidden');
    els.toast.classList.add('show');
    setTimeout(() => {
        els.toast.classList.remove('show');
        setTimeout(() => els.toast.classList.add('hidden'), 300);
    }, duration);
}

// ── Timer ────────────────────────────────────────────────────────────────────

function formatTime(totalSeconds) {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function updateTimerDisplay(remainingSeconds) {
    els.timerValue.textContent = formatTime(remainingSeconds);
    // Update progress ring
    const circumference = 2 * Math.PI * 90; // 565.48
    const progress = totalSessionSeconds > 0
        ? (1 - remainingSeconds / totalSessionSeconds)
        : 0;
    const offset = circumference * (1 - progress);
    els.timerProgress.style.strokeDashoffset = offset;
}

function startCountdown(remainingSeconds) {
    if (countdownInterval) clearInterval(countdownInterval);
    let remaining = remainingSeconds;
    updateTimerDisplay(remaining);

    countdownInterval = setInterval(() => {
        remaining--;
        if (remaining <= 0) {
            remaining = 0;
            clearInterval(countdownInterval);
            countdownInterval = null;
            refreshStatus();
        }
        updateTimerDisplay(remaining);
    }, 1000);
}

function stopCountdown() {
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }
    updateTimerDisplay(0);
    els.timerProgress.style.strokeDashoffset = 565.48;
}

// ── UI State ─────────────────────────────────────────────────────────────────

function setActiveUI(status) {
    const active = status.active;

    // Status badge
    els.statusBadge.classList.toggle('active', active);
    els.statusBadge.querySelector('.status-text').textContent = active
        ? status.mode.toUpperCase()
        : 'Idle';

    // Timer ring
    els.timerRing.classList.toggle('active', active);
    els.timerLabel.textContent = active ? 'REMAINING' : 'READY';

    // Mode & duration cards
    els.modeCard.classList.toggle('disabled', active);
    els.durationCard.classList.toggle('disabled', active);

    // Start/stop buttons
    els.btnStart.classList.toggle('hidden', active);
    els.btnStop.classList.toggle('hidden', !active);

    // Mode & expires info
    if (active) {
        els.modeDisplay.textContent = `Mode: ${status.mode}`;
        els.expiresDisplay.textContent = `Expires: ${status.expires_at}`;
    } else {
        els.modeDisplay.textContent = '—';
        els.expiresDisplay.textContent = '—';
    }

    // Pending unlock
    if (status.pending_unlock) {
        els.unlockInfo.classList.remove('hidden');
        const unlockSecs = status.pending_unlock_seconds || 0;
        els.unlockInfo.querySelector('p').textContent =
            `⏱ Unlock pending — releases at ${status.pending_unlock} (${formatTime(unlockSecs)} left)`;
    } else {
        els.unlockInfo.classList.add('hidden');
    }

    // Timer
    if (active) {
        totalSessionSeconds = status.total_duration_seconds || status.remaining_seconds;
        startCountdown(status.remaining_seconds);
    } else {
        totalSessionSeconds = 0;
        stopCountdown();
        els.timerValue.textContent = '00:00:00';
    }
}

// ── Refresh Status ───────────────────────────────────────────────────────────

async function refreshStatus() {
    const data = await api('GET', '/api/status');
    if (data.status === 'ok') {
        setActiveUI(data);
    }
}

// ── Refresh Lists ────────────────────────────────────────────────────────────

async function refreshLists() {
    const data = await api('GET', '/api/lists');
    if (data.status !== 'ok') return;

    const lists = data.lists;
    renderDomainList(els.blacklistDomains, lists.blacklist || [], 'blacklist');
    renderDomainList(els.whitelistDomains, lists.whitelist || [], 'whitelist');
    els.blacklistCount.textContent = (lists.blacklist || []).length;
    els.whitelistCount.textContent = (lists.whitelist || []).length;
}

function renderDomainList(container, domains, listName) {
    container.innerHTML = '';
    domains.forEach(domain => {
        const li = document.createElement('li');
        const span = document.createElement('span');
        span.textContent = domain;
        const removeBtn = document.createElement('button');
        removeBtn.className = 'remove-btn';
        removeBtn.dataset.list = listName;
        removeBtn.dataset.domain = domain;
        removeBtn.textContent = '✕';
        removeBtn.addEventListener('click', async () => {
            const res = await api('DELETE', `/api/lists/${listName}/${domain}`);
            if (res.status === 'ok') {
                showToast(`Removed ${domain}`);
                refreshLists();
            } else {
                showToast('Error: ' + res.message);
            }
        });
        li.appendChild(span);
        li.appendChild(removeBtn);
        container.appendChild(li);
    });
}

// ── Event Handlers ───────────────────────────────────────────────────────────

function initEvents() {
    // Mode toggle
    $$('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentMode = btn.dataset.mode;
        });
    });

    // Duration buttons
    $$('.dur-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.dur-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedDuration = parseInt(btn.dataset.minutes);
            els.customMinutes.value = '';
        });
    });

    // Custom duration
    els.customMinutes.addEventListener('input', () => {
        const val = parseInt(els.customMinutes.value);
        if (val > 0) {
            $$('.dur-btn').forEach(b => b.classList.remove('active'));
            selectedDuration = val;
        }
    });

    // Start button
    els.btnStart.addEventListener('click', async () => {
        const duration = selectedDuration;
        totalSessionSeconds = duration * 60;
        els.btnStart.textContent = '⏳ Starting...';
        const res = await api('POST', '/api/start', { duration, mode: currentMode });
        els.btnStart.innerHTML = '<span class="btn-icon">▶</span> Start Blocking';
        if (res.status === 'ok') {
            showToast(res.message);
            refreshStatus();
        } else {
            showToast(res.message || 'Failed to start session.');
        }
    });

    // Stop button → open modal
    els.btnStop.addEventListener('click', () => {
        els.stopModal.classList.remove('hidden');
        els.passphraseInput.value = '';
        els.modalError.classList.add('hidden');
        els.passphraseInput.focus();
    });

    // Cancel stop
    $('#btnCancelStop').addEventListener('click', () => {
        els.stopModal.classList.add('hidden');
    });

    // Confirm stop
    $('#btnConfirmStop').addEventListener('click', async () => {
        const key = els.passphraseInput.value;
        if (!key) {
            els.modalError.textContent = 'Please enter your passphrase.';
            els.modalError.classList.remove('hidden');
            return;
        }
        const res = await api('POST', '/api/stop', { key });
        if (res.status === 'pending' || res.status === 'ok') {
            els.stopModal.classList.add('hidden');
            showToast(res.message);
            refreshStatus();
        } else {
            els.modalError.textContent = res.message || 'Invalid passphrase.';
            els.modalError.classList.remove('hidden');
        }
    });

    // Modal passphrase enter key
    els.passphraseInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') $('#btnConfirmStop').click();
    });

    // Close modal on overlay click
    els.stopModal.addEventListener('click', (e) => {
        if (e.target === els.stopModal) els.stopModal.classList.add('hidden');
    });

    // Add domain: blacklist
    $('#btnAddBlacklist').addEventListener('click', () => addDomain('blacklist'));
    els.blacklistInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') addDomain('blacklist');
    });

    // Add domain: whitelist
    $('#btnAddWhitelist').addEventListener('click', () => addDomain('whitelist'));
    els.whitelistInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') addDomain('whitelist');
    });
}

function extractDomain(input) {
    let d = input.trim().toLowerCase();
    // Strip protocol
    d = d.replace(/^https?:\/\//, '');
    // Strip path, query, hash
    d = d.split('/')[0].split('?')[0].split('#')[0];
    // Strip port
    d = d.split(':')[0];
    // Strip www.
    d = d.replace(/^www\./, '');
    return d;
}

async function addDomain(listName) {
    const input = listName === 'blacklist' ? els.blacklistInput : els.whitelistInput;
    const raw = input.value.trim();
    if (!raw) return;

    const domain = extractDomain(raw);

    // Basic validation
    if (!/^[a-z0-9]([a-z0-9\-]*\.)+[a-z]{2,}$/.test(domain)) {
        showToast('Invalid domain. Example: reddit.com or https://reddit.com/r/test');
        return;
    }

    const res = await api('POST', `/api/lists/${listName}`, { domain });
    if (res.status === 'ok') {
        input.value = '';
        showToast(`Added ${domain} to ${listName}`);
        refreshLists();
    } else {
        showToast('Error: ' + res.message);
    }
}

// ── Init ─────────────────────────────────────────────────────────────────────

async function init() {
    initEvents();
    await refreshStatus();
    await refreshLists();

    // Poll status every 2 seconds
    pollInterval = setInterval(refreshStatus, 2000);
}

document.addEventListener('DOMContentLoaded', init);
