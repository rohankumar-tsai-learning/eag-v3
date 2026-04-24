/**
 * Storage Manager
 * Handles Chrome storage for todos and cached data
 */

class StorageManager {
  /**
   * Get data from Chrome storage
   */
  static async get(key) {
    return new Promise((resolve, reject) => {
      try {
        chrome.storage.local.get([key], (result) => {
          if (chrome.runtime.lastError) {
            reject(chrome.runtime.lastError);
          } else {
            resolve(result[key]);
          }
        });
      } catch (error) {
        Logger.error('Storage get error', error);
        reject(error);
      }
    });
  }

  /**
   * Set data in Chrome storage
   */
  static async set(key, value) {
    return new Promise((resolve, reject) => {
      try {
        chrome.storage.local.set({ [key]: value }, () => {
          if (chrome.runtime.lastError) {
            reject(chrome.runtime.lastError);
          } else {
            Logger.log(`Storage set: ${key}`);
            resolve();
          }
        });
      } catch (error) {
        Logger.error('Storage set error', error);
        reject(error);
      }
    });
  }

  /**
   * Remove data from Chrome storage
   */
  static async remove(key) {
    return new Promise((resolve, reject) => {
      try {
        chrome.storage.local.remove([key], () => {
          if (chrome.runtime.lastError) {
            reject(chrome.runtime.lastError);
          } else {
            Logger.log(`Storage removed: ${key}`);
            resolve();
          }
        });
      } catch (error) {
        Logger.error('Storage remove error', error);
        reject(error);
      }
    });
  }

  /**
   * Clear all storage
   */
  static async clear() {
    return new Promise((resolve, reject) => {
      try {
        chrome.storage.local.clear(() => {
          if (chrome.runtime.lastError) {
            reject(chrome.runtime.lastError);
          } else {
            Logger.log('Storage cleared');
            resolve();
          }
        });
      } catch (error) {
        Logger.error('Storage clear error', error);
        reject(error);
      }
    });
  }

  // ============================================================================
  // Todo Methods
  // ============================================================================

  static async getTodos() {
    const todos = await this.get(CONFIG.STORAGE_KEYS.TODOS);
    return todos || [];
  }

  static async saveTodos(todos) {
    await this.set(CONFIG.STORAGE_KEYS.TODOS, todos);
  }

  static async addTodo(todo) {
    const todos = await this.getTodos();
    todo.id = todos.length > 0 ? Math.max(...todos.map(t => t.id)) + 1 : 1;
    todos.push(todo);
    await this.saveTodos(todos);
    return todo;
  }

  static async updateTodo(todoId, updates) {
    const todos = await this.getTodos();
    const todo = todos.find(t => t.id === todoId);
    if (todo) {
      Object.assign(todo, updates);
      await this.saveTodos(todos);
    }
    return todo;
  }

  static async deleteTodo(todoId) {
    const todos = await this.getTodos();
    const filtered = todos.filter(t => t.id !== todoId);
    await this.saveTodos(filtered);
  }

  // ============================================================================
  // Cache Methods
  // ============================================================================

  static async getCachedData(key) {
    const timestamp = await this.get(`${key}_timestamp`);
    const data = await this.get(key);
    return { data, timestamp };
  }

  static async setCachedData(key, data, intervalMs) {
    const now = Date.now();
    await this.set(key, data);
    await this.set(`${key}_timestamp`, now);
    return now;
  }

  static async isCacheValid(key, intervalMs) {
    const timestamp = await this.get(`${key}_timestamp`);
    if (!timestamp) return false;
    return (Date.now() - timestamp) < intervalMs;
  }

  // ============================================================================
  // News Cache
  // ============================================================================

  static async getCachedNews() {
    return this.getCachedData(CONFIG.STORAGE_KEYS.NEWS_DATA);
  }

  static async setCachedNews(news) {
    return this.setCachedData(
      CONFIG.STORAGE_KEYS.NEWS_DATA,
      news,
      CONFIG.REFRESH_INTERVALS.NEWS
    );
  }

  static async isNewsCacheValid() {
    return this.isCacheValid(
      CONFIG.STORAGE_KEYS.LAST_NEWS_FETCH,
      CONFIG.REFRESH_INTERVALS.NEWS
    );
  }

  // ============================================================================
  // Weather Cache
  // ============================================================================

  static async getCachedWeather() {
    return this.getCachedData(CONFIG.STORAGE_KEYS.WEATHER_DATA);
  }

  static async setCachedWeather(weather) {
    return this.setCachedData(
      CONFIG.STORAGE_KEYS.WEATHER_DATA,
      weather,
      CONFIG.REFRESH_INTERVALS.WEATHER
    );
  }

  static async isWeatherCacheValid() {
    return this.isCacheValid(
      CONFIG.STORAGE_KEYS.LAST_WEATHER_FETCH,
      CONFIG.REFRESH_INTERVALS.WEATHER
    );
  }

  // ============================================================================
  // Stocks Cache
  // ============================================================================

  static async getCachedStocks() {
    return this.getCachedData(CONFIG.STORAGE_KEYS.STOCKS_DATA);
  }

  static async setCachedStocks(stocks) {
    return this.setCachedData(
      CONFIG.STORAGE_KEYS.STOCKS_DATA,
      stocks,
      CONFIG.REFRESH_INTERVALS.STOCKS
    );
  }

  static async isStocksCacheValid() {
    return this.isCacheValid(
      CONFIG.STORAGE_KEYS.LAST_STOCKS_FETCH,
      CONFIG.REFRESH_INTERVALS.STOCKS
    );
  }
}
