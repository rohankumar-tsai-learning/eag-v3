/**
 * Background Service Worker
 * Handles background tasks and messaging
 */

// Listen for messages from content scripts or popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log('[Background] Message received:', request);

  if (request.action === 'updateBadge') {
    chrome.action.setBadgeText({ text: request.text });
    chrome.action.setBadgeBackgroundColor({ color: '#4285F4' });
    sendResponse({ status: 'ok' });
    return;
  }

  if (request.action === 'clearBadge') {
    chrome.action.setBadgeText({ text: '' });
    sendResponse({ status: 'ok' });
    return;
  }

  if (request.action === 'openSidePanel') {
    (async () => {
      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab?.id) {
          throw new Error('No active tab found');
        }

        await chrome.sidePanel.open({ tabId: tab.id });
        sendResponse({ status: 'ok' });
      } catch (error) {
        sendResponse({ status: 'error', message: error?.message || String(error) });
      }
    })();

    return true;
  }

  sendResponse({ status: 'ignored' });
});

// Set initial badge
chrome.action.setBadgeText({ text: 'ON' });
chrome.action.setBadgeBackgroundColor({ color: '#4285F4' });

console.log('[Background] Service worker loaded');

// Open side panel when extension icon is clicked
chrome.action.onClicked.addListener(async (tab) => {
  await chrome.sidePanel.open({ tabId: tab.id });
});
