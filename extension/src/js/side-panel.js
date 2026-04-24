/**
 * Side Panel Main Logic
 * Gandalf the Organizer
 */

let agentRunning = false;
let lastStockSummary = null;
let lastWeatherSummary = null;
let lastNewsSummary = null;
let backendMonitorInterval = null;
let backendUnavailableHandled = false;
let refreshCooldownInterval = null;

const BACKEND_MONITOR_INTERVAL_MS = 10000;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function setAgentsMindVisible(visible) {
  if (agentRunning && !visible) {
    alert('Please wait. Wizard reasoning is still in progress.');
    return;
  }

  const panel = document.getElementById('agentsMindPanel');
  const toggleBtn = document.getElementById('toggleMindBtn');
  const overlay = document.getElementById('mindDrawerOverlay');

  if (!panel || !toggleBtn || !overlay) return;

  panel.classList.toggle('open', visible);
  panel.setAttribute('aria-hidden', visible ? 'false' : 'true');
  overlay.classList.toggle('active', visible);
  toggleBtn.setAttribute('aria-expanded', visible ? 'true' : 'false');
  toggleBtn.textContent = visible ? 'Hide Spellbook' : 'Wizard\'s Spellbook';
}

function toggleAgentsMind() {
  const panel = document.getElementById('agentsMindPanel');
  if (!panel) return;
  setAgentsMindVisible(!panel.classList.contains('open'));
}

async function disableSidePanelForActiveTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs[0]?.id || !chrome.sidePanel || typeof chrome.sidePanel.setOptions !== 'function') {
      return;
    }

    await chrome.sidePanel.setOptions({
      tabId: tabs[0].id,
      path: 'src/side_panel.html',
      enabled: false,
    });
  } catch (error) {
    Logger.warn('Failed to disable side panel after backend disconnect', error);
  }
}

async function handleBackendUnavailable() {
  if (backendUnavailableHandled) {
    return;
  }

  backendUnavailableHandled = true;
  if (backendMonitorInterval) {
    clearInterval(backendMonitorInterval);
    backendMonitorInterval = null;
  }

  Logger.warn('Backend not available - closing side panel automatically');
  alert('The Wizard is not available right now. Premium spellcasting is still under construction.');

  await disableSidePanelForActiveTab();
  window.close();
}

function startBackendMonitor() {
  if (backendMonitorInterval) {
    clearInterval(backendMonitorInterval);
  }

  backendMonitorInterval = setInterval(async () => {
    const health = await apiClient.health();
    if (!health) {
      await handleBackendUnavailable();
    }
  }, BACKEND_MONITOR_INTERVAL_MS);
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', async () => {
  Logger.log('Side panel loaded');

  // Record that the side panel was opened (for popup re-trigger prevention)
  await StorageManager.set(CONFIG.STORAGE_KEYS.SIDE_PANEL_OPENED_AT, Date.now());

  const initialized = await initializeUI();
  if (!initialized) {
    return;
  }

  await loadInitialData();
  setupEventListeners();
  await autoRunIfRequested();

  // Start refresh cooldown display timer on load
  updateRefreshCooldown();
  if (refreshCooldownInterval) {
    clearInterval(refreshCooldownInterval);
  }
  refreshCooldownInterval = setInterval(updateRefreshCooldown, 1000);

  // Close panel automatically if backend stops while panel is open.
  startBackendMonitor();
});

/**
 * Initialize UI
 */
async function initializeUI() {
  Logger.log('Initializing UI...');

  const health = await apiClient.health();
  if (!health) {
    await handleBackendUnavailable();
    return false;
  }

  await UIManager.renderTodos();
  await UIManager.startStockTicker();

  Logger.log('UI initialized');
  return true;
}

/**
 * Load initial data
 */
async function loadInitialData() {
  Logger.log('Loading initial data...');

  lastStockSummary = await StorageManager.get(CONFIG.STORAGE_KEYS.STOCKS_SUMMARY) || null;
  lastWeatherSummary = await StorageManager.get(CONFIG.STORAGE_KEYS.WEATHER_SUMMARY) || null;
  lastNewsSummary = await StorageManager.get(CONFIG.STORAGE_KEYS.NEWS_SUMMARY) || null;

  try {
    await UIManager.renderTodos();
  } catch (error) {
    Logger.warn('Failed to load todos from backend', error);
  }

  await UIManager.renderNews();
  await UIManager.updateWeather();
  await UIManager.startStockTicker();
}

