/**
 * ForcedFocus Chrome Extension — Background Service Worker
 * Actively blocks blacklisted domains at the browser level using
 * declarativeNetRequest, preventing bypass via Chrome's Secure DNS.
 */

const API = 'http://127.0.0.1:7070';
const POLL_INTERVAL = 3000;
const RULE_ID_START = 1000;

let lastActive = false;
let lastMode = null;

// ── Browser Cache Management ────────────────────────────────────────────────

async function clearBrowserCache() {
    console.log('[ForcedFocus] Clearing browser cache and service workers...');
    try {
        await chrome.browsingData.remove({
            "since": 0
        }, {
            "cache": true,
            "cacheStorage": true,
            "serviceWorkers": true
        });
        console.log('[ForcedFocus] Cache and service workers cleared.');
    } catch (err) {
        console.error('[ForcedFocus] Failed to clear cache:', err);
    }
}

// ── Poll daemon status and sync block rules ──────────────────────────────────

async function syncBlockRules() {
    try {
        const statusRes = await fetch(`${API}/api/status`, { signal: AbortSignal.timeout(2000) });
        const status = await statusRes.json();

        // During pomodoro break, clear block rules
        if (status.active && status.session_type === 'pomodoro' && status.pomo_phase === 'break') {
            if (lastActive) {
                await clearBlockRules();
                lastActive = false;
                lastMode = null;
            }
            chrome.action.setBadgeText({ text: 'BRK' });
            chrome.action.setBadgeBackgroundColor({ color: '#22c55e' });
            return;
        }

        if (status.active && status.mode === 'blacklist') {
            if (!lastActive || lastMode !== 'blacklist') {
                // Session just started — fetch domains and add rules
                const listsRes = await fetch(`${API}/api/lists`, { signal: AbortSignal.timeout(2000) });
                const listsData = await listsRes.json();
                const domains = listsData.lists?.blacklist || [];
                await applyBlockRules(domains);
                await clearBrowserCache(); // Clear cache to break existing sessions/service workers
                lastActive = true;
                lastMode = 'blacklist';
            }
        } else if (status.active && status.mode === 'whitelist') {
            // Whitelist mode — block everything EXCEPT whitelisted domains (if rescue, allow nothing)
            const isRescue = status.session_type === 'rescue';
            const modeKey = isRescue ? 'rescue' : 'whitelist';
            if (!lastActive || lastMode !== modeKey) {
                let allowed = [];
                if (!isRescue) {
                    const listsRes = await fetch(`${API}/api/lists`, { signal: AbortSignal.timeout(2000) });
                    const listsData = await listsRes.json();
                    allowed = listsData.lists?.whitelist || [];
                }
                await applyWhitelistRules(allowed);
                await clearBrowserCache(); // Force all sites to re-validate against whitelist
                lastActive = true;
                lastMode = modeKey;
            }
        } else {
            // Idle — remove all rules
            if (lastActive) {
                await clearBlockRules();
                lastActive = false;
                lastMode = null;
            }
        }

        // Update badge
        if (status.active) {
            chrome.action.setBadgeText({ text: 'ON' });
            chrome.action.setBadgeBackgroundColor({ color: '#ef4444' });
        } else {
            chrome.action.setBadgeText({ text: '' });
        }
    } catch {
        // Server not running — KEEP existing rules to prevent bypass.
        // Rules are only cleared when the server explicitly reports inactive.
        console.log('[ForcedFocus] Server unreachable — keeping existing rules.');
    }
}

// ── Apply blacklist block rules ──────────────────────────────────────────────

async function applyBlockRules(domains) {
    // Remove existing rules first
    await clearBlockRules();

    if (domains.length === 0) return;

    const rules = [];
    let id = RULE_ID_START;

    for (const domain of domains) {
        // Block the domain and all subdomains
        rules.push({
            id: id++,
            priority: 1,
            action: {
                type: 'redirect',
                redirect: {
                    url: chrome.runtime.getURL('blocked.html') + '?domain=' + encodeURIComponent(domain)
                }
            },
            condition: {
                urlFilter: `||${domain}`,
                resourceTypes: ['main_frame', 'sub_frame', 'stylesheet', 'script', 'image', 'font', 'object', 'xmlhttprequest', 'ping', 'csp_report', 'media', 'websocket', 'webbundle', 'other']
            }
        });
    }

    try {
        await chrome.declarativeNetRequest.updateDynamicRules({
            addRules: rules,
            removeRuleIds: rules.map(r => r.id)
        });
        console.log(`[ForcedFocus] Blacklist: ${rules.length} block rules active.`);
    } catch (err) {
        console.error('[ForcedFocus] Failed to add rules:', err);
    }
}

