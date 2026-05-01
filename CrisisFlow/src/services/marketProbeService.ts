import { auditLog } from "./auditLogger.js";
import { getLatestEntry, upsertCommodityEntry } from "./vaultService.js";
import { readWatchlistKeys, setWatchlistKeys } from "./watchlistService.js";
import type { MarketProbeItem, MarketProbeResult } from "../types.js";

const COOLDOWN_MS = 60_000;
const FRESH_WINDOW_MS = 4 * 60 * 60 * 1000;

let lastGeminiCallAt = 0;

type CommodityTarget = {
  key: string;
  label: string;
  domain: "energy" | "food";
  unit: string;
  fetcher: () => Promise<{ price: number; source: string }>;
};

const BASELINE_PRICES: Record<string, number> = {
  jkm_lng_asia: 11.8,
  crude_oil_india: 98.0,
  wheat_futures: 612.0,
  rice_futures: 17.6,
  urea_cf: 125.0,
  npk_mosaic: 23.0
};

const TARGET_CATALOG: Record<string, CommodityTarget> = {
  jkm_lng_asia: {
    key: "jkm_lng_asia",
    label: "Asia LNG Spot (JKM)",
    domain: "energy",
    unit: "USD/MMBtu",
    fetcher: fetchJKM
  },
  crude_oil_india: {
    key: "crude_oil_india",
    label: "Crude Oil (India Spot)",
    domain: "energy",
    unit: "USD/barrel",
    fetcher: fetchCrudeOilIndiaViaGemini
  },
  wheat_futures: {
    key: "wheat_futures",
    label: "Wheat Futures",
    domain: "food",
    unit: "USC/bushel",
    fetcher: () => fetchFuturesQuote("ZW=F")
  },
  rice_futures: {
    key: "rice_futures",
    label: "Rice Futures",
    domain: "food",
    unit: "USC/cwt",
    fetcher: () => fetchFuturesQuote("ZR=F")
  },
  urea_cf: {
    key: "urea_cf",
    label: "Urea Fertilizer (CF Industries)",
    domain: "food",
    unit: "USD/share",
    fetcher: fetchUreaViaStock
  },
  npk_mosaic: {
    key: "npk_mosaic",
    label: "NPK Complex Fertilizer (Mosaic Co.)",
    domain: "food",
    unit: "USD/share",
    fetcher: fetchNPKViaStock
  }
};

function getActiveTargets(): CommodityTarget[] {
  const keys = readWatchlistKeys();
  const resolved = keys.map((key) => TARGET_CATALOG[key]).filter((target): target is CommodityTarget => Boolean(target));

  if (resolved.length > 0) {
    return resolved;
  }

  return Object.values(TARGET_CATALOG);
}

export function getSupportedWatchlistTargets(): Array<{ key: string; label: string; domain: "energy" | "food"; unit: string }> {
  return Object.values(TARGET_CATALOG).map((target) => ({
    key: target.key,
    label: target.label,
    domain: target.domain,
    unit: target.unit
  }));
}

export function updateProbeWatchlist(keys: string[]): { activeKeys: string[]; invalidKeys: string[] } {
  return setWatchlistKeys(keys);
}

export function getActiveWatchlistKeys(): string[] {
  return readWatchlistKeys();
}

function nowIso(): string {
  return new Date().toISOString();
}

function toNum(value: string): number {
  const normalized = value.replace(/,/g, ".").replace(/[^0-9.-]/g, "");
  return Number.parseFloat(normalized);
}

function parseFirstNumber(value: string): number {
  const match = value.match(/-?\d+(?:[.,]\d+)?/);
  if (!match?.[0]) {
    return Number.NaN;
  }
  return Number.parseFloat(match[0].replace(/,/g, "."));
}

function remainingCooldownMs(): number {
  const elapsed = Date.now() - lastGeminiCallAt;
  return Math.max(0, COOLDOWN_MS - elapsed);
}

const STALE_SOURCES = new Set(["seeded_zero", "seeded_baseline"]);

function hasFreshLocalData(): boolean {
  const activeTargets = getActiveTargets();
  return activeTargets.every((t) => {
    const latest = getLatestEntry(t.key);
    if (!latest) {
      return false;
    }
    const ts = Date.parse(latest.timestamp);
    if (Number.isNaN(ts)) {
      return false;
    }
    if (Date.now() - ts >= FRESH_WINDOW_MS) {
      return false;
    }
    // Reject fallback/zero entries — force a real probe if that's all we have.
    if (STALE_SOURCES.has(latest.source ?? "")) {
      return false;
    }
    if (!Number.isFinite(latest.price) || latest.price <= 0) {
      return false;
    }
    return true;
  });
}

