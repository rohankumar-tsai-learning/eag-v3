import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import type express from "express";
import { z } from "zod";
import { auditLog } from "./services/auditLogger.js";
import { getActiveWatchlistKeys, getSupportedWatchlistTargets, probeMarket, updateProbeWatchlist } from "./services/marketProbeService.js";
import { dispatchUiUpdate } from "./services/uiDispatchService.js";
import { upsertCommodityEntry } from "./services/vaultService.js";
import { getWatchlistPath } from "./services/watchlistService.js";

type TargetMeta = {
  key: string;
  label: string;
  domain: "energy" | "food";
  unit: string;
};

function wantsForce(prompt: string): boolean {
  return /\b(force|fresh|live|full\s+live|ignore\s+cache|no\s+cache)\b/i.test(prompt);
}

type MovementInsight = {
  key: string;
  label: string;
  deltaPct: number;
  direction: "up" | "down";
};

function extractMovementInsight(payload: { deltas?: Array<{ key: string; label: string; deltaPct: number | null }>; risk?: { energy: string; food: string } }): {
  mostMoved: MovementInsight | null;
  worsening: boolean;
  worseningReason: string;
} {
  const candidates = (payload.deltas ?? []).filter(
    (delta): delta is { key: string; label: string; deltaPct: number } => typeof delta.deltaPct === "number" && Number.isFinite(delta.deltaPct)
  );

  const mostMoved =
    candidates.length > 0
      ? [...candidates]
          .sort((a, b) => Math.abs(b.deltaPct) - Math.abs(a.deltaPct))[0]
      : null;

  const mostMovedInsight: MovementInsight | null = mostMoved
    ? {
        key: mostMoved.key,
        label: mostMoved.label,
        deltaPct: Number(mostMoved.deltaPct.toFixed(2)),
        direction: mostMoved.deltaPct >= 0 ? "up" : "down"
      }
    : null;

  const risk = payload.risk ?? { energy: "STABLE", food: "STABLE" };
  const hasCrisisRisk = risk.energy === "CRISIS" || risk.food === "CRISIS";
  const hasAlertRisk = risk.energy === "ALERT" || risk.food === "ALERT";
  const severePositiveMoves = candidates.filter((delta) => delta.deltaPct >= 10).length;
  const worsening = hasCrisisRisk || severePositiveMoves > 0 || (hasAlertRisk && severePositiveMoves > 0);

  let worseningReason = "No severe upward shocks detected; situation appears stable to improving.";
  if (hasCrisisRisk) {
    worseningReason = `Risk matrix includes CRISIS (energy=${risk.energy}, food=${risk.food}).`;
  } else if (severePositiveMoves > 0) {
    worseningReason = `${severePositiveMoves} commodity move(s) exceed +10%, indicating escalation pressure.`;
  } else if (hasAlertRisk) {
    worseningReason = `Risk matrix is at ALERT (energy=${risk.energy}, food=${risk.food}); monitor closely.`;
  }

  return {
    mostMoved: mostMovedInsight,
    worsening,
    worseningReason
  };
}

function promptNeedsWatchlistUpdate(prompt: string): boolean {
  return /\b(set|change|update|switch|focus|track|watch|monitor)\b/i.test(prompt);
}

function findTargetMatches(prompt: string, supported: TargetMeta[]): string[] {
  const text = prompt.toLowerCase();
  const matches = new Set<string>();

  for (const target of supported) {
    if (text.includes(target.key.toLowerCase())) {
      matches.add(target.key);
    }
  }

  const aliasChecks: Array<{ key: string; terms: string[] }> = [
    { key: "jkm_lng_asia", terms: ["jkm", "lng", "asia lng", "gas"] },
    { key: "crude_oil_india", terms: ["crude", "oil", "brent", "wti"] },
    { key: "wheat_futures", terms: ["wheat"] },
    { key: "rice_futures", terms: ["rice"] },
    { key: "urea_cf", terms: ["urea", "cf industries", "fertilizer", "fertiliser"] },
    { key: "npk_mosaic", terms: ["npk", "mosaic", "fertilizer", "fertiliser"] }
  ];

  for (const alias of aliasChecks) {
    if (alias.terms.some((term) => text.includes(term))) {
      matches.add(alias.key);
    }
  }

  const domainRequestedEnergy = /\benergy\b/i.test(prompt);
  const domainRequestedFood = /\bfood\b/i.test(prompt);
  if (domainRequestedEnergy || domainRequestedFood) {
    for (const target of supported) {
      if (domainRequestedEnergy && target.domain === "energy") {
        matches.add(target.key);
      }
      if (domainRequestedFood && target.domain === "food") {
        matches.add(target.key);
      }
    }
  }

  return [...matches];
}