async function autoRunIfRequested() {
  try {
    // Popup sets this flag right before opening panel; allow brief retries for storage timing.
    for (let attempt = 0; attempt < 10; attempt += 1) {
      const shouldAutoRun = await StorageManager.get(CONFIG.STORAGE_KEYS.AUTO_RUN_ON_PANEL_OPEN);
      if (shouldAutoRun) {
        await StorageManager.remove(CONFIG.STORAGE_KEYS.AUTO_RUN_ON_PANEL_OPEN);
        setAgentsMindVisible(true);
        
        // Check if auto-run happened recently (within last 15 minutes)
        const lastAutoRunAt = await StorageManager.get(CONFIG.STORAGE_KEYS.LAST_AUTO_RUN_AT) || 0;
        const now = Date.now();
        if (now - lastAutoRunAt < CONFIG.AUTO_RUN_COOLDOWN_MS) {
          Logger.log('Auto-run on cooldown (15 min limit)');
          return;
        }
        
        await runStockCycle({ showLogs: true });
        // Record the auto-run time
        await StorageManager.set(CONFIG.STORAGE_KEYS.LAST_AUTO_RUN_AT, Date.now());
        return;
      }

      await delay(120);
    }
  } catch (error) {
    Logger.error('Failed auto-run check', error);
  }
}

function extractExternalData(messages) {
  const externalData = {
    news: null,
    stocks: null,
    weather: null,
  };

  messages.forEach((message) => {
    if (message.type !== 'observation') {
      return;
    }

    const toolName = message.metadata?.tool;
    const result = message.metadata?.result;

    if (!toolName || !result || message.metadata?.status !== 'success') {
      return;
    }

    if (toolName === 'search_ai_news') {
      externalData.news = result;
    }

    if (toolName === 'get_ai_stocks') {
      externalData.stocks = result;
    }

    if (toolName === 'get_weather') {
      externalData.weather = result;
    }
  });

  return externalData;
}

function collectExternalDataFromMessage(message, externalData) {
  if (message.type !== 'observation') {
    return;
  }

  const toolName = message.metadata?.tool;
  const result = message.metadata?.result;

  if (!toolName || !result || message.metadata?.status !== 'success') {
    return;
  }

  if (toolName === 'search_ai_news') {
    externalData.news = result;
  }

  if (toolName === 'get_ai_stocks') {
    externalData.stocks = result;
  }

  if (toolName === 'get_weather') {
    externalData.weather = result;
  }
}

async function loadExternalDataWithAgent({ showLogs = false } = {}) {
  Logger.log('Loading external data through agent loop...');

  const userEmail = '';
  const task = 'Gather current information in this order: (1) Call get_weather exactly once, summarize weather. (2) Call get_ai_stocks exactly once, summarize stocks. (3) Call search_ai_news exactly once, no summary for news. Return module_group payloads for frontend rendering.';

  const locationContext = await resolveLocationContextForAgentRun();
  Logger.log('Resolved location context for weather', locationContext);

  const groupedResults = {
    weather: null,
    news: null,
    stocks: null,
  };

  const messages = await apiClient.runAgent(task, {
    email: userEmail,
    city: locationContext.city || '',
    latitude: locationContext.latitude,
    longitude: locationContext.longitude,
    maxIterations: 3,
  }, {
    onMessage: async (message) => {
      if (showLogs && message.type !== 'completed') {
        setAgentsMindVisible(true);
        UIManager.renderReasoningLog(message);
      }

      if (message.type === 'observation' && message.metadata?.module_group) {
        const moduleGroup = message.metadata.module_group;
        const moduleName = moduleGroup.module;
        const payload = moduleGroup.payload || {};

        // News can have null summary, but weather/stocks need both data and summary
        const hasValidPayload = moduleGroup.status === 'success' && payload.data &&
          (moduleName === 'news' || (moduleName !== 'news' && payload.summary));
        
        if (hasValidPayload) {
          groupedResults[moduleName] = payload;
          await UIManager.applyModuleGroup(moduleName, payload.data, payload.summary);

          if (moduleName === 'stocks') {
            lastStockSummary = payload.summary;
          } else if (moduleName === 'weather') {
            lastWeatherSummary = payload.summary;
          } else if (moduleName === 'news') {
            lastNewsSummary = null; // News has no summary
          }
        }
      }
    },
  });

  if (showLogs) {
    Logger.log('Reasoning logs streamed in real-time');
  }

  return { messages, groupedResults };
}