function readFreshLocalItems(): MarketProbeItem[] {
  const activeTargets = getActiveTargets();
  return activeTargets
    .map((t) => {
      const latest = getLatestEntry(t.key);
      if (!latest) {
        return null;
      }
      return {
        key: t.key,
        label: t.label,
        domain: t.domain,
        price: latest.price,
        unit: latest.unit || t.unit,
        sentiment: latest.sentiment ?? "Local vault snapshot reused to preserve API budget.",
        source: latest.source ?? "local_vault",
        timestamp: latest.timestamp,
        stale: (latest.source ?? "") === "seeded_zero"
      } as MarketProbeItem;
    })
    .filter((x): x is MarketProbeItem => x !== null);
}

async function fetchText(url: string): Promise<string> {
  const response = await fetch(url, {
    headers: {
      "User-Agent": "CrisisFlow/1.0"
    }
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText}`);
  }
  return response.text();
}

async function fetchStooqClose(symbol: string): Promise<number> {
  const csv = await fetchText(`https://stooq.com/q/l/?s=${symbol}&i=d`);
  const lines = csv.trim().split("\n");
  if (lines.length < 1) {
    throw new Error(`Unexpected CSV for ${symbol}`);
  }

  const row = lines[0].split(",");
  const close = toNum(row[6] ?? "");
  if (!Number.isFinite(close)) {
    throw new Error(`No close price in Stooq row for ${symbol}`);
  }

  return close;
}

async function fetchInrRate(): Promise<number> {
  const body = await fetchText("https://open.er-api.com/v6/latest/USD");
  const payload = JSON.parse(body) as {
    result?: string;
    rates?: Record<string, number>;
  };

  const inr = payload.rates?.INR;
  if (!Number.isFinite(inr)) {
    throw new Error("FX rate missing for INR");
  }
  return inr as number;
}

async function fetchFuturesQuote(symbol: string): Promise<{ price: number; source: string }> {
  const stooqSymbol = symbol.toLowerCase().replace(/=f$/, ".f");
  const close = await fetchStooqClose(stooqSymbol);

  return {
    price: close,
    source: `stooq:${stooqSymbol}`
  };
}

async function fetchCrudeOilIndiaViaGemini(): Promise<{ price: number; source: string }> {
  const apiKey = process.env.GEMINI_API_KEY;
  
  // If no Gemini API key, fall back to WTI crude price as proxy
  if (!apiKey) {
    const wtiPrice = await fetchStooqClose("cl.f");
    if (!Number.isFinite(wtiPrice) || wtiPrice <= 0) {
      throw new Error("Failed to fetch WTI crude oil price as fallback");
    }
    return {
      price: wtiPrice,
      source: "stooq:cl.f (WTI fallback - Gemini API key not configured)"
    };
  }

  // Check Gemini cooldown - enforce 60 second gap between API calls
  const waitMs = remainingCooldownMs();
  if (waitMs > 0) {
    auditLog("Gemini crude oil fetch throttled", { remainingSeconds: Math.ceil(waitMs / 1000) });
    // Fall back to WTI while in cooldown
    const wtiPrice = await fetchStooqClose("cl.f");
    return {
      price: wtiPrice,
      source: `stooq:cl.f (WTI fallback - Gemini cooldown ${Math.ceil(waitMs / 1000)}s remaining)`
    };
  }

  const prompt = `You are a live oil market data provider. Return ONLY valid JSON, no markdown.\n\nProvide the current crude oil spot price for India in USD per barrel. Include both WTI and Brent reference prices if available. Use today's date: May 1, 2026.\n\nReturn exactly this JSON format:\n{\n  "crude_price_usd_per_barrel": <number>,\n  "source_market": "WTI|Brent|India_spot",\n  "confidence": "high|medium|low",\n  "note": "<brief note about market conditions>"
}`;

  try {
    const model = "gemini-3.1-flash-lite-preview";
    const apiVersion = "v1beta";
    const url = `https://generativelanguage.googleapis.com/${apiVersion}/models/${model}:generateContent`;
    const requestBody = {
      contents: [{ role: "user", parts: [{ text: prompt }] }],
      generationConfig: { responseMimeType: "application/json" }
    };

    auditLog("Gemini crude oil price request", { model, apiVersion });
    // Mark API call start and enforce 60-second cooldown
    lastGeminiCallAt = Date.now();
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": apiKey
      },
      body: JSON.stringify(requestBody)
    });

    if (!response.ok) {
      auditLog("Gemini crude oil fetch failed", { status: response.status });
      // Fall back to WTI
      const wtiPrice = await fetchStooqClose("cl.f");
      return {
        price: wtiPrice,
        source: "stooq:cl.f (WTI fallback after Gemini error)"
      };
    }

    const body = await response.text();
    const payload = JSON.parse(body) as {
      candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
    };
    const text = payload.candidates?.[0]?.content?.parts?.[0]?.text ?? "";
    const parsed = JSON.parse(text) as {
      crude_price_usd_per_barrel?: number;
      source_market?: string;
      note?: string;
    };

    if (parsed.crude_price_usd_per_barrel && Number.isFinite(parsed.crude_price_usd_per_barrel)) {
      auditLog("Gemini crude oil price response", { price: parsed.crude_price_usd_per_barrel, source: parsed.source_market });
      return {
        price: parsed.crude_price_usd_per_barrel,
        source: `Gemini:${parsed.source_market || "spot"}`
      };
    }
  } catch (err) {
    auditLog("Gemini crude oil fetch exception", { error: String(err) });
  }

  // Final fallback to WTI
  const wtiPrice = await fetchStooqClose("cl.f");
  return {
    price: wtiPrice,
    source: "stooq:cl.f (WTI fallback after Gemini parsing error)"
  };
}

