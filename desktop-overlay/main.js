const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("node:path");

const BACKEND_BASE_URL = process.env.VOICE_CALENDAR_API_BASE || "http://127.0.0.1:8000";
const MCP_BASE_URL = process.env.VOICE_CALENDAR_MCP_BASE || "http://127.0.0.1:8001";

let overlayWindow = null;
let overlayMcpClient = null;

async function getMcpClient() {
  if (!overlayMcpClient) {
    const module = await import(path.join(__dirname, "mcpClient.mjs"));
    overlayMcpClient = new module.OverlayMcpClient(MCP_BASE_URL);
  }
  return overlayMcpClient;
}

function createOverlayWindow() {
  overlayWindow = new BrowserWindow({
    width: 360,
    height: 520,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    skipTaskbar: false,
    hasShadow: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  overlayWindow.loadFile(path.join(__dirname, "src/index.html"));
  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });
}

app.whenReady().then(() => {
  createOverlayWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createOverlayWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", async () => {
  if (overlayMcpClient) {
    await overlayMcpClient.close();
  }
});

ipcMain.handle("overlay:config", async () => {
  return {
    backendBaseUrl: BACKEND_BASE_URL,
    mcpBaseUrl: MCP_BASE_URL,
    calendarUrl: `${BACKEND_BASE_URL}/`,
  };
});

ipcMain.handle("overlay:open-calendar", async () => {
  await shell.openExternal(`${BACKEND_BASE_URL}/`);
  return { ok: true };
});

ipcMain.handle("overlay:call-mcp-tool", async (_event, toolName, argumentsPayload) => {
  const client = await getMcpClient();
  return client.callTool(toolName, argumentsPayload);
});
