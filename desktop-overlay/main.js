const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("node:path");

const BACKEND_BASE_URL = process.env.VOICE_CALENDAR_API_BASE || "http://127.0.0.1:8000";

let overlayWindow = null;

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

ipcMain.handle("overlay:config", async () => {
  return {
    backendBaseUrl: BACKEND_BASE_URL,
    calendarUrl: `${BACKEND_BASE_URL}/`,
  };
});

ipcMain.handle("overlay:open-calendar", async () => {
  await shell.openExternal(`${BACKEND_BASE_URL}/`);
  return { ok: true };
});
