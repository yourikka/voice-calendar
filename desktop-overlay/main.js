const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow, ipcMain, screen, shell } = require("electron");

const BACKEND_BASE_URL = process.env.VOICE_CALENDAR_API_BASE || "http://127.0.0.1:8000";
const MCP_BASE_URL = process.env.VOICE_CALENDAR_MCP_BASE || "http://127.0.0.1:8001";
const COMPACT_SIZE = { width: 126, height: 64 };
const EXPANDED_SIZE = { width: 456, height: 468 };
const SNAP_MARGIN = 16;
const DEFAULT_TOOL_OPTIONS = [
  {
    value: "voice.handle_command",
    label: "语音日历",
    description: "录音后直接识别并执行日历命令，适合多轮语音补全。",
  },
  {
    value: "calendar.handle_command",
    label: "文本日历命令",
    description: "文本和转写结果都直接进入日历命令解析。",
  },
  {
    value: "news.get_today_hot_topics",
    label: "今日热点",
    description: "获取当天热点资讯，语音输入会先转写再触发热点工具。",
  },
];

let overlayWindow = null;
let overlayMcpClient = null;
let calendarWindow = null;
let dragState = null;
let overlayState = {
  edge: "right",
  x: null,
  y: null,
  displayId: null,
};

function getDebugLogPath() {
  return path.join(app.getPath("userData"), "overlay-debug.log");
}

function appendDebugLog(entry) {
  try {
    fs.mkdirSync(path.dirname(getDebugLogPath()), { recursive: true });
    fs.appendFileSync(getDebugLogPath(), `${JSON.stringify(entry)}\n`);
  } catch (_) {
    // Ignore debug logging failures.
  }
}

async function getMcpClient() {
  if (!overlayMcpClient) {
    const module = await import(path.join(__dirname, "mcpClient.mjs"));
    overlayMcpClient = new module.OverlayMcpClient(MCP_BASE_URL);
  }
  return overlayMcpClient;
}

function getStateFilePath() {
  return path.join(app.getPath("userData"), "overlay-window-state.json");
}

function getTargetSize(mode) {
  return mode === "expanded" ? EXPANDED_SIZE : COMPACT_SIZE;
}

function loadOverlayState() {
  try {
    const raw = fs.readFileSync(getStateFilePath(), "utf8");
    const parsed = JSON.parse(raw);
    overlayState = {
      edge: parsed.edge === "left" ? "left" : "right",
      x: typeof parsed.x === "number" ? parsed.x : null,
      y: typeof parsed.y === "number" ? parsed.y : null,
      displayId: typeof parsed.displayId === "number" ? parsed.displayId : null,
    };
  } catch {
    overlayState = {
      edge: "right",
      x: null,
      y: null,
      displayId: null,
    };
  }
}

function saveOverlayState() {
  fs.mkdirSync(path.dirname(getStateFilePath()), { recursive: true });
  fs.writeFileSync(getStateFilePath(), JSON.stringify(overlayState, null, 2));
}

function getDisplayForState() {
  if (overlayState.displayId !== null) {
    const matched = screen.getAllDisplays().find((display) => display.id === overlayState.displayId);
    if (matched) {
      return matched;
    }
  }
  return screen.getPrimaryDisplay();
}

function clampBounds(bounds, workArea) {
  const minX = workArea.x + SNAP_MARGIN;
  const maxX = workArea.x + workArea.width - bounds.width - SNAP_MARGIN;
  const minY = workArea.y + SNAP_MARGIN;
  const maxY = workArea.y + workArea.height - bounds.height - SNAP_MARGIN;
  return {
    ...bounds,
    x: Math.min(Math.max(bounds.x, minX), Math.max(minX, maxX)),
    y: Math.min(Math.max(bounds.y, minY), Math.max(minY, maxY)),
  };
}

function buildBoundsFromState(mode) {
  const size = getTargetSize(mode);
  const display = getDisplayForState();
  const { workArea } = display;
  const x = overlayState.x ?? (workArea.x + workArea.width - size.width - SNAP_MARGIN);
  const y = overlayState.y ?? (workArea.y + workArea.height - size.height - SNAP_MARGIN);
  return clampBounds({ x, y, width: size.width, height: size.height }, workArea);
}

function persistWindowPlacement(bounds) {
  const display = screen.getDisplayMatching(bounds);
  const midpoint = display.workArea.x + (display.workArea.width / 2);
  overlayState = {
    edge: bounds.x + (bounds.width / 2) < midpoint ? "left" : "right",
    x: bounds.x,
    y: bounds.y,
    displayId: display.id,
  };
  saveOverlayState();
}

function snapBounds(bounds) {
  const display = screen.getDisplayMatching(bounds);
  const clamped = clampBounds(bounds, display.workArea);
  const midpoint = display.workArea.x + (display.workArea.width / 2);
  const x = clamped.x + (clamped.width / 2) < midpoint
    ? display.workArea.x + SNAP_MARGIN
    : display.workArea.x + display.workArea.width - clamped.width - SNAP_MARGIN;
  return { ...clamped, x };
}