// ── Apply whitelist rules (block everything except allowed) ──────────────────

async function applyWhitelistRules(allowedDomains) {
    await clearBlockRules();

    // In whitelist mode, block all navigation EXCEPT allowed domains + localhost
    const rules = [{
        id: RULE_ID_START,
        priority: 1,
        action: {
            type: 'redirect',
            redirect: {
                url: chrome.runtime.getURL('blocked.html') + '?domain=all'
            }
        },
        condition: {
            urlFilter: '*',
            resourceTypes: ['main_frame', 'sub_frame', 'stylesheet', 'script', 'image', 'font', 'object', 'xmlhttprequest', 'ping', 'csp_report', 'media', 'websocket', 'webbundle', 'other']
        }
    }];

    // Add allow rules for whitelisted domains (higher priority)
    let id = RULE_ID_START + 1;
    for (const domain of allowedDomains) {
        rules.push({
            id: id++,
            priority: 2,
            action: { type: 'allow' },
            condition: {
                urlFilter: `||${domain}`,
                resourceTypes: ['main_frame', 'sub_frame', 'stylesheet', 'script', 'image', 'font', 'object', 'xmlhttprequest', 'ping', 'csp_report', 'media', 'websocket', 'webbundle', 'other']
            }
        });
    }
    // Always allow localhost for the dashboard
    rules.push({
        id: id++,
        priority: 2,
        action: { type: 'allow' },
        condition: {
            urlFilter: '||127.0.0.1',
            resourceTypes: ['main_frame', 'sub_frame', 'stylesheet', 'script', 'image', 'font', 'object', 'xmlhttprequest', 'ping', 'csp_report', 'media', 'websocket', 'webbundle', 'other']
        }
    });
    rules.push({
        id: id++,
        priority: 2,
        action: { type: 'allow' },
        condition: {
            urlFilter: '||localhost',
            resourceTypes: ['main_frame', 'sub_frame', 'stylesheet', 'script', 'image', 'font', 'object', 'xmlhttprequest', 'ping', 'csp_report', 'media', 'websocket', 'webbundle', 'other']
        }
    });

    try {
        await chrome.declarativeNetRequest.updateDynamicRules({
            addRules: rules,
            removeRuleIds: rules.map(r => r.id)
        });
        console.log(`[ForcedFocus] Whitelist: ${allowedDomains.length} allowed, rest blocked.`);
    } catch (err) {
        console.error('[ForcedFocus] Failed to add whitelist rules:', err);
    }
}

// ── Clear all dynamic rules ──────────────────────────────────────────────────

async function clearBlockRules() {
    try {
        const existing = await chrome.declarativeNetRequest.getDynamicRules();
        if (existing.length > 0) {
            await chrome.declarativeNetRequest.updateDynamicRules({
                removeRuleIds: existing.map(r => r.id)
            });
            console.log(`[ForcedFocus] Cleared ${existing.length} block rules.`);
        }
    } catch (err) {
        console.error('[ForcedFocus] Failed to clear rules:', err);
    }
}

// ── Start polling via chrome.alarms (persists across service worker suspensions) ──

chrome.alarms.create('syncRules', { periodInMinutes: 0.05 }); // ~3 seconds
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === 'syncRules') {
        syncBlockRules();
    }
});
// Also run immediately on service worker start
syncBlockRules();

// T8: Handle messages from popup/content scripts
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === 'getTimeRemaining') {
        fetch(`${API}/api/status`, { signal: AbortSignal.timeout(2000) })
            .then(res => res.json())
            .then(data => {
                if (data.active) {
                    sendResponse({
                        remaining: data.remaining_seconds || 0,
                        phase: data.pomo_phase || null,
                        phaseRemaining: data.pomo_phase_remaining || null
                    });
                } else {
                    sendResponse({ remaining: 0 });
                }
            })
            .catch(() => sendResponse({ remaining: 0 }));
        return true; // Keep message channel open for async response
    }
});