async function resolveLocationContextForAgentRun() {
  // 1) Use persisted location first (from popup user-gesture capture)
  const persisted = await StorageManager.get(CONFIG.STORAGE_KEYS.LAST_LOCATION_CONTEXT) || {};
  if (persisted?.latitude != null && persisted?.longitude != null) {
    return persisted;
  }

  // 2) Try live geolocation / IP fallback in side panel context
  try {
    const fresh = await getBrowserLocationContext();
    if (fresh?.latitude != null && fresh?.longitude != null) {
      await StorageManager.set(CONFIG.STORAGE_KEYS.LAST_LOCATION_CONTEXT, fresh);
      return fresh;
    }
  } catch (error) {
    Logger.warn('Failed to get side-panel location context', error);
  }

  // 3) Wait briefly for popup-captured location to land in storage
  for (let attempt = 0; attempt < 10; attempt += 1) {
    await delay(300);
    const retried = await StorageManager.get(CONFIG.STORAGE_KEYS.LAST_LOCATION_CONTEXT) || {};
    if (retried?.latitude != null && retried?.longitude != null) {
      return retried;
    }
  }

  // 4) Last resort: use cached weather city if available
  const cachedWeather = await StorageManager.getCachedWeather();
  const city = cachedWeather?.data?.location?.city;
  if (city) {
    return { city };
  }

  // 5) Final fallback: infer a city label from browser timezone.
  try {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    const parts = timezone.split('/');
    const last = parts[parts.length - 1] || '';
    const guessedCity = last.replace(/_/g, ' ').trim();
    if (guessedCity) {
      return { city: guessedCity };
    }
  } catch (error) {
    Logger.warn('Timezone fallback city resolution failed', error);
  }

  return {};
}

async function getBrowserLocationContext() {
  const geoFromBrowser = await new Promise((resolve) => {
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
        });
      },
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 },
    );
  });

  if (geoFromBrowser?.latitude != null && geoFromBrowser?.longitude != null) {
    return geoFromBrowser;
  }

  // Fallback: resolve coarse location from IP when browser geolocation is unavailable.
  try {
    const response = await fetch('https://ipwho.is/');
    const payload = await response.json();
    if (payload?.success && payload.latitude != null && payload.longitude != null) {
      return {
        latitude: Number(payload.latitude),
        longitude: Number(payload.longitude),
        city: payload.city || '',
      };
    }
  } catch (error) {
    Logger.warn('IP-based geolocation fallback failed', error);
  }

  return {};
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
  const bind = (id, eventName, handler) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener(eventName, handler);
    }
  };

  // Buttons
  bind('refreshBtn', 'click', refreshAll);
  bind('scheduleEventBtn', 'click', showScheduleEventModal);
  bind('stockDropdownBtn', 'click', showStocksDropdown);
  bind('clearLogsBtn', 'click', clearReasoningLogs);
  bind('toggleMindBtn', 'click', toggleAgentsMind);
  bind('closeMindDrawerBtn', 'click', () => setAgentsMindVisible(false));
  bind('mindDrawerOverlay', 'click', () => setAgentsMindVisible(false));

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      if (agentRunning) {
        event.preventDefault();
        return;
      }
      setAgentsMindVisible(false);
    }
  });

  // Add Todo button may be rendered dynamically; delegate clicks from todo list.
  const todoList = document.getElementById('todoList');
  if (todoList) {
    todoList.addEventListener('click', (event) => {
      const target = event.target;
      if (target && target.id === 'addTodoBtn') {
        showAddTodoModal();
      }
    });
  }

  // Add Todo Form
  bind('saveTodoBtn', 'click', saveTodo);
  bind('todoTitle', 'input', updateCharCount);
  bind('todoDescription', 'input', updateCharCount);

  // Schedule Event Form
  bind('saveEventBtn', 'click', saveEvent);

  // Modal close buttons
  bind('closeStocksModalBtn', 'click', () => {
    if (agentRunning) {
      alert('Please wait for current processing to complete.');
      return;
    }
    const modal = document.getElementById('stocksModal');
    if (modal) modal.classList.remove('active');
  });
  bind('closeWeatherModalBtn', 'click', () => {
    if (agentRunning) {
      alert('Please wait for current processing to complete.');
      return;
    }
    const modal = document.getElementById('weatherModal');
    if (modal) modal.style.display = 'none';
  });
  bind('cancelAddTodoBtn', 'click', () => {
    const modal = document.getElementById('addTodoModal');
    if (modal) modal.classList.remove('active');
  });
  bind('cancelScheduleEventBtn', 'click', () => {
    const modal = document.getElementById('scheduleEventModal');
    if (modal) modal.classList.remove('active');
  });

  // Close modals when clicking outside
  bind('addTodoModal', 'click', closeModal);
  bind('scheduleEventModal', 'click', closeModal);
  bind('stocksModal', 'click', closeModal);
  bind('weatherModal', 'click', (e) => {
    if (e.target.id === 'weatherModal') {
      document.getElementById('weatherModal').style.display = 'none';
    }
  });
  
  Logger.log('Event listeners setup');
}