async function runPromptWorkflow(prompt: string): Promise<unknown> {
  const supported = getSupportedWatchlistTargets();
  const activeBefore = getActiveWatchlistKeys();
  const normalized = prompt.trim();

  if (!normalized) {
    return {
      status: "error",
      message: "Prompt is empty",
      supported,
      activeWatchlist: activeBefore
    };
  }

  const force = wantsForce(normalized);
  const inferredKeys = findTargetMatches(normalized, supported);
  const shouldUpdateWatchlist = promptNeedsWatchlistUpdate(normalized) && inferredKeys.length > 0;

  let watchlistResult: { activeKeys: string[]; invalidKeys: string[] } | null = null;
  if (shouldUpdateWatchlist) {
    watchlistResult = updateProbeWatchlist(inferredKeys);
  }

  const payload = await dispatchUiUpdate(force);
  const movement = extractMovementInsight(payload);
  return {
    status: "ok",
    prompt: normalized,
    interpretation: {
      force,
      inferredKeys,
      watchlistUpdated: Boolean(watchlistResult)
    },
    watchlist: {
      before: activeBefore,
      after: getActiveWatchlistKeys(),
      update: watchlistResult
    },
    summary: {
      generatedAt: payload.generatedAt,
      risk: payload.risk,
      probedKeys: payload.probe.items.map((item) => item.key),
      throttled: payload.probe.metadata.throttled,
      usedLocalFreshData: payload.probe.metadata.usedLocalFreshData,
      advisoryCount: payload.advisory.length,
      mostMovedCommodity: movement.mostMoved,
      situationGettingWorse: movement.worsening,
      situationReason: movement.worseningReason
    },
    payload
  };
}

async function getRuntimeHealth(): Promise<unknown> {
  const webPort = Number.parseInt(process.env.PORT || "8080", 10);
  const mcpPort = Number.parseInt(process.env.MCP_PORT || "8181", 10);
  const webStatusUrl = `http://127.0.0.1:${webPort}/api/status`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1500);

  let webStatus: { ok: boolean; status?: unknown; error?: string } = { ok: false };
  try {
    const response = await fetch(webStatusUrl, { signal: controller.signal });
    if (!response.ok) {
      webStatus = { ok: false, error: `HTTP ${response.status}` };
    } else {
      const status = (await response.json()) as unknown;
      webStatus = { ok: true, status };
    }
  } catch (error) {
    webStatus = { ok: false, error: error instanceof Error ? error.message : String(error) };
  } finally {
    clearTimeout(timeout);
  }

  return {
    status: "ok",
    runtime: {
      mcp: {
        ok: true,
        url: `http://127.0.0.1:${mcpPort}/mcp`
      },
      web: {
        url: `http://127.0.0.1:${webPort}`,
        statusEndpoint: webStatusUrl,
        ...webStatus
      }
    },
    watchlist: {
      path: getWatchlistPath(),
      activeKeys: getActiveWatchlistKeys()
    },
    tools: [
      "health_status_tool",
      "chat_prompt_tool",
      "get_watchlist_tool",
      "set_watchlist_tool",
      "market_probe_tool",
      "vault_manager_tool",
      "ui_dispatch_tool"
    ]
  };
}

