import express, { type Request, type Response } from "express";
import fs from "node:fs";
import path from "node:path";
import { auditLog, getAuditLogPath } from "./services/auditLogger.js";
import { buildUiDispatchPayload, dispatchUiUpdate } from "./services/uiDispatchService.js";
import { getVaultPath, readVault } from "./services/vaultService.js";
import { subscribeUiDispatch } from "./services/uiDispatchService.js";
import type { UiDispatchPayload } from "./types.js";

// Broadcast SSE to all connected web clients from any source (including MCP process).
const sseClients = new Set<Response>();
const auditClients = new Set<Response>();

// Byte offset: only serve log content written after this position.
// Set to current file size on Clear so old entries never reappear.
let auditClearOffset = 0;

function broadcastAuditClear(): void {
  const data = `data: ${JSON.stringify({ tail: "" })}\n\n`;
  for (const client of auditClients) {
    client.write(data);
  }
}

function broadcastSse(payload: UiDispatchPayload): void {
  const data = `data: ${JSON.stringify(payload)}\n\n`;
  for (const client of sseClients) {
    client.write(data);
  }
}

function watchVaultForChanges(vaultPath: string): void {
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  fs.watch(vaultPath, { persistent: false }, () => {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(async () => {
      try {
        const payload = await buildUiDispatchPayload(false);
        // The watcher fired because live data was just written to vault.
        // Override the cache flag so the UI shows "Live probe" not "Vault cache".
        payload.probe.metadata.usedLocalFreshData = false;
        payload.probe.metadata.latestDataTs = new Date().toISOString();
        broadcastSse(payload);
        auditLog("SSE broadcast triggered by vault change", { clients: sseClients.size });
      } catch (error) {
        auditLog("SSE vault-watch broadcast error", { error: String(error) });
      }
    }, 250);
  });
}

function sseHeaders(res: Response): void {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
}

export function startWebServer(port: number): void {
  const app = express();
  app.use(express.json());
  app.use(express.static(path.resolve(process.cwd(), "public")));

  app.get("/api/status", (_req: Request, res: Response) => {
    res.json({ status: "ok", now: new Date().toISOString() });
  });

  app.get("/api/vault", (_req: Request, res: Response) => {
    res.json(readVault());
  });

  app.post("/api/dispatch", async (req: Request, res: Response) => {
    const force = Boolean(req.body?.force);
    const payload = await dispatchUiUpdate(force);
    res.json(payload);
  });

  app.get("/api/ui/stream", (req: Request, res: Response) => {
    sseHeaders(res);
    sseClients.add(res);

    // Also subscribe to in-process broadcasts (web server's own /api/dispatch calls).
    const unsubscribe = subscribeUiDispatch((payload) => {
      res.write(`data: ${JSON.stringify(payload)}\n\n`);
    });

    res.write(`data: ${JSON.stringify({ type: "connected", ts: new Date().toISOString() })}\n\n`);
    req.on("close", () => {
      sseClients.delete(res);
      unsubscribe();
      res.end();
    });
  });

  app.get("/api/audit/stream", (req: Request, res: Response) => {
    sseHeaders(res);
    const logPath = getAuditLogPath();
    auditClients.add(res);

    const sendTail = (): void => {
      try {
        const size = fs.statSync(logPath).size;
        if (size <= auditClearOffset) {
          // Nothing written after the last clear.
          res.write(`data: ${JSON.stringify({ tail: "" })}\n\n`);
          return;
        }
        const fd = fs.openSync(logPath, "r");
        const len = size - auditClearOffset;
        const buf = Buffer.alloc(len);
        fs.readSync(fd, buf, 0, len, auditClearOffset);
        fs.closeSync(fd);
        const lines = buf.toString("utf-8").split(/\r?\n/).slice(-120).join("\n");
        res.write(`data: ${JSON.stringify({ tail: lines })}\n\n`);
      } catch {
        // file may not exist yet
      }
    };

    sendTail();
    const timer = setInterval(sendTail, 2000);

    req.on("close", () => {
      auditClients.delete(res);
      clearInterval(timer);
      res.end();
    });
  });

  app.delete("/api/audit/log", (_req: Request, res: Response) => {
    try {
      // Move the offset to the current end of the file so all existing
      // content is hidden. New entries written after this point will show up.
      const logPath = getAuditLogPath();
      auditClearOffset = fs.existsSync(logPath) ? fs.statSync(logPath).size : 0;
      broadcastAuditClear();
      res.json({ ok: true });
    } catch (error) {
      res.status(500).json({ ok: false, error: String(error) });
    }
  });

  app.get("/api/files", (_req: Request, res: Response) => {
    res.json({
      vaultPath: getVaultPath(),
      auditPath: getAuditLogPath()
    });
  });

  app.listen(port, () => {
    auditLog("Web server online", { port });
    console.log(`CrisisFlow web server listening on http://localhost:${port}`);

    // Watch vault for changes written by MCP process so SSE updates cross-process.
    const vaultPath = getVaultPath();
    watchVaultForChanges(vaultPath);
    auditLog("Vault file watcher started", { vaultPath });
  });
}
