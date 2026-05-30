const { contextBridge, ipcRenderer } = require("electron");

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
  openCalendar: () => ipcRenderer.invoke("overlay:open-calendar"),
  callMcpTool: (toolName, argumentsPayload) => ipcRenderer.invoke("overlay:call-mcp-tool", toolName, argumentsPayload),
  setMode: (mode) => ipcRenderer.invoke("overlay:set-mode", mode),
  startDrag: (screenX, screenY) => ipcRenderer.invoke("overlay:drag-start", { screenX, screenY }),
  moveDrag: (screenX, screenY) => ipcRenderer.invoke("overlay:drag-move", { screenX, screenY }),
  endDrag: () => ipcRenderer.invoke("overlay:drag-end"),
  audioToBase64: (blob) => blobToBase64(blob),
});
