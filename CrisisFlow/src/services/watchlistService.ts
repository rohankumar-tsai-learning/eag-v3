import fs from "node:fs";
import path from "node:path";

const watchlistPath = path.resolve(process.cwd(), "data", "watchlist.json");

const DEFAULT_WATCHLIST_KEYS = [
  "jkm_lng_asia",
  "crude_oil_india",
  "wheat_futures",
  "rice_futures",
  "urea_cf",
  "npk_mosaic"
] as const;

export const SUPPORTED_WATCHLIST_KEYS = [...DEFAULT_WATCHLIST_KEYS] as const;

type WatchlistConfig = {
  keys: string[];
  updatedAt: string;
};

export type WatchlistUpdateResult = {
  activeKeys: string[];
  invalidKeys: string[];
};

function unique(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function ensureWatchlistFile(): WatchlistConfig {
  const dir = path.dirname(watchlistPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  if (!fs.existsSync(watchlistPath)) {
    const initial: WatchlistConfig = {
      keys: [...DEFAULT_WATCHLIST_KEYS],
      updatedAt: new Date().toISOString()
    };
    fs.writeFileSync(watchlistPath, JSON.stringify(initial, null, 2), "utf-8");
    return initial;
  }

  const raw = fs.readFileSync(watchlistPath, "utf-8");
  const parsed = JSON.parse(raw) as Partial<WatchlistConfig>;
  const keys = unique(Array.isArray(parsed.keys) ? parsed.keys : [...DEFAULT_WATCHLIST_KEYS]);

  return {
    keys: keys.length > 0 ? keys : [...DEFAULT_WATCHLIST_KEYS],
    updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt : new Date().toISOString()
  };
}

function saveWatchlist(keys: string[]): void {
  const payload: WatchlistConfig = {
    keys,
    updatedAt: new Date().toISOString()
  };
  fs.writeFileSync(watchlistPath, JSON.stringify(payload, null, 2), "utf-8");
}

export function getWatchlistPath(): string {
  ensureWatchlistFile();
  return watchlistPath;
}

export function readWatchlistKeys(): string[] {
  return ensureWatchlistFile().keys;
}

export function setWatchlistKeys(requestedKeys: string[]): WatchlistUpdateResult {
  ensureWatchlistFile();

  const requested = unique(requestedKeys);
  const activeKeys = requested.filter((key) => SUPPORTED_WATCHLIST_KEYS.includes(key as (typeof SUPPORTED_WATCHLIST_KEYS)[number]));
  const invalidKeys = requested.filter((key) => !SUPPORTED_WATCHLIST_KEYS.includes(key as (typeof SUPPORTED_WATCHLIST_KEYS)[number]));

  if (activeKeys.length === 0) {
    throw new Error("No valid watchlist keys provided");
  }

  saveWatchlist(activeKeys);
  return { activeKeys, invalidKeys };
}
