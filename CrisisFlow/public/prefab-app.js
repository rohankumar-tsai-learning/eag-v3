/**
 * Prefab-based application orchestration layer
 * Manages network integration, state updates, and event handling.
 * Keeps the backend contract completely unchanged.
 */

import { store } from "./prefab-state.js";
import {
  nodes,
  fmtAge,
  renderRisk,
  renderAdvisory,
  renderTrends,
  showSkeletons,
  clearSkeletons,
  setProbing,
  setLastPayload,
  updateAuditLog,
  clearAuditLog,
  refreshRiskClock,
} from "./prefab-renderers.js";

let auditStream = null;
let auditAutoScroll = true;

/**
 * Probe market and update state
 * Calls POST /api/dispatch and GET /api/vault
 */
async function refresh(force = false) {
  setProbing(true);
  showSkeletons();
  store.set({ isProbing: true });

  try {
    const response = await fetch("/api/dispatch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force }),
    });

    if (!response.ok) {
      throw new Error(`Dispatch request failed: ${response.status}`);
    }

    const payload = await response.json();
    const vault = await fetch("/api/vault").then((r) => r.json());
    store.set({ payload, vault });
  } catch (error) {
    console.error("Refresh error:", error);
  } finally {
    setProbing(false);
    store.set({ isProbing: false });
  }
}

/**
 * Connect to UI stream (SSE)
 * Listen for real-time updates from /api/ui/stream
 */
function connectUiStream() {
  const stream = new EventSource("/api/ui/stream");
  stream.onmessage = async (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "connected") {
      store.set({ connected: true });
      return;
    }
    // For any payload, fetch vault data and update state
    const vault = await fetch("/api/vault").then((r) => r.json());
    store.set({ payload: data, vault });
  };

  stream.onerror = () => {
    console.error("UI stream error, reconnecting in 3s");
    stream.close();
    store.set({ connected: false });
    setTimeout(connectUiStream, 3000);
  };
}

/**
 * Connect to audit stream (SSE)
 * Listen for audit log updates from /api/audit/stream
 */
function connectAuditStream() {
  if (auditStream) {
    auditStream.close();
  }

  auditStream = new EventSource("/api/audit/stream");
  auditStream.onmessage = (event) => {
    const data = JSON.parse(event.data);
    const shouldPreserveScroll = !auditAutoScroll;
    updateAuditLog(data.tail || "", shouldPreserveScroll);
    store.set({ auditTail: data.tail || "" });
  };

  auditStream.onerror = () => {
    console.error("Audit stream error, reconnecting in 3s");
    auditStream.close();
    setTimeout(connectAuditStream, 3000);
  };
}

/**
 * State change handler
 * Renders UI when state changes
 */
function onStateChange(state) {
  if (state.payload && state.vault) {
    setLastPayload(state.payload);
    renderRisk(state.payload);
    renderAdvisory(state.payload);
    renderTrends(state.payload, state.vault);
  }
}

/**
 * Initialize event listeners
 */
function initializeEventListeners() {
  // Refresh button
  nodes.refreshBtn.addEventListener("click", () => {
    refresh(true);
  });

  // Force toggle
  nodes.forceToggle.addEventListener("change", (e) => {
    store.set({ force: e.target.checked });
  });

  // Clear log button
  nodes.clearLogBtn.addEventListener("click", async () => {
    nodes.clearLogBtn.disabled = true;
    nodes.clearLogBtn.textContent = "Clearing…";
    try {
      await fetch("/api/audit/log", { method: "DELETE" });
      clearAuditLog();
      store.set({ auditTail: "" });
      // Reconnect SSE so the server resets the read offset
      connectAuditStream();
    } catch (error) {
      console.error("Clear log error:", error);
    } finally {
      nodes.clearLogBtn.disabled = false;
      nodes.clearLogBtn.textContent = "Clear Log";
    }
  });

  // Audit log scroll detection for auto-scroll
  nodes.auditLog.addEventListener("scroll", () => {
    const distanceFromBottom =
      nodes.auditLog.scrollHeight - nodes.auditLog.scrollTop - nodes.auditLog.clientHeight;
    auditAutoScroll = distanceFromBottom < 16;
  });
}

/**
 * Initialize the application
 */
export function initApp() {
  // Subscribe to state changes
  store.subscribe(onStateChange);

  // Initialize event listeners
  initializeEventListeners();

  // Start network streams
  connectUiStream();
  connectAuditStream();

  // Show skeletons and do initial refresh
  showSkeletons();
  refresh(false);

  // Refresh risk clock every 15 seconds
  setInterval(refreshRiskClock, 15000);

  console.log("Prefab-based app initialized");
}

// Auto-initialize on load
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}