// Factory: a fresh McpServer instance is required per HTTP request because
// McpServer.connect() can only be called once per instance.
function createServer(): McpServer {
  const server = new McpServer({
    name: "crisisflow-mcp",
    version: "1.0.0"
  });

  server.registerTool(
    "health_status_tool",
    {
      description: "Return MCP/Web runtime readiness, watchlist state, and available tools for chat orchestration diagnostics.",
      inputSchema: {}
    },
    async () => {
      auditLog("Tool call: health_status_tool", {});
      const response = await getRuntimeHealth();
      auditLog("health_status_tool response", {
        webOk: (response as { runtime?: { web?: { ok?: boolean } } }).runtime?.web?.ok ?? false
      });
      return {
        content: [{ type: "text", text: JSON.stringify(response, null, 2) }]
      };
    }
  );

  server.registerTool(
    "chat_prompt_tool",
    {
      description: "Use natural language to run CrisisFlow workflows. It can infer watchlist updates and always dispatches a UI update.",
      inputSchema: {
        prompt: z.string().min(1)
      }
    },
    async ({ prompt }: { prompt: string }) => {
      auditLog("Tool call: chat_prompt_tool", { prompt });
      const result = await runPromptWorkflow(prompt);
      auditLog("chat_prompt_tool response", {
        status: (result as { status?: string }).status ?? "unknown"
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }]
      };
    }
  );

  server.registerTool(
    "market_probe_tool",
    {
      description: "Fetch live commodity prices and sentiment with cooldown-aware intelligence logic.",
      inputSchema: {
        force: z.boolean().default(false)
      }
    },
    async ({ force }: { force?: boolean }) => {
      auditLog("Tool call: market_probe_tool", { force: Boolean(force) });
      const result = await probeMarket(Boolean(force));
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }]
      };
    }
  );

  server.registerTool(
    "get_watchlist_tool",
    {
      description: "Return current active watchlist keys and supported commodity targets.",
      inputSchema: {}
    },
    async () => {
      auditLog("Tool call: get_watchlist_tool", {});
      const response = {
        status: "ok",
        activeKeys: getActiveWatchlistKeys(),
        supported: getSupportedWatchlistTargets()
      };
      auditLog("get_watchlist_tool response", response);
      return {
        content: [{ type: "text", text: JSON.stringify(response, null, 2) }]
      };
    }
  );

  server.registerTool(
    "set_watchlist_tool",
    {
      description: "Update active commodities for market probing using supported watchlist keys.",
      inputSchema: {
        keys: z.array(z.string()).min(1)
      }
    },
    async ({ keys }: { keys: string[] }) => {
      auditLog("Tool call: set_watchlist_tool", { keys });
      const { activeKeys, invalidKeys } = updateProbeWatchlist(keys);
      const response = {
        status: "ok",
        activeKeys,
        invalidKeys,
        supported: getSupportedWatchlistTargets()
      };
      auditLog("set_watchlist_tool response", response);
      return {
        content: [{ type: "text", text: JSON.stringify(response, null, 2) }]
      };
    }
  );

  server.registerTool(
    "vault_manager_tool",
    {
      description: "Append or create commodity time-series entries in crisis_vault.json.",
      inputSchema: {
        key: z.string(),
        price: z.number(),
        unit: z.string(),
        timestamp: z.string().optional(),
        sentiment: z.string().optional(),
        source: z.string().optional()
      }
    },
    async ({ key, price, unit, timestamp, sentiment, source }: { key: string; price: number; unit: string; timestamp?: string; sentiment?: string; source?: string }) => {
      auditLog("Tool call: vault_manager_tool", { key, price, unit, timestamp, sentiment, source });
      const series = upsertCommodityEntry({
        key,
        price,
        unit,
        timestamp: timestamp ?? new Date().toISOString(),
        sentiment,
        source: source ?? "manual"
      });

      auditLog("vault_manager_tool response", { key, count: series.entries.length });
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({ status: "ok", key, entries: series.entries.length }, null, 2)
          }
        ]
      };
    }
  );

  server.registerTool(
    "ui_dispatch_tool",
    {
      description: "Package live data, deltas, and risk levels into a single UI update payload.",
      inputSchema: {
        force: z.boolean().default(false)
      }
    },
    async ({ force }: { force?: boolean }) => {
      auditLog("Tool call: ui_dispatch_tool", { force: Boolean(force) });
      const payload = await dispatchUiUpdate(Boolean(force));
      return {
        content: [{ type: "text", text: JSON.stringify(payload, null, 2) }]
      };
    }
  );

  return server;
}

export async function startMcpServer(port = 8181): Promise<void> {
  const app = createMcpExpressApp({ host: "127.0.0.1" });
  // Note: createMcpExpressApp already installs body-parser; do NOT add express.json() here.

  // Stateless: fresh server + transport per request — no session ID needed.
  const handleRequest = async (req: express.Request, res: express.Response): Promise<void> => {
    const startedAt = Date.now();
    auditLog("MCP request start", {
      method: req.method,
      path: req.path,
      contentType: req.headers["content-type"]
    });

    const server = createServer();

    res.on("finish", () => {
      auditLog("MCP request finish", {
        method: req.method,
        path: req.path,
        statusCode: res.statusCode,
        durationMs: Date.now() - startedAt
      });
      void server.close();
    });

    try {
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined // stateless mode
      });
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      auditLog("MCP request error", { method: req.method, path: req.path, message });
      console.error("MCP request error", error);

      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: "2.0",
          error: {
            code: -32603,
            message: "Internal MCP server error"
          },
          id: null
        });
      }
    }
  };

  app.post("/mcp", handleRequest);
  app.get("/mcp", handleRequest);
  app.delete("/mcp", handleRequest);

  app.listen(port, "127.0.0.1", () => {
    auditLog("MCP server online", { transport: "streamableHttp", port });
    console.log(`CrisisFlow MCP server listening on http://127.0.0.1:${port}/mcp`);
    console.log(`Open MCP Inspector, set transport to Streamable HTTP, URL: http://127.0.0.1:${port}/mcp`);
  });
}
