import { auditLog } from "./auditLogger.js";
import { probeMarket } from "./marketProbeService.js";
import { buildAdvisoryActions, calculateDeltas, calculateRiskMatrix } from "./riskService.js";
import { buildGeminiAdvisoryActions } from "./geminiAdvisoryService.js";
import { readVault } from "./vaultService.js";
import type { UiDispatchPayload } from "../types.js";

const listeners = new Set<(payload: UiDispatchPayload) => void>();

export function subscribeUiDispatch(listener: (payload: UiDispatchPayload) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export async function buildUiDispatchPayload(force = false): Promise<UiDispatchPayload> {
  auditLog("Tool call: ui_dispatch_tool", { force });
  const probe = await probeMarket(force);
  const deltas = calculateDeltas(probe);
  const risk = calculateRiskMatrix(deltas);
  const fallbackAdvisory = buildAdvisoryActions(deltas);
  const vault = readVault();
  const advisory = await buildGeminiAdvisoryActions(probe, deltas, risk, vault, fallbackAdvisory);

  // Update latestDataTs to current time when serving payload (even if data is cached)
  // This ensures the UI shows accurate "just now" timing for each refresh
  probe.metadata.latestDataTs = new Date().toISOString();

  const payload: UiDispatchPayload = {
    generatedAt: new Date().toISOString(),
    probe,
    deltas,
    risk,
    advisory
  };

  auditLog("ui_dispatch_tool response", payload);
  return payload;
}

export async function dispatchUiUpdate(force = false): Promise<UiDispatchPayload> {
  const payload = await buildUiDispatchPayload(force);
  for (const listener of listeners) {
    listener(payload);
  }
  auditLog("UI dispatch broadcast", { listeners: listeners.size });
  return payload;
}
