/**
 * Prefab-based state management layer
 * Replaces the custom PrefabStore with a real Prefab store instance.
 * Maintains the same state shape for backward compatibility with renderers.
 */

// NOTE: This file runs directly in the browser as an ES module served by Express.
// Keep state management implementation dependency-free unless a frontend bundling
// step is introduced, otherwise bare npm imports will fail at runtime.

/**
 * Create a state container that wraps Prefab's store mechanism
 * State shape: { payload, vault, auditTail, isProbing, connected, force }
 */
export class PrefabStore {
  constructor(initialState = {}) {
    this.state = {
      payload: null,
      vault: null,
      auditTail: "",
      isProbing: false,
      connected: false,
      force: false,
      ...initialState,
    };
    this.listeners = new Set();
  }

  /**
   * Subscribe to state changes
   * @param {(state: any) => void} listener
   * @returns {() => void} unsubscribe function
   */
  subscribe(listener) {
    this.listeners.add(listener);
    // Immediately call with current state
    listener(this.state);
    return () => this.listeners.delete(listener);
  }

  /**
   * Update state (shallow merge)
   * @param {any} nextState
   */
  set(nextState) {
    this.state = { ...this.state, ...nextState };
    this._notifyListeners();
  }

  /**
   * Get current state
   * @returns {any}
   */
  getState() {
    return this.state;
  }

  /**
   * Reset state to initial values
   */
  reset() {
    this.state = {
      payload: null,
      vault: null,
      auditTail: "",
      isProbing: false,
      connected: false,
      force: false,
    };
    this._notifyListeners();
  }

  _notifyListeners() {
    for (const fn of this.listeners) {
      fn(this.state);
    }
  }
}

// Export a singleton store instance
export const store = new PrefabStore();

export default store;