async function fetchUreaViaStock(): Promise<{ price: number; source: string }> {
  const price = await fetchStooqClose("cf.us");
  return { price, source: "stooq:cf.us" };
}

async function fetchNPKViaStock(): Promise<{ price: number; source: string }> {
  const price = await fetchStooqClose("mos.us");
  return { price, source: "stooq:mos.us" };
}

async function fetchJKM(): Promise<{ price: number; source: string }> {
  try {
    const price = await fetchStooqClose("jkm.f");
    if (Number.isFinite(price)) {
      return {
        price,
        source: "stooq:jkm.f"
      };
    }
  } catch {
    // Fall through to proxy fallback.
  }

  try {
    const ng = await fetchStooqClose("ng.f");
    const brent = await fetchStooqClose("cl.f");
    const proxy = ng * 2.2 + brent * 0.055;
    if (Number.isFinite(proxy) && proxy > 0) {
      return {
        price: proxy,
        source: "proxy:stooq:ng.f+cl.f"
      };
    }
  } catch {
    // Fall through to Gemini fallback.
  }

  return fetchViaGemini(
    "Provide latest Asia LNG Spot JKM price as numeric value and a one-sentence sentiment in JSON with keys price and sentiment."
  );
}

async function fetchViaGemini(prompt: string): Promise<{ price: number; source: string }> {
  const apiKey = process.env.GEMINI_API_KEY;
  const model = "gemini-3.1-flash-lite-preview";
  const apiVersion = "v1beta";

  if (!apiKey) {
    throw new Error("Gemini API key not configured");
  }

  const waitMs = remainingCooldownMs();
  if (waitMs > 0) {
    throw new Error(`COOLDOWN:${Math.ceil(waitMs / 1000)}`);
  }

  lastGeminiCallAt = Date.now();
  const url = `https://generativelanguage.googleapis.com/${apiVersion}/models/${model}:generateContent?key=${apiKey}`;
  auditLog("Gemini request", { model, apiVersion, prompt });

  const requestBody: {
    contents: Array<{ role: string; parts: Array<{ text: string }> }>;
    generationConfig?: { responseMimeType: string };
  } = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: { responseMimeType: "application/json" }
  };

  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(requestBody)
  });

  const body = await response.text();
  auditLog("Gemini response", { model, apiVersion, status: response.status, body });

  if (!response.ok) {
    throw new Error(`Gemini ${apiVersion}/${model} HTTP ${response.status}`);
  }

  const payload = JSON.parse(body) as { candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }> };
  const text = payload.candidates?.[0]?.content?.parts?.[0]?.text ?? "{}";

  let parsedPrice = Number.NaN;

  try {
    const parsed = JSON.parse(text) as { price?: number };
    parsedPrice = Number(parsed.price);
  } catch {
    const extracted = parseFirstNumber(text);
    if (Number.isFinite(extracted)) {
      parsedPrice = extracted;
    }
  }

  if (!Number.isFinite(parsedPrice)) {
    throw new Error(`Gemini ${apiVersion}/${model} returned non-numeric price`);
  }

  return {
    price: parsedPrice,
    source: `gemini:${model}`
  };
}

