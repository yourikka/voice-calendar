const { contextBridge, ipcRenderer } = require("electron");

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.error || "请求失败");
  }
  return data;
}

async function postAudio(url, blob, locale = "zh-CN") {
  const formData = new FormData();
  formData.append("audio", new File([blob], "voice-input.webm", { type: blob.type || "audio/webm" }));
  formData.append("locale", locale);

  const response = await fetch(url, {
    method: "POST",
    body: formData,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.error || "语音请求失败");
  }
  return data;
}

contextBridge.exposeInMainWorld("overlayAPI", {
  getConfig: () => ipcRenderer.invoke("overlay:config"),
  openCalendar: () => ipcRenderer.invoke("overlay:open-calendar"),
  callMcpTool: async (toolName, argumentsPayload) => {
    const { backendBaseUrl } = await ipcRenderer.invoke("overlay:config");
    return postJson(`${backendBaseUrl}/api/mcp/tools/${toolName}`, {
      arguments: argumentsPayload,
    });
  },
  transcribeAudio: async (blob, locale) => {
    const { backendBaseUrl } = await ipcRenderer.invoke("overlay:config");
    return postAudio(`${backendBaseUrl}/api/voice/transcriptions`, blob, locale);
  },
});
