/**
 * UI Manager
 * Handles all UI rendering and interactions
 */

class UIManager {
  static stockTickerInterval = null;
  static moduleSummaries = {
    weather: null,
    news: null,
    stocks: null,
  };
  static moduleData = {
    weather: null,
    news: null,
    stocks: null,
  };

  /**
   * Render todos
   */
  static async renderTodos() {
    const todoList = document.getElementById('todoList');
    
    try {
      const response = await apiClient.getTodos();
      const todos = response.todos || [];

      if (todos.length === 0) {
        const emptyMessage = await StorageManager.get('empty_state_message');
        todoList.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-message">
              ${emptyMessage || "Your life is suspiciously organized... let's fix that."}
            </div>
            <button class="add-todo-btn" id="addTodoBtn">+ Add Quest</button>
          </div>
        `;
        return;
      }

      todoList.innerHTML = todos.map(todo => `
        <div class="todo-item importance-${todo.importance}" data-todo-id="${todo.id}">
          <div class="todo-header">
            <div class="todo-title">${this.escapeHtml(todo.title)}</div>
            <div class="todo-importance-badge">
              ${todo.importance_display?.name || 'Task'}
            </div>
          </div>
          <div class="todo-description">${this.escapeHtml(todo.description)}</div>
          <div class="todo-footer">
            <span>📅 ${new Date(todo.due_date).toLocaleDateString()}</span>
            <div class="todo-actions">
              <button class="todo-action-btn complete-btn" data-todo-id="${todo.id}" title="Complete">✓</button>
              <button class="todo-action-btn edit-btn" data-todo-id="${todo.id}" title="Edit">✎</button>
              <button class="todo-action-btn delete-btn" data-todo-id="${todo.id}" title="Delete">🗑️</button>
            </div>
          </div>
        </div>
      `).join('');

      // Add event listeners
      document.querySelectorAll('.complete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const todoId = parseInt(btn.dataset.todoId);
          await UIManager.completeTodo(todoId);
        });
      });

      document.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const todoId = parseInt(btn.dataset.todoId);
          await UIManager.deleteTodo(todoId);
        });
      });

    } catch (error) {
      Logger.error('Failed to render todos', error);
      todoList.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-message">⚠️ Error loading tasks</div>
        </div>
      `;
    }
  }

  /**
   * Render news feed
   */
  static async renderNews(newsData = null, moduleSummary = null) {
    const newsFeed = document.getElementById('newsFeed');
    
    try {
      const cached = newsData ? { data: newsData } : await StorageManager.getCachedNews();
      const response = cached?.data || { articles: [] };
      const articles = response.articles || [];
      const summaryText = moduleSummary || await StorageManager.get(CONFIG.STORAGE_KEYS.NEWS_SUMMARY);

      // Show articles directly - no summary needed for news (data-only)
      if (articles.length === 0) {
        newsFeed.innerHTML = `
          <div style="text-align: center; color: #808080; padding: 20px;">
            No AI news available yet.
          </div>
        `;
        return;
      }

      // Build article list (without wizard summary card since news is data-only)
      newsFeed.innerHTML = articles.map(article => `
        <div class="news-item">
          <div class="news-source">${this.escapeHtml(article.source || 'AI News')}</div>
          <div class="news-title">${this.escapeHtml(article.title)}</div>
          <div class="news-summary">${this.escapeHtml(article.summary)}</div>
          <div class="news-footer">
            <span>${article.date ? new Date(article.date).toLocaleDateString() : 'Recently'}</span>
            ${article.url ? `<a href="${article.url}" target="_blank" style="color: #4285F4;">Read more →</a>` : ''}
          </div>
        </div>
      `).join('');

    } catch (error) {
      Logger.error('Failed to render news', error);
      newsFeed.innerHTML = `
        <div style="text-align: center; color: #808080; padding: 20px;">
          ⚠️ Error loading news
        </div>
      `;
    }
  }

  /**
   * Render reasoning logs
   */
  static renderReasoningLog(message) {
    const reasoningLogs = document.getElementById('reasoningLogs');
    
    // Skip tool_call messages from display
    if (message.type === 'tool_call') {
      return;
    }
    
    const timestamp = new Date(message.timestamp).toLocaleTimeString();
    const typeLabel = message.type.toUpperCase();
    
    // Filter out coordinates from weather tool observations
    let content = message.content;
    if (message.type === 'observation' && message.metadata?.tool === 'get_weather') {
      try {
        const result = message.metadata?.result || {};
        if (result.latitude || result.longitude) {
          // Remove coordinate details from the logged content
          content = content.replace(/\(\s*[-\d.]+\s*,\s*[-\d.]+\s*\)/g, '(location data)');
        }
      } catch (e) {
        // If parsing fails, just use original content
      }
    }
    
    const entry = document.createElement('div');
    entry.className = `reasoning-entry ${message.type}`;
    entry.innerHTML = `
      <span class="reasoning-timestamp">${timestamp}</span>
      <span class="reasoning-type">${typeLabel}</span>
      <span class="reasoning-content">${this.escapeHtml(content)}</span>
    `;
    
    reasoningLogs.appendChild(entry);
    reasoningLogs.scrollTop = reasoningLogs.scrollHeight;
  }

  /**
   * Update weather display and make it clickable
   */
  static async updateWeather(weatherData = null, summaryText = null) {
    try {
      const cached = weatherData ? { data: weatherData } : await StorageManager.getCachedWeather();
      const response = cached?.data;
      const weatherSummary = summaryText || await StorageManager.get(CONFIG.STORAGE_KEYS.WEATHER_SUMMARY);

      if (!response) {
        const cityNameEl = document.getElementById('cityName');
        const temperatureEl = document.getElementById('temperature');
        const weatherIconEl = document.getElementById('weatherIcon');
        if (cityNameEl) cityNameEl.textContent = 'Awaiting weather';
        if (temperatureEl) temperatureEl.textContent = '--°C';
        if (weatherIconEl) weatherIconEl.textContent = '🌤️';
        return;
      }

      const weather = response.current || {};
      const location = response.location || {};
      
      const cityNameEl = document.getElementById('cityName');
      const temperatureEl = document.getElementById('temperature');
      const weatherIconEl = document.getElementById('weatherIcon');
      const weatherInfo = document.querySelector('.weather-info');
      
      if (cityNameEl) cityNameEl.textContent = location.city || 'Unknown';
      if (temperatureEl) temperatureEl.textContent = `${weather.temperature || '--'}°C`;
      if (weatherIconEl) weatherIconEl.textContent = weather.icon || '🌤️';
      
      // Store weather data for modal display and make weather clickable
      if (weatherInfo) {
        weatherInfo.style.cursor = 'pointer';
        weatherInfo.onclick = () => UIManager.showWeatherModal(response, weatherSummary);
      }

    } catch (error) {
      Logger.error('Failed to update weather', error);
    }
  }

  /**
   * Show weather details in a modal popup
   */
  static showWeatherModal(weatherData, llmSummary = null) {
    const modal = document.getElementById('weatherModal');
    const weatherDetails = document.getElementById('weatherDetails');
    
    if (!weatherData || !weatherData.current) {
      weatherDetails.innerHTML = '<div style="text-align: center; color: #808080;">No weather data available</div>';
      modal.style.display = 'block';
      return;
    }
    
    const location = weatherData.location || {};
    const current = weatherData.current || {};
    const forecast = weatherData.forecast || [];
    
    // Show LLM summary if available, otherwise show full weather details
    if (llmSummary) {
      weatherDetails.innerHTML = `
        <div style="text-align: center;">
          <h2>${location.city || 'Unknown'}, ${location.country || ''}</h2>
          <div style="font-size: 48px; margin: 20px 0;">${current.icon || '🌤️'}</div>
          <div style="font-size: 32px; margin: 10px 0;">${current.temperature || '--'}°C</div>
          <div style="margin: 20px 0; padding: 15px; background-color: #f3f6fb; border-radius: 8px; line-height: 1.6;">
            <p>${this.escapeHtml(llmSummary)}</p>
          </div>
        </div>
      `;
    } else {
      // Fallback to detailed weather display
      let forecastHtml = '';
      if (forecast.length > 0) {
        forecastHtml = `
          <div style="margin-top: 20px;">
            <h3 style="margin: 10px 0;">Forecast</h3>
            ${forecast.slice(0, 3).map(day => `
              <div style="padding: 8px; margin: 5px 0; border-left: 3px solid #4a9eff;">
                ${day.icon} ${day.date}: ${day.condition}, ${day.temperature_min}°C - ${day.temperature_max}°C
              </div>
            `).join('')}
          </div>
        `;
      }
      
      weatherDetails.innerHTML = `
        <div style="text-align: center;">
          <h2>${location.city || 'Unknown'}, ${location.country || ''}</h2>
          <div style="font-size: 48px; margin: 20px 0;">${current.icon || '🌤️'}</div>
          <div style="font-size: 32px; margin: 10px 0;">${current.temperature || '--'}°C</div>
          <div style="font-size: 18px; margin: 10px 0; color: #aaa;">${current.condition || 'N/A'}</div>
          <div style="margin-top: 20px; font-size: 14px; color: #999;">
            💧 Humidity: ${current.humidity || '--'}%<br>
            💨 Wind: ${current.wind_speed || '--'} km/h
          </div>
          ${forecastHtml}
        </div>
      `;
    }
    
    modal.style.display = 'block';
  }

  /**
   * Stock ticker typewriter effect
   */
  static async startStockTicker(stocksData = null) {
    try {
      const cached = stocksData ? { data: stocksData } : await StorageManager.getCachedStocks();
      const response = cached?.data || { stocks: [] };
      const stocks = response.stocks || [];
      if (stocks.length === 0) {
        const stockTickerEl = document.getElementById('stockTicker');
        if (stockTickerEl) {
          stockTickerEl.textContent = '--';
          stockTickerEl.dataset.currentText = '--';
        }
        return;
      }

      if (this.stockTickerInterval) {
        clearInterval(this.stockTickerInterval);
      }

      let currentIndex = 0;
      const stockTickerEl = document.getElementById('stockTicker');

      const renderStockTicker = (newText) => {
        if (!stockTickerEl) {
          return;
        }

        const previousText = stockTickerEl.dataset.currentText;
        if (!previousText) {
          stockTickerEl.textContent = newText;
          stockTickerEl.dataset.currentText = newText;
          return;
        }

        if (previousText === newText) {
          return;
        }

        const escapedPrevious = this.escapeHtml(previousText);
        const escapedNew = this.escapeHtml(newText);
        stockTickerEl.classList.add('odometer-active');
        stockTickerEl.innerHTML = `
          <span class="odometer-window">
            <span class="odometer-strip" id="odometerStrip">
              <span class="odometer-value">${escapedPrevious}</span>
              <span class="odometer-value">${escapedNew}</span>
            </span>
          </span>
        `;

        const strip = stockTickerEl.querySelector('#odometerStrip');
        if (strip) {
          requestAnimationFrame(() => {
            strip.classList.add('roll');
          });
        }

        setTimeout(() => {
          stockTickerEl.classList.remove('odometer-active');
          stockTickerEl.textContent = newText;
          stockTickerEl.dataset.currentText = newText;
        }, 420);
      };
      
      const updateStock = () => {
        if (stocks[currentIndex]) {
          const stock = stocks[currentIndex];
          const priceText = this.formatStockPrice(stock.current_price, stock.currency);
          const changeText = this.formatStockChange(stock.change_percent);

          renderStockTicker(`${stock.symbol} ${priceText} (${changeText})`);
          currentIndex = (currentIndex + 1) % stocks.length;
        }
      };
      
      updateStock(); // Show first stock immediately
      
      // Change stock every 5 seconds
      this.stockTickerInterval = setInterval(updateStock, CONFIG.STOCK_DISPLAY_INTERVAL);

    } catch (error) {
      Logger.error('Failed to start stock ticker', error);
    }
  }

  /**
   * Show stocks dropdown
   */
  static async showStocksDropdown(summaryText = null) {
    try {
      const cached = await StorageManager.getCachedStocks();
      const response = cached?.data || this.moduleData.stocks || { stocks: [] };
      const stocks = response.stocks || [];

      const summaryEl = document.getElementById('stocksSummary');
      let summary = summaryText;
      if (!summary) {
        summary = await StorageManager.get(CONFIG.STORAGE_KEYS.STOCKS_SUMMARY);
      }

      if (summaryEl) {
        summaryEl.innerHTML = `
          <div style="padding: 12px; background: #f3f6fb; border-radius: 8px; color: #1f1f1f; line-height: 1.5;">
            ${summary ? this.escapeHtml(summary) : 'No wizard market summary yet. Run refresh to forge one.'}
          </div>
        `;
      }
      
      const stocksList = document.getElementById('stocksList');
      stocksList.innerHTML = stocks.map(stock => `
        <div style="padding: 12px; border-bottom: 1px solid #2a2a2a; display: flex; justify-content: space-between; align-items: center;">
          <div>
            <strong>${stock.name}</strong>
            <br>
            <small style="color: #808080;">${stock.exchange}</small>
          </div>
          <div style="text-align: right;">
            <div><strong>${stock.symbol}</strong> ${this.formatStockPrice(stock.current_price, stock.currency)}</div>
            <small style="color: #FBBC04;">${stock.sector}</small>
            <div style="font-size: 11px; color: ${Number(stock.change_percent) >= 0 ? '#34A853' : '#EA4335'};">${this.formatStockChange(stock.change_percent)}</div>
          </div>
        </div>
      `).join('');
      
      document.getElementById('stocksModal').classList.add('active');

    } catch (error) {
      Logger.error('Failed to show stocks', error);
    }
  }

  /**
   * Complete a todo
   */
  static async completeTodo(todoId) {
    try {
      await apiClient.completeTodo(todoId);
      await this.renderTodos();
      Logger.log('Todo completed:', todoId);
    } catch (error) {
      Logger.error('Failed to complete todo', error);
    }
  }

  /**
   * Delete a todo
   */
  static async deleteTodo(todoId) {
    if (confirm('Are you sure you want to delete this task?')) {
      try {
        await apiClient.deleteTodo(todoId);
        await this.renderTodos();
        Logger.log('Todo deleted:', todoId);
      } catch (error) {
        Logger.error('Failed to delete todo', error);
      }
    }
  }

  /**
   * Add a new todo
   */
  static async addTodo(title, description, dueDate, importance) {
    try {
      await apiClient.addTodo(title, description, dueDate, importance);
      await this.renderTodos();
      document.getElementById('addTodoModal').classList.remove('active');
      Logger.log('Todo added:', title);
    } catch (error) {
      Logger.error('Failed to add todo', error);
      alert('Failed to add quest. Please try again.');
    }
  }

  /**
   * Schedule an event
   */
  static async scheduleEvent(eventTitle, eventTime, eventDescription, recipientEmail, reminderMinutes) {
    try {
      const response = await apiClient.scheduleEvent(
        eventTitle,
        eventTime,
        eventDescription,
        recipientEmail,
        reminderMinutes
      );
      
      document.getElementById('scheduleEventModal').classList.remove('active');
      alert(`✅ ${response.message}`);
      Logger.log('Event scheduled:', eventTitle);
    } catch (error) {
      Logger.error('Failed to schedule event', error);
      alert('Failed to schedule chronicle. Please check your email and try again.');
    }
  }

  /**
   * Set loading state on button
   */
  static setButtonLoading(btn, isLoading, loadingText = 'Thinking...') {
    if (!btn) {
      return;
    }

    if (isLoading) {
      btn.disabled = true;
      btn.classList.add('btn-loading');
      if (!btn.dataset.originalText) {
        btn.dataset.originalText = btn.textContent;
      }
      btn.textContent = loadingText;
    } else {
      btn.disabled = false;
      btn.classList.remove('btn-loading');
      if (btn.dataset.originalText) {
        btn.textContent = btn.dataset.originalText;
        delete btn.dataset.originalText;
      }
    }
  }

  static formatStockPrice(value, currency = 'USD') {
    if (typeof value !== 'number' || Number.isNaN(value)) {
      return '--';
    }

    const symbol = currency === 'USD' ? '$' : '';
    return `${symbol}${value.toFixed(2)}`;
  }

  static formatStockChange(changePercent) {
    if (typeof changePercent !== 'number' || Number.isNaN(changePercent)) {
      return 'n/a';
    }

    const sign = changePercent >= 0 ? '+' : '';
    return `${sign}${changePercent.toFixed(2)}%`;
  }

  /**
   * Escape HTML to prevent XSS
   */
  static escapeHtml(text) {
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
  }

  /**
   * Clear all reasoning logs
   */
  static clearReasoningLogs() {
    const reasoningLogs = document.getElementById('reasoningLogs');
    reasoningLogs.innerHTML = '<div style="color: #808080; font-size: 11px;">Agent reasoning will appear here...</div>';
  }

  /**
   * Persist and render external data gathered by the agent loop.
   */
  static async applyExternalData(data) {
    if (data.news) {
      await StorageManager.setCachedNews(data.news);
      await this.renderNews(data.news);
    }

    if (data.stocks) {
      await StorageManager.setCachedStocks(data.stocks);
      await this.startStockTicker(data.stocks);
    }

    if (data.weather) {
      await StorageManager.setCachedWeather(data.weather);
      await this.updateWeather(data.weather);
    }
  }

  static async resetModuleDisplays() {
    this.moduleSummaries = {
      weather: null,
      news: null,
      stocks: null,
    };
    this.moduleData = {
      weather: null,
      news: null,
      stocks: null,
    };

    await Promise.all([
      StorageManager.remove(CONFIG.STORAGE_KEYS.WEATHER_SUMMARY),
      StorageManager.remove(CONFIG.STORAGE_KEYS.NEWS_SUMMARY),
      StorageManager.remove(CONFIG.STORAGE_KEYS.STOCKS_SUMMARY),
      StorageManager.remove(CONFIG.STORAGE_KEYS.WEATHER_DATA),
      StorageManager.remove(CONFIG.STORAGE_KEYS.NEWS_DATA),
      StorageManager.remove(CONFIG.STORAGE_KEYS.STOCKS_DATA),
    ]);

    await this.updateWeather(null, null);
    await this.renderNews({ articles: [] }, null);
    await this.startStockTicker({ stocks: [] });
  }

  static async applyModuleGroup(moduleName, data, summary) {
    if (!moduleName || !data) {
      return;
    }

    // News module can proceed without summary (data-only), but weather/stocks need summary
    if (moduleName === 'weather' || moduleName === 'stocks') {
      if (!summary) return;
    }

    if (moduleName === 'weather') {
      this.moduleSummaries.weather = summary;
      this.moduleData.weather = data;
      await StorageManager.set(CONFIG.STORAGE_KEYS.WEATHER_SUMMARY, summary);
      await StorageManager.setCachedWeather(data);
      await this.updateWeather(data, summary);
      return;
    }

    if (moduleName === 'news') {
      // News: store data only, no summary
      this.moduleSummaries.news = null;
      this.moduleData.news = data;
      await StorageManager.setCachedNews(data);
      await this.renderNews(data);
      return;
    }

    if (moduleName === 'stocks') {
      this.moduleSummaries.stocks = summary;
      this.moduleData.stocks = data;
      await StorageManager.set(CONFIG.STORAGE_KEYS.STOCKS_SUMMARY, summary);
      await StorageManager.setCachedStocks(data);
      await this.startStockTicker(data);
    }
  }
}