/**
 * Run stock cycle (internal)
 */
async function runStockCycle({ showLogs = true } = {}) {
  if (agentRunning) return;

  agentRunning = true;
  
  Logger.log('Starting stock cycle...');
  UIManager.clearReasoningLogs();
  await UIManager.resetModuleDisplays();
  
  try {
    const { messages } = await loadExternalDataWithAgent({ showLogs });

    Logger.log('Agent completed successfully', messages.length);

    // Set 30-minute refresh cooldown
    const now = Date.now();
    const thirtyMinutesFromNow = now + (30 * 60 * 1000);
    await StorageManager.set(CONFIG.STORAGE_KEYS.NEXT_ALLOWED_REFRESH_AT, thirtyMinutesFromNow);
    Logger.log('Refresh button disabled for 30 minutes');

    await UIManager.renderTodos();
  } catch (error) {
    Logger.error('Agent error', error);
    UIManager.renderReasoningLog({
      type: 'error',
      content: `Agent error: ${error.message}`,
      timestamp: new Date().toISOString(),
    });
  } finally {
    agentRunning = false;
    // Update refresh button cooldown display
    updateRefreshCooldown();
  }
}

/**
 * Update refresh button cooldown display
 */
async function updateRefreshCooldown() {
  const nextAllowedAt = await StorageManager.get(CONFIG.STORAGE_KEYS.NEXT_ALLOWED_REFRESH_AT) || 0;
  const now = Date.now();
  const btn = document.getElementById('refreshBtn');
  const cooldownText = document.getElementById('refreshCooldownText');

  if (!cooldownText) return;

  if (now < nextAllowedAt) {
    btn.disabled = true;
    const remainingMs = nextAllowedAt - now;
    const minutes = Math.floor(remainingMs / 60000);
    const seconds = Math.floor((remainingMs % 60000) / 1000);
    cooldownText.textContent = `Premium refresh available in ${minutes}m ${seconds}s`;
    cooldownText.classList.add('visible');
  } else {
    btn.disabled = false;
    cooldownText.classList.remove('visible');
    if (refreshCooldownInterval) {
      clearInterval(refreshCooldownInterval);
      refreshCooldownInterval = null;
    }
  }
}

/**
 * Refresh all data
 */
async function refreshAll() {
  Logger.log('Manual refresh requested...');

  const nextAllowedAt = await StorageManager.get(CONFIG.STORAGE_KEYS.NEXT_ALLOWED_REFRESH_AT) || 0;
  const now = Date.now();
  if (now < nextAllowedAt) {
    const remainingMinutes = Math.ceil((nextAllowedAt - now) / 60000);
    alert(
      `Premium refresh magic is not available right now (work in progress). ` +
      `Please wait ${remainingMinutes} minute${remainingMinutes === 1 ? '' : 's'} before trying again.`
    );
    return;
  }
  
  const btn = document.getElementById('refreshBtn');
  UIManager.setButtonLoading(btn, true, 'Refreshing...');

  const cooldownTime = now + CONFIG.REFRESH_COOLDOWN_MS;
  await StorageManager.set(CONFIG.STORAGE_KEYS.NEXT_ALLOWED_REFRESH_AT, cooldownTime);
  
  // Disable button and start countdown
  btn.disabled = true;
  if (refreshCooldownInterval) {
    clearInterval(refreshCooldownInterval);
  }
  refreshCooldownInterval = setInterval(updateRefreshCooldown, 1000);
  updateRefreshCooldown();
  
  try {
    await UIManager.renderTodos();
    await runStockCycle({ showLogs: true });
    
    Logger.log('Stocks refreshed');
  } catch (error) {
    Logger.error('Refresh failed', error);
  } finally {
    UIManager.setButtonLoading(btn, false);
  }
}

/**
 * Show add todo modal
 */
function showAddTodoModal() {
  document.getElementById('addTodoModal').classList.add('active');
  document.getElementById('todoTitle').focus();
}

/**
 * Show schedule event modal
 */
function showScheduleEventModal() {
  document.getElementById('scheduleEventModal').classList.add('active');
  document.getElementById('eventTitle').focus();
}

/**
 * Save new todo
 */
