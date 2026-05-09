/**
 * ForcedFocus Content Script
 * Injects into web pages to provide additional functionality and 
 * integration with the ForcedFocus ecosystem.
 */

// Only run on pages that are being blocked by ForcedFocus
const urlParams = new URLSearchParams(window.location.search);
const blockedDomain = urlParams.get('domain');

if (blockedDomain) {
  // Add styling for blocked pages
  const style = document.createElement('style');
  style.textContent = `
    body.forcedfocus-blocked {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      margin: 0;
      padding: 20px;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
    }
    
    .forcedfocus-container {
      max-width: 600px;
      padding: 2rem;
      background: rgba(30, 41, 59, 0.8);
      border-radius: 12px;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
    }
    
    .forcedfocus-icon {
      font-size: 4rem;
      margin-bottom: 1rem;
    }
    
    .forcedfocus-title {
      font-size: 2rem;
      font-weight: 700;
      margin: 0 0 1rem 0;
      color: #f87171;
    }
    
    .forcedfocus-message {
      font-size: 1.1rem;
      line-height: 1.6;
      margin-bottom: 1.5rem;
    }
    
    .forcedfocus-domain {
      background: rgba(239, 68, 68, 0.1);
      color: #f87171;
      padding: 0.25rem 0.5rem;
      border-radius: 4px;
      font-family: monospace;
      font-size: 1rem;
    }
    
    .forcedfocus-timer {
      font-size: 1.5rem;
      font-weight: 600;
      color: #60a5fa;
      margin: 1rem 0;
    }
    
    .forcedfocus-footer {
      font-size: 0.9rem;
      color: #94a3b8;
      margin-top: 2rem;
    }
    
    .forcedfocus-button {
      background: #3b82f6;
      color: white;
      border: none;
      padding: 0.75rem 1.5rem;
      border-radius: 6px;
      font-size: 1rem;
      cursor: pointer;
      transition: background 0.2s;
      text-decoration: none;
      display: inline-block;
    }
    
    .forcedfocus-button:hover {
      background: #2563eb;
    }
  `;
  document.head.appendChild(style);
  
  // Update the blocked page content
  document.body.className = 'forcedfocus-blocked';
  document.body.innerHTML = `
    <div class="forcedfocus-container">
      <div class="forcedfocus-icon">🚫</div>
      <h1 class="forcedfocus-title">Website Blocked</h1>
      <p class="forcedfocus-message">
        Access to <span class="forcedfocus-domain">${blockedDomain}</span> has been blocked by ForcedFocus.
      </p>
      <div class="forcedfocus-timer" id="timer">Session ends in: calculating...</div>
      <p class="forcedfocus-footer">
        Use your focused time productively. Consider working on important tasks.
      </p>
      <a href="#" class="forcedfocus-button" id="closeTab">Close This Tab</a>
    </div>
  `;
  
  // Add close tab functionality
  document.getElementById('closeTab').addEventListener('click', (e) => {
    e.preventDefault();
    window.close();
  });
  
  // Fetch remaining time from the extension
  chrome.runtime.sendMessage({action: 'getTimeRemaining'}, (response) => {
    if (response && response.remaining) {
      const timer = document.getElementById('timer');
      if (timer) {
        const minutes = Math.floor(response.remaining / 60);
        const seconds = response.remaining % 60;
        timer.textContent = `Session ends in: ${minutes}:${seconds.toString().padStart(2, '0')}`;
      }
    }
  });
  
  // Periodically update the timer
  setInterval(() => {
    chrome.runtime.sendMessage({action: 'getTimeRemaining'}, (response) => {
      if (response && response.remaining) {
        const timer = document.getElementById('timer');
        if (timer) {
          const minutes = Math.floor(response.remaining / 60);
          const seconds = response.remaining % 60;
          timer.textContent = `Session ends in: ${minutes}:${seconds.toString().padStart(2, '0')}`;
        }
      }
    });
  }, 1000);
}