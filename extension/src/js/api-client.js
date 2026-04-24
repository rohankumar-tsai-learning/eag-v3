/**
 * API Client
 * Handles communication with FastAPI backend
 */

class APIClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
    this.timeout = CONFIG.API.TIMEOUT;
  }

  /**
   * Generic fetch with timeout and error handling
   */
  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          ...options.headers,
        },
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      clearTimeout(timeoutId);
      Logger.error(`API request failed: ${endpoint}`, error);
      throw error;
    }
  }

  /**
   * Streaming request using EventSource
   */
  streamRequest(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    Logger.log(`Starting stream: ${url}`);

    return new EventSource(url);
  }

  /**
   * Run agent with streaming
   */
  runAgent(task, context = {}, handlers = {}) {
    const endpoint = CONFIG.API.ENDPOINTS.AGENT_RUN;
    
    Logger.log('Running agent', { task, context });

    return new Promise((resolve, reject) => {
      try {
        const eventSource = new EventSource(
          `${this.baseUrl}${endpoint}?${new URLSearchParams({
            task,
            city: context.city ?? '',
            latitude: context.latitude ?? '',
            longitude: context.longitude ?? '',
            email: context.email ?? '',
            max_iterations: context.maxIterations ?? 10,
          })}`
        );

        const messages = [];

        eventSource.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data);
            if (message.type === 'completed') {
              Logger.log('Agent completed');
              eventSource.close();
              resolve(messages);
              return;
            }

            messages.push(message);
            Logger.log('Agent message received', message);
            if (typeof handlers.onMessage === 'function') {
              handlers.onMessage(message, messages);
            }
          } catch (error) {
            Logger.error('Failed to parse agent message', error);
          }
        };

        eventSource.onerror = (error) => {
          Logger.error('Agent stream error', error);
          eventSource.close();
          reject(error);
        };
      } catch (error) {
        Logger.error('Failed to start agent stream', error);
        reject(error);
      }
    });
  }

  /**
   * Get all todos
   */
  async getTodos() {
    return this.request(CONFIG.API.ENDPOINTS.TODOS);
  }

  /**
   * Add todo
   */
  async addTodo(title, description, dueDate, importance = 'medium') {
    return this.request(CONFIG.API.ENDPOINTS.TODOS, {
      method: 'POST',
      body: JSON.stringify({ title, description, due_date: dueDate, importance }),
    });
  }

  /**
   * Update todo
   */
  async updateTodo(todoId, updates) {
    const endpoint = `${CONFIG.API.ENDPOINTS.TODOS}/${todoId}`;
    return this.request(endpoint, {
      method: 'PUT',
      body: JSON.stringify(updates),
    });
  }

  /**
   * Delete todo
   */
  async deleteTodo(todoId) {
    const endpoint = `${CONFIG.API.ENDPOINTS.TODOS}/${todoId}`;
    return this.request(endpoint, {
      method: 'DELETE',
    });
  }

  /**
   * Complete todo
   */
  async completeTodo(todoId) {
    const endpoint = `${CONFIG.API.ENDPOINTS.TODOS}/${todoId}/complete`;
    return this.request(endpoint, {
      method: 'PUT',
    });
  }

  /**
   * Schedule event
   */
  async scheduleEvent(eventTitle, eventTime, eventDescription, recipientEmail, reminderMinutes = 15) {
    return this.request(CONFIG.API.ENDPOINTS.EVENTS, {
      method: 'POST',
      body: JSON.stringify({
        event_title: eventTitle,
        event_time: eventTime,
        event_description: eventDescription,
        recipient_email: recipientEmail,
        reminder_minutes_before: reminderMinutes,
      }),
    });
  }

  /**
   * Check if backend is running
   */
  async health() {
    try {
      return await this.request('/health');
    } catch (error) {
      return null;
    }
  }
}

// Create global API client instance
const apiClient = new APIClient(CONFIG.API.BASE_URL);
