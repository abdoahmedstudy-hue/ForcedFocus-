/**
 * ForcedFocus Chrome Extension — Enhanced Background Service Worker
 * Actively blocks blacklisted domains at the browser level using
 * declarativeNetRequest, preventing bypass via Chrome's Secure DNS.
 * Includes advanced features like analytics, smarter caching, and better error handling.
 */

const API = 'http://127.0.0.1:7070';
const POLL_INTERVAL = 3000;
const RULE_ID_START = 1000;
const MAX_RETRY_ATTEMPTS = 3;
const RETRY_DELAY = 2000;

// State management
let lastActive = false;
let lastMode = null;
let connectionAttempts = 0;
let isRetrying = false;
let blockRulesCache = {
  blacklist: [],
  whitelist: [],
  timestamp: 0
};

// Analytics
let analytics = {
  blockedRequests: 0,
  allowedRequests: 0,
  startTime: Date.now()
};

// ── Utility Functions ─────────────────────────────────────────────────────────

function log(message, level = 'info') {
  const timestamp = new Date().toISOString();
  console.log(`[ForcedFocus][${timestamp}][${level.toUpperCase()}] ${message}`);
}

function isErrorRecoverable(error) {
  // Some errors we can ignore/retry, others are permanent
  if (error instanceof TypeError && error.message.includes('fetch')) {
    return true; // Network issues
  }
  if (error.name === 'AbortError') {
    return true; // Timeout
  }
  return false;
}

async function fetchWithRetry(url, options = {}, maxRetries = MAX_RETRY_ATTEMPTS) {
  for (let i = 0; i <= maxRetries; i++) {
    try {
      const response = await fetch(url, {
        ...options,
        signal: AbortSignal.timeout(5000) // 5 second timeout
      });
      return response;
    } catch (error) {
      if (i === maxRetries || !isErrorRecoverable(error)) {
        throw error;
      }
      
      log(`Fetch attempt ${i + 1} failed: ${error.message}. Retrying in ${RETRY_DELAY}ms...`, 'warn');
      await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
    }
  }
}

// ── Browser Cache Management ──────────────────────────────────────────────────

async function clearBrowserCache() {
  log('Clearing browser cache and service workers...');
  try {
    await chrome.browsingData.remove({
      "since": 0
    }, {
      "cache": true,
      "cacheStorage": true,
      "serviceWorkers": true
    });
    log('Cache and service workers cleared successfully.');
  } catch (err) {
    log(`Failed to clear cache: ${err.message}`, 'error');
  }
}

// ── Analytics ─────────────────────────────────────────────────────────────────

function recordBlockedRequest(domain) {
  analytics.blockedRequests++;
  chrome.storage.local.set({ analytics });
  
  // Send to native app for logging (optional)
  chrome.runtime.sendMessage({
    action: 'blockedRequest',
    domain: domain,
    timestamp: Date.now()
  }).catch(() => {
    // Ignore if native app isn't listening
  });
}

function recordAllowedRequest(domain) {
  analytics.allowedRequests++;
  chrome.storage.local.set({ analytics });
}

// ── Rule Management ───────────────────────────────────────────────────────────

async function getDynamicRules() {
  try {
    return await chrome.declarativeNetRequest.getDynamicRules();
  } catch (err) {
    log(`Failed to get dynamic rules: ${err.message}`, 'error');
    return [];
  }
}

async function updateDynamicRules(addRules = [], removeRuleIds = []) {
  try {
    await chrome.declarativeNetRequest.updateDynamicRules({
      addRules,
      removeRuleIds
    });
    log(`Updated dynamic rules: ${addRules.length} added, ${removeRuleIds.length} removed`);
  } catch (err) {
    log(`Failed to update dynamic rules: ${err.message}`, 'error');
    throw err;
  }
}

// ── Block Rule Generation ─────────────────────────────────────────────────────

function generateBlockRules(domains, baseUrl = '') {
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
          url: baseUrl + chrome.runtime.getURL('blocked.html') + '?domain=' + encodeURIComponent(domain)
        }
      },
      condition: {
        urlFilter: `||${domain}`,
        resourceTypes: [
          'main_frame', 'sub_frame', 'stylesheet', 'script', 'image', 
          'font', 'object', 'xmlhttprequest', 'ping', 'csp_report', 
          'media', 'websocket', 'webbundle', 'other'
        ]
      }
    });
  }
  
  return rules;
}

function generateWhitelistRules(allowedDomains, baseUrl = '') {
  const rules = [];
  let id = RULE_ID_START;
  
  // Block everything by default
  rules.push({
    id: id++,
    priority: 1,
    action: {
      type: 'redirect',
      redirect: {
        url: baseUrl + chrome.runtime.getURL('blocked.html') + '?domain=all'
      }
    },
    condition: {
      urlFilter: '*',
      resourceTypes: [
        'main_frame', 'sub_frame', 'stylesheet', 'script', 'image', 
        'font', 'object', 'xmlhttprequest', 'ping', 'csp_report', 
        'media', 'websocket', 'webbundle', 'other'
      ]
    }
  });
  
  // Allow specific domains (higher priority)
  for (const domain of allowedDomains) {
    rules.push({
      id: id++,
      priority: 2,
      action: { type: 'allow' },
      condition: {
        urlFilter: `||${domain}`,
        resourceTypes: [
          'main_frame', 'sub_frame', 'stylesheet', 'script', 'image', 
          'font', 'object', 'xmlhttprequest', 'ping', 'csp_report', 
          'media', 'websocket', 'webbundle', 'other'
        ]
      }
    });
  }
  
  // Always allow localhost for the dashboard
  ['127.0.0.1', 'localhost'].forEach(host => {
    rules.push({
      id: id++,
      priority: 2,
      action: { type: 'allow' },
      condition: {
        urlFilter: `||${host}`,
        resourceTypes: [
          'main_frame', 'sub_frame', 'stylesheet', 'script', 'image', 
          'font', 'object', 'xmlhttprequest', 'ping', 'csp_report', 
          'media', 'websocket', 'webbundle', 'other'
        ]
      }
    });
  });
  
  return rules;
}

