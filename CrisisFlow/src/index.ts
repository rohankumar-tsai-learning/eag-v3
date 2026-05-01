import "dotenv/config";
import { setupConsoleTee } from "./services/auditLogger.js";
import { startWebServer } from "./webServer.js";

async function main(): Promise<void> {
  setupConsoleTee();
  const port = Number.parseInt(process.env.PORT || "8080", 10);

  startWebServer(port);
}

main().catch((error) => {
  console.error("Fatal startup error", error);
  process.exit(1);
});
