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

// ── Poll daemon status and sync block rules ──────────────────────────────────

async function syncBlockRules() {
    try {
        const statusRes = await fetch(`${API}/api/status`, { signal: AbortSignal.timeout(2000) });
        const status = await statusRes.json();

        if (status.active && status.mode === 'blacklist') {
            if (!lastActive || lastMode !== 'blacklist') {
                // Session just started — fetch domains and add rules
                const listsRes = await fetch(`${API}/api/lists`, { signal: AbortSignal.timeout(2000) });
                const listsData = await listsRes.json();
                const domains = listsData.lists?.blacklist || [];
                await applyBlockRules(domains);
                lastActive = true;
                lastMode = 'blacklist';
            }
        } else if (status.active && status.mode === 'whitelist') {
            // Whitelist mode — block everything EXCEPT whitelisted domains
            if (!lastActive || lastMode !== 'whitelist') {
                const listsRes = await fetch(`${API}/api/lists`, { signal: AbortSignal.timeout(2000) });
                const listsData = await listsRes.json();
                const allowed = listsData.lists?.whitelist || [];
                await applyWhitelistRules(allowed);
                lastActive = true;
                lastMode = 'whitelist';
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
        // Server not running — clear rules to be safe
        if (lastActive) {
            await clearBlockRules();
            lastActive = false;
            lastMode = null;
        }
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
                resourceTypes: ['main_frame']
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
            excludedInitiatorDomains: ['127.0.0.1', 'localhost', ...allowedDomains],
            resourceTypes: ['main_frame']
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
                resourceTypes: ['main_frame']
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
            resourceTypes: ['main_frame']
        }
    });
    rules.push({
        id: id++,
        priority: 2,
        action: { type: 'allow' },
        condition: {
            urlFilter: '||localhost',
            resourceTypes: ['main_frame']
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

// ── Start polling ────────────────────────────────────────────────────────────

setInterval(syncBlockRules, POLL_INTERVAL);
syncBlockRules();