async function saveTodo() {
  const title = document.getElementById('todoTitle').value.trim();
  const description = document.getElementById('todoDescription').value.trim();
  const dueDate = document.getElementById('todoDueDate').value;
  const importance = document.getElementById('todoImportance').value;
  
  // Validation
  if (!title) {
    alert('Please enter a task title');
    return;
  }
  
  if (!dueDate) {
    alert('Please select a due date');
    return;
  }
  
  if (description.split(/\s+/).length > 200) {
    alert('Description exceeds 200 words limit');
    return;
  }
  
  Logger.log('Saving todo...');
  
  try {
    await UIManager.addTodo(title, description, dueDate, importance);
    
    // Reset form
    document.getElementById('todoTitle').value = '';
    document.getElementById('todoDescription').value = '';
    document.getElementById('todoDueDate').value = '';
    document.getElementById('todoImportance').value = 'medium';
    
    // Clear char counts
    document.getElementById('titleCount').textContent = '0/50';
    document.getElementById('descCount').textContent = '0/200';
    
    alert('✅ Task added successfully!');
  } catch (error) {
    Logger.error('Failed to save todo', error);
  }
}

/**
 * Save event
 */
async function saveEvent() {
  const eventTitle = document.getElementById('eventTitle').value.trim();
  const eventTime = document.getElementById('eventTime').value;
  const eventDescription = document.getElementById('eventDescription').value.trim();
  const eventEmail = document.getElementById('eventEmail').value.trim();
  const reminderMinutes = parseInt(document.getElementById('reminderMinutes').value) || 15;
  
  // Validation
  if (!eventTitle) {
    alert('Please enter event title');
    return;
  }
  
  if (!eventTime) {
    alert('Please select event time');
    return;
  }
  
  if (!eventEmail) {
    alert('Please enter email address');
    return;
  }
  
  Logger.log('Saving event...');
  
  try {
    await UIManager.scheduleEvent(
      eventTitle,
      eventTime,
      eventDescription,
      eventEmail,
      reminderMinutes
    );
    
    // Reset form
    document.getElementById('eventTitle').value = '';
    document.getElementById('eventTime').value = '';
    document.getElementById('eventDescription').value = '';
    document.getElementById('eventEmail').value = '';
    document.getElementById('reminderMinutes').value = '15';
    
  } catch (error) {
    Logger.error('Failed to save event', error);
  }
}

/**
 * Expand todos section
 */
async function expandTodos() {
  Logger.log('Expanding todos...');
  // TODO: Implement modal expansion view
  alert('📖 Expansion feature coming soon!\n\nThis will show a full-screen dual-pane view with To-Dos and AI News side-by-side.');
}

/**
 * Show stocks dropdown
 */
async function showStocksDropdown() {
  if (agentRunning) {
    alert('Please wait for current processing to complete.');
    return;
  }
  Logger.log('Showing stocks dropdown...');
  await UIManager.showStocksDropdown(lastStockSummary);
}

/**
 * Clear reasoning logs
 */
function clearReasoningLogs() {
  if (agentRunning) {
    alert('Please wait until reasoning completes.');
    return;
  }
  UIManager.clearReasoningLogs();
  Logger.log('Reasoning logs cleared');
}

/**
 * Update character count for inputs
 */
function updateCharCount(event) {
  const input = event.target;
  let count = input.value.length;
  
  // For textarea, count words
  if (input.id === 'todoDescription') {
    count = input.value.split(/\s+/).filter(word => word.length > 0).length;
    const countEl = document.getElementById('descCount');
    countEl.textContent = `${count}/200`;
    countEl.className = count > 200 ? 'char-count error' : count > 150 ? 'char-count warning' : 'char-count';
  } else if (input.id === 'todoTitle') {
    count = input.value.length;
    const countEl = document.getElementById('titleCount');
    countEl.textContent = `${count}/50`;
    countEl.className = count > 50 ? 'char-count error' : 'char-count';
  }
}

/**
 * Close modal when clicking outside content
 */
function closeModal(event) {
  if (agentRunning) {
    return;
  }
  if (event.target === this && this.id.includes('Modal')) {
    this.classList.remove('active');
  }
}

// Auto-refresh data every hour
setInterval(async () => {
  Logger.log('Auto-refreshing data...');
  try {
    await loadExternalDataWithAgent({ showLogs: false });
  } catch (error) {
    Logger.warn('Auto-refresh failed', error);
  }
}, CONFIG.REFRESH_INTERVALS.STOCKS);

window.addEventListener('beforeunload', (event) => {
  if (agentRunning) {
    event.preventDefault();
    event.returnValue = 'Wizard reasoning is still running. Please wait.';
    return 'Wizard reasoning is still running. Please wait.';
  }

  if (backendMonitorInterval) {
    clearInterval(backendMonitorInterval);
    backendMonitorInterval = null;
  }
});

Logger.log('✅ Side panel script loaded successfully');

