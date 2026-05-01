import fs from "node:fs";
import path from "node:path";
import type { CommoditySeries, CrisisVault, MarketProbeItem, TimeSeriesEntry } from "../types.js";
import { auditLog } from "./auditLogger.js";

const vaultPath = path.resolve(process.cwd(), "data", "crisis_vault.json");

const labels: Record<string, { label: string; domain: "energy" | "food" }> = {
  jkm_lng_asia: { label: "Asia LNG Spot (JKM)", domain: "energy" },
  crude_oil_india: { label: "Crude Oil (India Spot)", domain: "energy" },
  wheat_futures: { label: "Wheat Futures", domain: "food" },
  rice_futures: { label: "Rice Futures", domain: "food" }
};

function ensureVault(): CrisisVault {
  const dir = path.dirname(vaultPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  if (!fs.existsSync(vaultPath)) {
    const initial: CrisisVault = { commodities: {}, updatedAt: new Date().toISOString() };
    fs.writeFileSync(vaultPath, JSON.stringify(initial, null, 2), "utf-8");
    return initial;
  }

  const raw = fs.readFileSync(vaultPath, "utf-8");
  const parsed = JSON.parse(raw) as CrisisVault;
  if (!parsed.commodities) {
    parsed.commodities = {};
  }
  return parsed;
}

function saveVault(vault: CrisisVault): void {
  vault.updatedAt = new Date().toISOString();
  fs.writeFileSync(vaultPath, JSON.stringify(vault, null, 2), "utf-8");
}

export function readVault(): CrisisVault {
  return ensureVault();
}

export function getCommoditySeries(key: string): CommoditySeries | undefined {
  return ensureVault().commodities[key];
}

export function upsertCommodityEntry(item: MarketProbeItem | { key: string; price: number; unit: string; timestamp: string; sentiment?: string; source?: string }): CommoditySeries {
  const vault = ensureVault();
  const meta = labels[item.key] ?? { label: item.key, domain: "energy" as const };

  if (!vault.commodities[item.key]) {
    vault.commodities[item.key] = {
      key: item.key,
      label: meta.label,
      domain: meta.domain,
      entries: []
    };
  }

  const entry: TimeSeriesEntry = {
    timestamp: item.timestamp,
    price: item.price,
    unit: item.unit,
    sentiment: item.sentiment,
    source: item.source
  };

  vault.commodities[item.key].entries.push(entry);
  saveVault(vault);
  auditLog("Vault append", { key: item.key, entry });

  return vault.commodities[item.key];
}

export function getLatestEntry(key: string): TimeSeriesEntry | null {
  const series = getCommoditySeries(key);
  if (!series || series.entries.length === 0) {
    return null;
  }
  return series.entries[series.entries.length - 1] ?? null;
}

export function getVaultPath(): string {
  ensureVault();
  return vaultPath;
}
