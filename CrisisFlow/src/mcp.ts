import "dotenv/config";
import { startMcpServer } from "./mcpServer.js";
import { setupConsoleTee } from "./services/auditLogger.js";

async function main(): Promise<void> {
  setupConsoleTee();
  const port = Number.parseInt(process.env.MCP_PORT || "8181", 10);
  await startMcpServer(port);
}

main().catch((error) => {
  console.error("Fatal MCP startup error", error);
  process.exit(1);
});
