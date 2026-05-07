/**
 * ForcedFocus — Settings Client
 */

const $ = (sel) => document.querySelector(sel);

const els = {
    settingsGrid: $('#settingsGrid'),
    soundLibrary: $('#soundLibrary'),
    btnSaveSettings: $('#btnSaveSettings'),
    toast: $('#toast'),
    fileInput: $('#fileInput'),
    btnTriggerUpload: $('#btnTriggerUpload'),
    uploadStatus: $('#uploadStatus')
};

let settings = {};
let availableSounds = [];
let previewAudio = null;

async function api(method, endpoint, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(endpoint, opts);
    return res.json();
}

function showToast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.remove('hidden');
    setTimeout(() => els.toast.classList.add('hidden'), 3000);
}

function playPreview(filename) {
    if (previewAudio) {
        previewAudio.pause();
        previewAudio = null;
    }
    if (!filename) return;
    previewAudio = new Audio('/sounds/' + encodeURIComponent(filename));
    previewAudio.play().catch(e => console.log('Preview error:', e));
}

async function init() {
    try {
        const [settingsRes, soundsRes] = await Promise.all([
            api('GET', '/api/settings'),
            api('GET', '/api/sounds')
        ]);
        
        if (settingsRes.settings) settings = settingsRes.settings;
        if (soundsRes.sounds) availableSounds = soundsRes.sounds;
        
        renderSettings();
        renderLibrary();
    } catch (e) {
        console.error("Init error:", e);
    }
}

function renderSettings() {
    els.settingsGrid.innerHTML = '';
    const categories = [
        { id: 'start', label: 'Session Start' },
        { id: 'rescue', label: 'Rescue Mode' },
        { id: 'unlock', label: 'Request Unlock' },
        { id: 'break', label: 'Pomodoro Break' },
        { id: 'end', label: 'Session End' },
        { id: 'scheduled', label: 'Scheduled Session' },
        { id: 'blocked', label: 'Blocked Site Attempt' }
    ];

    categories.forEach(cat => {
        const item = document.createElement('div');
        item.className = 'settings-item';
        
        const current = settings[`sound_${cat.id}`] || '';
        
        let optionsHtml = availableSounds.map(s => 
            `<option value="${s}" ${s === current ? 'selected' : ''}>${s}</option>`
        ).join('');

        item.innerHTML = `
            <label>${cat.label}</label>
            <select data-cat="${cat.id}">
                <option value="">None</option>
                ${optionsHtml}
            </select>
        `;
        els.settingsGrid.appendChild(item);
    });
}

function renderLibrary() {
    els.soundLibrary.innerHTML = '';
    if (availableSounds.length === 0) {
        els.soundLibrary.innerHTML = '<div class="loading">No custom sounds found.</div>';
        return;
    }

    availableSounds.forEach(s => {
        const row = document.createElement('div');
        row.className = 'sound-row';
        row.innerHTML = `
            <div class="sound-info" title="${s}">${s}</div>
            <div class="sound-actions">
                <button class="btn-icon" data-action="play" data-file="${s}" title="Play Preview">▶️</button>
                <button class="btn-icon delete" data-action="delete" data-file="${s}" title="Delete Sound">🗑️</button>
            </div>
        `;
        els.soundLibrary.appendChild(row);
    });
}

async function deleteSound(filename) {
    if (!confirm(`Are you sure you want to delete "${filename}"?`)) return;
    
    const res = await api('POST', '/api/delete-sound', { filename });
    if (res.status === 'ok') {
        showToast(res.message);
        // Refresh
        const soundsRes = await api('GET', '/api/sounds');
        if (soundsRes.sounds) {
            availableSounds = soundsRes.sounds;
            renderSettings();
            renderLibrary();
        }
    } else {
        showToast('Delete failed: ' + res.message);
    }
}

async function saveSettings() {
    const selects = els.settingsGrid.querySelectorAll('select');
    const newSettings = { ...settings };
    selects.forEach(sel => {
        const cat = sel.dataset.cat;
        newSettings[`sound_${cat}`] = sel.value;
    });

    els.btnSaveSettings.textContent = '⏳ Saving...';
    const res = await api('POST', '/api/settings', { settings: newSettings });
    els.btnSaveSettings.textContent = 'Save Preferences';

    if (res.status === 'ok') {
        settings = res.settings;
        showToast('Sound settings saved successfully!');
    } else {
        showToast('Error saving settings.');
    }
}

async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.mp3')) {
        els.uploadStatus.textContent = '❌ Error: Only .mp3 files allowed.';
        return;
    }

    els.uploadStatus.textContent = `⏳ Uploading ${file.name}...`;
    
    try {
        const base64 = await toBase64(file);
        const res = await api('POST', '/api/upload-sound', {
            filename: file.name,
            data: base64.split(',')[1] // Strip prefix
        });

        if (res.status === 'ok') {
            els.uploadStatus.textContent = `✅ ${res.message}`;
            showToast('New sound added to library!');
            
            // Play it immediately!
            playPreview(file.name);

            // Refresh list
            const soundsRes = await api('GET', '/api/sounds');
            if (soundsRes.sounds) {
                availableSounds = soundsRes.sounds;
                renderSettings();
                renderLibrary();
            }
        } else {
            els.uploadStatus.textContent = `❌ Error: ${res.message}`;
        }
    } catch (err) {
        console.error(err);
        els.uploadStatus.textContent = '❌ Upload failed.';
    }
}

function toBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onload = () => resolve(reader.result);
        reader.onerror = error => reject(error);
    });
}

els.btnSaveSettings.addEventListener('click', saveSettings);
els.btnTriggerUpload.addEventListener('click', () => els.fileInput.click());
els.fileInput.addEventListener('change', handleFileUpload);

els.settingsGrid.addEventListener('change', (e) => {
    if (e.target.tagName === 'SELECT') {
        playPreview(e.target.value);
    }
});

els.soundLibrary.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-icon');
    if (!btn) return;
    const action = btn.dataset.action;
    const file = btn.dataset.file;
    if (action === 'play') playPreview(file);
    if (action === 'delete') deleteSound(file);
});

document.addEventListener('DOMContentLoaded', init);