function createOverlayWindow() {
  const initialBounds = buildBoundsFromState("compact");
  overlayWindow = new BrowserWindow({
    width: initialBounds.width,
    height: initialBounds.height,
    x: initialBounds.x,
    y: initialBounds.y,
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
  overlayWindow.webContents.on("did-finish-load", () => {
    appendDebugLog({ event: "webContents:did-finish-load" });
  });
  overlayWindow.webContents.on("dom-ready", () => {
    appendDebugLog({ event: "webContents:dom-ready" });
  });
  overlayWindow.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    appendDebugLog({
      event: "webContents:console-message",
      level,
      message,
      line,
      sourceId,
    });
  });
  overlayWindow.webContents.on("render-process-gone", (_event, details) => {
    appendDebugLog({ event: "webContents:render-process-gone", details });
  });
  overlayWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
    appendDebugLog({
      event: "webContents:did-fail-load",
      errorCode,
      errorDescription,
      validatedURL,
    });
  });
  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });
}

function createCalendarWindow(url) {
  if (calendarWindow && !calendarWindow.isDestroyed()) {
    calendarWindow.loadURL(url);
    calendarWindow.focus();
    return calendarWindow;
  }

  calendarWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 980,
    minHeight: 720,
    autoHideMenuBar: true,
    title: "Voice Calendar Web",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  calendarWindow.loadURL(url);
  calendarWindow.on("closed", () => {
    calendarWindow = null;
  });
  return calendarWindow;
}

function resizeOverlayWindow(mode, contentHeight, contentWidth) {
  if (!overlayWindow) {
    return;
  }
  const target = { ...getTargetSize(mode) };
  if (mode === "expanded" && Number.isFinite(contentHeight)) {
    target.height = Math.max(168, Math.min(Math.round(contentHeight), EXPANDED_SIZE.height));
  }
  if (mode !== "expanded") {
    if (Number.isFinite(contentWidth)) {
      target.width = Math.max(108, Math.min(Math.round(contentWidth), COMPACT_SIZE.width));
    }
    if (Number.isFinite(contentHeight)) {
      target.height = Math.max(52, Math.min(Math.round(contentHeight), COMPACT_SIZE.height));
    }
  }
  const currentBounds = overlayWindow.getBounds();
  const display = screen.getDisplayMatching(currentBounds);
  const nextBounds = clampBounds(
    {
      x: currentBounds.x,
      y: currentBounds.y,
      width: target.width,
      height: target.height,
    },
    display.workArea,
  );
  overlayWindow.setBounds(nextBounds, true);
  persistWindowPlacement(nextBounds);
}

app.whenReady().then(() => {
  loadOverlayState();
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
  appendDebugLog({ event: "overlay:config" });
  return {
    backendBaseUrl: BACKEND_BASE_URL,
    mcpBaseUrl: MCP_BASE_URL,
    calendarUrl: `${BACKEND_BASE_URL}/`,
    dragMode: "bridge",
    nativeAudioCapture: false,
    toolOptions: DEFAULT_TOOL_OPTIONS,
  };
});

ipcMain.handle("overlay:open-calendar", async () => {
  appendDebugLog({ event: "overlay:open-calendar" });
  const url = `${BACKEND_BASE_URL}/`;
  try {
    createCalendarWindow(url);
    return { ok: true, url, target: "electron-window" };
  } catch (error) {
    await shell.openExternal(url);
    return {
      ok: true,
      url,
      target: "external-browser",
      fallback: true,
      message: String(error.message || error),
    };
  }
});

ipcMain.handle("overlay:call-mcp-tool", async (_event, toolName, argumentsPayload) => {
  appendDebugLog({ event: "overlay:call-mcp-tool", toolName });
  const client = await getMcpClient();
  return client.callTool(toolName, argumentsPayload);
});

ipcMain.handle("overlay:set-mode", async (_event, mode, contentHeight, contentWidth) => {
  appendDebugLog({ event: "overlay:set-mode", mode, contentHeight, contentWidth });
  resizeOverlayWindow(mode, contentHeight, contentWidth);
  return { ok: true };
});

ipcMain.handle("overlay:drag-start", async (_event, payload) => {
  appendDebugLog({ event: "overlay:drag-start", payload });
  if (!overlayWindow) {
    return { ok: false };
  }
  const bounds = overlayWindow.getBounds();
  dragState = {
    offsetX: payload.screenX - bounds.x,
    offsetY: payload.screenY - bounds.y,
  };
  return { ok: true };
});

ipcMain.handle("overlay:drag-move", async (_event, payload) => {
  appendDebugLog({ event: "overlay:drag-move", payload });
  if (!overlayWindow || !dragState) {
    return { ok: false };
  }
  const currentBounds = overlayWindow.getBounds();
  const nextBounds = {
    ...currentBounds,
    x: Math.round(payload.screenX - dragState.offsetX),
    y: Math.round(payload.screenY - dragState.offsetY),
  };
  const display = screen.getDisplayMatching(nextBounds);
  const clamped = clampBounds(nextBounds, display.workArea);
  overlayWindow.setBounds(clamped, false);
  return { ok: true };
});

ipcMain.handle("overlay:drag-end", async () => {
  appendDebugLog({ event: "overlay:drag-end" });
  if (!overlayWindow) {
    return { ok: false };
  }
  dragState = null;
  const clamped = clampBounds(overlayWindow.getBounds(), screen.getDisplayMatching(overlayWindow.getBounds()).workArea);
  overlayWindow.setBounds(clamped, false);
  persistWindowPlacement(clamped);
  return { ok: true, bounds: clamped };
});

ipcMain.on("overlay:debug-log", (_event, payload) => {
  appendDebugLog(payload);
});
