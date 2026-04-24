/**
 * Extension Configuration Template
 * Copy this to src/config.js and customize as needed
 */

const EXTENSION_CONFIG = {
  // Backend API
  BACKEND_URL: 'http://localhost:8000',
  
  // User Preferences
  USER: {
    DEFAULT_CITY: 'New York',
    EMAIL: '', // Leave empty or add your email
    TIMEZONE: Intl.DateTimeFormat().resolvedOptions().timeZone,
  },
  
  // Feature Toggles
  FEATURES: {
    SHOW_WEATHER: true,
    SHOW_STOCKS: true,
    SHOW_NEWS: true,
    SHOW_REASONING_LOGS: true,
    AUTO_REFRESH: true,
    EMAIL_NOTIFICATIONS: true,
  },
  
  // Intervals (in milliseconds)
  INTERVALS: {
    AUTO_REFRESH: 3600000, // 1 hour
    STOCK_DISPLAY: 5000,    // 5 seconds
    HEALTH_CHECK: 30000,    // 30 seconds
  },
  
  // UI Preferences
  UI: {
    THEME: 'amoled', // 'amoled' or 'light'
    COMPACT_MODE: false,
    SHOW_EMPTY_STATE_JOKES: true,
  },
  
  // Storage Limits
  STORAGE: {
    MAX_TODOS: 1000,
    MAX_CACHE_AGE: 3600000, // 1 hour
  },
  
  // Logging
  DEBUG: true,
  LOG_LEVEL: 'info', // 'error', 'warn', 'info', 'debug'
};

// Initialize config from localStorage
function initializeConfig() {
  const stored = localStorage.getItem('gandalf_config');
  if (stored) {
    Object.assign(EXTENSION_CONFIG, JSON.parse(stored));
  }
}

// Save config to localStorage
function saveConfig() {
  localStorage.setItem('gandalf_config', JSON.stringify(EXTENSION_CONFIG));
}

// Initialize on load
initializeConfig();
