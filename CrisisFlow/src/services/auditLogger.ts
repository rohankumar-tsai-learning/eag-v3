import fs from "node:fs";
import path from "node:path";

const logDir = path.resolve(process.cwd(), "logs");
const logFile = path.join(logDir, "session_audit.log");

let initialized = false;

function ensureLogFile(): void {
  if (!fs.existsSync(logDir)) {
    fs.mkdirSync(logDir, { recursive: true });
  }
  if (!fs.existsSync(logFile)) {
    fs.writeFileSync(logFile, "", "utf-8");
  }
}

function writeLine(level: string, message: string, meta?: unknown): void {
  ensureLogFile();
  const stamp = new Date().toISOString();
  const payload = meta === undefined ? "" : ` ${JSON.stringify(meta)}`;
  fs.appendFileSync(logFile, `[${stamp}] [${level}] ${message}${payload}\n`, "utf-8");
}

export function setupConsoleTee(): void {
  if (initialized) {
    return;
  }
  ensureLogFile();
  const origLog = console.log.bind(console);
  const origError = console.error.bind(console);
  const origWarn = console.warn.bind(console);

  console.log = (...args: unknown[]) => {
    writeLine("CONSOLE", "log", args);
    origLog(...args);
  };

  console.error = (...args: unknown[]) => {
    writeLine("CONSOLE", "error", args);
    origError(...args);
  };

  console.warn = (...args: unknown[]) => {
    writeLine("CONSOLE", "warn", args);
    origWarn(...args);
  };

  initialized = true;
  writeLine("SYSTEM", "Console tee initialized");
}

export function auditLog(message: string, meta?: unknown): void {
  writeLine("AUDIT", message, meta);
}

export function getAuditLogPath(): string {
  ensureLogFile();
  return logFile;
}
