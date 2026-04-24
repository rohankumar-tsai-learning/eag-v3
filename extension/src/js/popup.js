/**
 * Popup logic
 * Moved from inline script to comply with extension CSP.
 */

async function checkBackendStatus() {
  const statusBox = document.getElementById('statusBox');
  const runBtn = document.getElementById('runOrganiserBtn');
  const disclaimer = document.getElementById('wizardDisclaimer');
  const postRunActions = document.getElementById('postRunActions');
  
  // Initially show offline state
  statusBox.className = 'status inactive';
  statusBox.innerHTML = 'Checking wizard status...';
  runBtn.disabled = true;
  runBtn.textContent = 'Checking...';
  
  // Check if panel was recently opened
  const panelRecentlyOpened = await checkIfSidePanelRecentlyOpened();
  if (panelRecentlyOpened) {
    statusBox.innerHTML = 'Assistant already in use';
    runBtn.textContent = 'Panel Already Open';
    disclaimer.classList.add('visible');
    postRunActions.classList.add('hidden');
    await setSidePanelEnabledForActiveTab(true);
    return;
  }
  
  // Check if auto-run happened recently (15 min cooldown)
  const lastAutoRunAt = await StorageManager.get(CONFIG.STORAGE_KEYS.LAST_AUTO_RUN_AT) || 0;
  const now = Date.now();
  const timeSinceLastRun = now - lastAutoRunAt;
  if (timeSinceLastRun < CONFIG.AUTO_RUN_COOLDOWN_MS) {
    const remainingMs = CONFIG.AUTO_RUN_COOLDOWN_MS - timeSinceLastRun;
    const remainingMinutes = Math.ceil(remainingMs / 60000);
    statusBox.className = 'status inactive';
    statusBox.innerHTML = `Next run available in ${remainingMinutes}m`;
    runBtn.textContent = `Wait ${remainingMinutes}m`;
    runBtn.disabled = true;
    disclaimer.classList.add('visible');
    postRunActions.classList.add('hidden');
    await setSidePanelEnabledForActiveTab(true);
    return;
  }
  
  // Check backend health
  const health = await apiClient.health();

  if (health) {
    statusBox.className = 'status active';
    statusBox.innerHTML = 'Connected - Backend is running';
    disclaimer.classList.remove('visible');
    postRunActions.classList.add('hidden');
    runBtn.disabled = false;
    runBtn.textContent = 'Run the Organiser';
    await setSidePanelEnabledForActiveTab(true);
  } else {
    statusBox.className = 'status inactive';
    statusBox.innerHTML = 'Backend disconnected';
    runBtn.disabled = true;
    runBtn.textContent = 'Wizard Offline';
    disclaimer.classList.add('visible');
    postRunActions.classList.add('hidden');
    await setSidePanelEnabledForActiveTab(false);
  }
}

async function setSidePanelEnabledForActiveTab(enabled) {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs[0]?.id || !chrome.sidePanel || typeof chrome.sidePanel.setOptions !== 'function') {
      return;
    }

    await chrome.sidePanel.setOptions({
      tabId: tabs[0].id,
      path: 'src/side_panel.html',
      enabled,
    });
  } catch (error) {
    Logger.warn('Could not update side panel enabled state', error);
  }
}

async function checkIfSidePanelRecentlyOpened() {
  try {
    // Check if the side panel was opened recently (within last 5 seconds)
    const panelOpenedAt = await StorageManager.get(CONFIG.STORAGE_KEYS.SIDE_PANEL_OPENED_AT);
    if (!panelOpenedAt) {
      return false;
    }

    const timeSinceOpened = Date.now() - panelOpenedAt;
    const GRACE_PERIOD_MS = 5000; // 5 seconds

    return timeSinceOpened < GRACE_PERIOD_MS;
  } catch (error) {
    Logger.warn('Could not check side panel status', error);
    return false;
  }
}

async function openSidePanelForActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs[0]?.id) {
    throw new Error('No active tab available for side panel');
  }

  if (!chrome.sidePanel || typeof chrome.sidePanel.open !== 'function') {
    throw new Error('sidePanel API unavailable in popup context');
  }

  await chrome.sidePanel.open({ tabId: tabs[0].id });
}

async function captureLocationContextFromUserGesture() {
  const fromBrowser = await new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        resolve({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          city: '',
          source: 'browser-geolocation',
          captured_at: Date.now(),
        });
      },
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 300000 },
    );
  });

  if (fromBrowser?.latitude != null && fromBrowser?.longitude != null) {
    return fromBrowser;
  }

  try {
    const response = await fetch('https://ipwho.is/');
    const payload = await response.json();
    if (payload?.success && payload.latitude != null && payload.longitude != null) {
      return {
        latitude: Number(payload.latitude),
        longitude: Number(payload.longitude),
        city: payload.city || '',
        source: 'ipwho-fallback',
        captured_at: Date.now(),
      };
    }
  } catch (error) {
    Logger.warn('Popup location fallback failed', error);
  }

  return null;
}

function setupPopupListeners() {
  document.getElementById('runOrganiserBtn').addEventListener('click', async (event) => {
    const runBtn = event.currentTarget;
    const postRunActions = document.getElementById('postRunActions');

    // Check if side panel was recently opened (prevent accidental re-trigger)
    const panelRecentlyOpened = await checkIfSidePanelRecentlyOpened();
    if (panelRecentlyOpened) {
      alert('The Assistant panel is already open. Please focus on the side panel or close it first.');
      return;
    }

    runBtn.disabled = true;
    runBtn.textContent = 'Starting...';

    try {
      // Start location capture in background so we don't block side panel open.
      captureLocationContextFromUserGesture()
        .then((locationContext) => {
          if (locationContext) {
            return StorageManager.set(CONFIG.STORAGE_KEYS.LAST_LOCATION_CONTEXT, locationContext);
          }
          return null;
        })
        .catch((error) => Logger.warn('Failed to capture location context from popup', error));

      // Do not await storage before opening the panel; user gesture must be preserved.
      StorageManager.set(CONFIG.STORAGE_KEYS.AUTO_RUN_ON_PANEL_OPEN, true)
        .catch((error) => Logger.warn('Failed to set auto-run flag', error));
      await openSidePanelForActiveTab();
      postRunActions.classList.remove('hidden');
      window.close();
    } catch (error) {
      runBtn.disabled = false;
      runBtn.textContent = 'Run the Organiser';
      alert(`Could not start organiser: ${error.message}`);
    }
  });

  document.getElementById('openSidePanelBtn').addEventListener('click', async () => {
    await openSidePanelForActiveTab();
    window.close();
  });

  document.getElementById('settingsBtn').addEventListener('click', () => {
    alert('Settings page coming soon!');
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  setupPopupListeners();
  await checkBackendStatus();
});