function buildDynamicSentiment(key: string, source: string, currentPrice: number): string {
  const latest = getLatestEntry(key);
  const prev = latest?.price;

  if (!Number.isFinite(prev)) {
    return `source=${source}; price=${currentPrice.toFixed(4)}; trend=initial_observation`;
  }

  const previous = prev as number;
  if (previous === 0) {
    return `source=${source}; price=${currentPrice.toFixed(4)}; prev=${previous.toFixed(4)}; trend=baseline_reset`;
  }

  const deltaPct = ((currentPrice - previous) / previous) * 100;
  let trend = "flat";
  if (deltaPct >= 10) {
    trend = "sharp_rise";
  } else if (deltaPct >= 3) {
    trend = "rise";
  } else if (deltaPct <= -10) {
    trend = "sharp_drop";
  } else if (deltaPct <= -3) {
    trend = "drop";
  }

  return `source=${source}; price=${currentPrice.toFixed(4)}; prev=${previous.toFixed(4)}; delta_pct=${deltaPct.toFixed(2)}; trend=${trend}`;
}

function fallbackFromVault(key: string, label: string, domain: "energy" | "food", unit: string, reason: string): MarketProbeItem {
  const latest = getLatestEntry(key);
  if (latest && Number.isFinite(latest.price) && latest.price > 0) {
    return {
      key,
      label,
      domain,
      price: latest.price,
      unit: latest.unit || unit,
      sentiment: `fallback=local_vault; source=${latest.source ?? "local_vault"}; price=${latest.price.toFixed(4)}; reason=${reason}`,
      source: latest.source ?? "local_vault",
      timestamp: nowIso(),
      stale: true
    };
  }

  const baseline = BASELINE_PRICES[key];
  if (Number.isFinite(baseline) && baseline > 0) {
    return {
      key,
      label,
      domain,
      price: baseline,
      unit,
      sentiment: `fallback=seeded_baseline; price=${baseline.toFixed(4)}; reason=${reason}`,
      source: "seeded_baseline",
      timestamp: nowIso(),
      stale: true
    };
  }

  return {
    key,
    label,
    domain,
    price: 0,
    unit,
    sentiment: `fallback=seeded_zero; price=0; reason=${reason}`,
    source: "seeded_zero",
    timestamp: nowIso(),
    stale: true
  };
}

export async function probeMarket(force = false): Promise<MarketProbeResult> {
  auditLog("Tool call: market_probe_tool", { force });

  const fresh = hasFreshLocalData();
  if (!force && fresh) {
    const items = readFreshLocalItems();
    const latestDataTs = items.reduce((best, it) => (it.timestamp > best ? it.timestamp : best), "");
    const result: MarketProbeResult = {
      items,
      metadata: {
        usedGemini: false,
        throttled: false,
        cooldownRemainingSec: 0,
        usedLocalFreshData: true,
        latestDataTs
      }
    };
    auditLog("market_probe_tool response", result);
    return result;
  }

  const waitSec = Math.ceil(remainingCooldownMs() / 1000);
  const throttled = waitSec > 0;
  const items: MarketProbeItem[] = [];
  let usedGemini = false;

  const activeTargets = getActiveTargets();

  for (const target of activeTargets) {
    try {
      const probe = await target.fetcher();
      if (probe.source.startsWith("gemini:")) {
        usedGemini = true;
      }

      const item: MarketProbeItem = {
        key: target.key,
        label: target.label,
        domain: target.domain,
        price: probe.price,
        unit: target.unit,
        sentiment: buildDynamicSentiment(target.key, probe.source, probe.price),
        source: probe.source,
        timestamp: nowIso(),
        stale: false
      };

      items.push(item);
      upsertCommodityEntry(item);
      auditLog("Source response", { key: target.key, source: probe.source, price: probe.price });
    } catch (error) {
      const text = error instanceof Error ? error.message : String(error);
      const cooldownMatch = text.match(/^COOLDOWN:(\d+)/);
      const reason = cooldownMatch
        ? `System Throttled: Cooling Down ${cooldownMatch[1]}s.`
        : `Source fetch failed for ${target.key}: ${text}`;

      const fallback = fallbackFromVault(target.key, target.label, target.domain, target.unit, reason);
      items.push(fallback);
      upsertCommodityEntry(fallback);
      auditLog("Source fallback", { key: target.key, reason });
    }
  }

  const result: MarketProbeResult = {
    items,
    metadata: {
      usedGemini,
      throttled,
      cooldownRemainingSec: waitSec,
      usedLocalFreshData: false,
      latestDataTs: nowIso()
    }
  };

  auditLog("market_probe_tool response", result);
  return result;
}
