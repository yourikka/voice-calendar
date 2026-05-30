const { contextBridge, ipcRenderer } = require("electron");

function debugLog(event, payload = {}) {
  try {
    ipcRenderer.send("overlay:debug-log", {
      event,
      payload,
      at: new Date().toISOString(),
    });
  } catch (_) {
    // Ignore logging failures in preload.
  }
}

async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary);
}

contextBridge.exposeInMainWorld("overlayAPI", {
  getConfig: () => ipcRenderer.invoke("overlay:config"),
  getPendingNotification: () => null,
  openCalendar: () => ipcRenderer.invoke("overlay:open-calendar"),
  callMcpTool: (toolName, argumentsPayload) => ipcRenderer.invoke("overlay:call-mcp-tool", toolName, argumentsPayload),
  setMode: (mode, contentHeight, contentWidth) => ipcRenderer.invoke("overlay:set-mode", mode, contentHeight, contentWidth),
  startDrag: (screenX, screenY) => ipcRenderer.invoke("overlay:drag-start", { screenX, screenY }),
  moveDrag: (screenX, screenY) => ipcRenderer.invoke("overlay:drag-move", { screenX, screenY }),
  endDrag: () => ipcRenderer.invoke("overlay:drag-end"),
  startVoiceCapture: () => Promise.resolve({ ok: false, error: "Electron 桌面端未启用原生录音接口。" }),
  stopVoiceCapture: () => Promise.resolve({ ok: false, error: "Electron 桌面端未启用原生录音接口。" }),
  audioToBase64: (blob) => blobToBase64(blob),
  debugLog,
});