// ── Core Blocking Logic ───────────────────────────────────────────────────────

async function clearBlockRules() {
  try {
    const existing = await getDynamicRules();
    if (existing.length > 0) {
      await updateDynamicRules([], existing.map(r => r.id));
      log(`Cleared ${existing.length} block rules.`);
    }
  } catch (err) {
    log(`Failed to clear rules: ${err.message}`, 'error');
  }
}

async function applyBlockRules(domains) {
  // Remove existing rules first
  await clearBlockRules();
  
  if (domains.length === 0) {
    log('No domains to block.');
    return;
  }
  
  const rules = generateBlockRules(domains);
  await updateDynamicRules(rules);
  
  log(`Applied ${rules.length} block rules.`);
}

async function applyWhitelistRules(allowedDomains) {
  await clearBlockRules();
  
  const rules = generateWhitelistRules(allowedDomains);
  await updateDynamicRules(rules);
  
  log(`Applied whitelist rules: ${allowedDomains.length} allowed, rest blocked.`);
}

// ── Session Management ────────────────────────────────────────────────────────

async function fetchSessionStatus() {
  try {
    const response = await fetchWithRetry(`${API}/api/status`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return await response.json();
  } catch (error) {
    log(`Failed to fetch session status: ${error.message}`, 'error');
    throw error;
  }
}

async function fetchDomainLists() {
  try {
    const response = await fetchWithRetry(`${API}/api/lists`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return await response.json();
  } catch (error) {
    log(`Failed to fetch domain lists: ${error.message}`, 'error');
    throw error;
  }
}

async function syncBlockRules() {
  try {
    const status = await fetchSessionStatus();
    
    // Reset connection attempts on successful fetch
    connectionAttempts = 0;
    // T11: Restore fast polling if it was reduced during outage
    if (isRetrying) {
      isRetrying = false;
      chrome.alarms.clear('syncRules');
      chrome.alarms.create('syncRules', { periodInMinutes: 0.05 }); // ~3 seconds
      log('Server reconnected — restored fast polling.');
    }
    
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
        const listsData = await fetchDomainLists();
        const domains = listsData.lists?.blacklist || [];
        await applyBlockRules(domains);
        await clearBrowserCache();
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
          const listsData = await fetchDomainLists();
          allowed = listsData.lists?.whitelist || [];
        }
        await applyWhitelistRules(allowed);
        await clearBrowserCache();
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
    
  } catch (error) {
    connectionAttempts++;
    
    // Server not running — KEEP existing rules to prevent bypass.
    // Rules are only cleared when the server explicitly reports inactive.
    log(`Server unreachable (${connectionAttempts} attempts) — keeping existing rules.`, 'warn');
    
    // If we've tried too many times, maybe the server is down permanently
    if (connectionAttempts > 10 && !isRetrying) {
      isRetrying = true;
      log('Connection attempts exceeded threshold. Will retry less frequently.', 'warn');
      // Reduce polling frequency to be less aggressive
      chrome.alarms.clear('syncRules');
      chrome.alarms.create('syncRules', { periodInMinutes: 1 }); // Every minute instead of every 3 seconds
    }
  }
}

// ── Extension Lifecycle ───────────────────────────────────────────────────────

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'syncRules') {
    syncBlockRules();
  }
});

// Also run immediately on service worker start
chrome.runtime.onStartup.addListener(() => {
  log('Extension started');
  // T10: Ensure alarm exists on every startup, not just onInstalled
  chrome.alarms.create('syncRules', { periodInMinutes: 0.05 });
  syncBlockRules();
});

chrome.runtime.onInstalled.addListener((details) => {
  log(`Extension installed/updated: ${details.reason}`);
  
  // Initialize analytics
  chrome.storage.local.get(['analytics'], (result) => {
    if (!result.analytics) {
      chrome.storage.local.set({ analytics });
    }
  });
  
  // Start polling
  chrome.alarms.create('syncRules', { periodInMinutes: 0.05 }); // ~3 seconds
  syncBlockRules();
});

// Handle messages from popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'getAnalytics') {
    chrome.storage.local.get(['analytics'], (result) => {
      sendResponse(result.analytics || analytics);
    });
    return true; // Keep message channel open for async response
  }
  
  if (message.action === 'resetAnalytics') {
    analytics = {
      blockedRequests: 0,
      allowedRequests: 0,
      startTime: Date.now()
    };
    chrome.storage.local.set({ analytics });
    sendResponse({ success: true });
    return true;
  }

  // T8: Handle timer requests from content scripts and blocked pages
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
    return true;
  }
});