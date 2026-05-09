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

    // T14: Attach event listeners after DOM is ready and elements are rendered
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
}

document.addEventListener('DOMContentLoaded', init);
