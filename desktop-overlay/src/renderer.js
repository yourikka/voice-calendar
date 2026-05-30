const compactBar = document.querySelector("#compact-bar");
const assistantPanel = document.querySelector("#assistant-panel");
const expandPanelButton = document.querySelector("#expand-panel");
const closePanelButton = document.querySelector("#close-panel");
const openCalendarButton = document.querySelector("#open-calendar");
const recordButton = document.querySelector("#record-audio");
const toolPanelToggleButton = document.querySelector("#tool-panel-toggle");
const toolPanelBody = document.querySelector("#tool-panel-body");
const confirmButton = document.querySelector("#confirm-button");
const cancelButton = document.querySelector("#cancel-button");
const candidateList = document.querySelector("#candidate-list");
const candidatePanel = document.querySelector("#candidate-panel");
const confirmationPanel = document.querySelector("#confirmation-panel");
const candidateCount = document.querySelector("#candidate-count");
const statusText = document.querySelector("#status-text");
const backendText = document.querySelector("#backend-text");
const stateText = document.querySelector("#state-text");
const replyText = document.querySelector("#reply-text");
const replyMessage = document.querySelector("#reply-message");
const parserSource = document.querySelector("#parser-source");
const voiceProvider = document.querySelector("#voice-provider");
const toolChecklist = document.querySelector("#tool-checklist");
const transcriptText = document.querySelector("#transcript-text");
const voiceOrbLabel = document.querySelector("#voice-orb-label");
const compactDragHandle = document.querySelector("#compact-drag-handle");
const panelDragHandle = document.querySelector("#panel-drag-handle");

let overlayBridge = null;
let isExpanded = false;
let mediaRecorder = null;
let mediaStream = null;
let audioChunks = [];
let recording = false;
let sessionId = null;
let pendingOperationId = null;
let pendingCandidates = [];
let pendingIntent = null;
let pendingSlots = {};
let toolOptions = [];
let enabledTools = new Set(["voice.handle_command"]);
let dragMode = "bridge";
let nativeAudioCapture = false;
let nativeRecording = false;
let toolPanelExpanded = false;
let dragging = false;

function debugLog(event, payload = {}) {
  try {
    if (window.overlayAPI?.debugLog) {
      window.overlayAPI.debugLog(event, payload);
    }
  } catch (_) {
    // Ignore debug logging failures in renderer.
  }
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("音频读取失败。"));
    reader.onloadend = () => {
      const payload = typeof reader.result === "string" ? reader.result.split(",")[1] : "";
      resolve(payload || "");
    };
    reader.readAsDataURL(blob);
  });
}

function createPywebviewOverlayAPI(api) {
  return {
    getConfig: () => api.get_config(),
    getPendingNotification: () => api.get_pending_notification(),
    openCalendar: () => api.open_calendar(),
    callMcpTool: (toolName, argumentsPayload) => api.call_mcp_tool(toolName, argumentsPayload),
    setMode: (mode, contentHeight, contentWidth) => api.set_mode(mode, contentHeight, contentWidth),
    startDrag: (screenX, screenY) => api.start_drag(screenX, screenY),
    moveDrag: (screenX, screenY) => api.move_drag(screenX, screenY),
    endDrag: () => api.end_drag(),
    startVoiceCapture: () => api.start_voice_capture(),
    stopVoiceCapture: () => api.stop_voice_capture(),
    audioToBase64: (blob) => blobToBase64(blob),
  };
}

async function resolveOverlayAPI() {
  if (window.overlayAPI) {
    return window.overlayAPI;
  }
  if (window.pywebview?.api) {
    return createPywebviewOverlayAPI(window.pywebview.api);
  }
  await new Promise((resolve) => {
    window.addEventListener("pywebviewready", resolve, { once: true });
  });
  if (window.pywebview?.api) {
    return createPywebviewOverlayAPI(window.pywebview.api);
  }
  throw new Error("未找到桌面桥接接口。");
}

async function bootstrap() {
  debugLog("bootstrap:start");
  overlayBridge = await resolveOverlayAPI();
  debugLog("bootstrap:resolved-api", { hasOverlayApi: Boolean(overlayBridge) });
  const config = await overlayBridge.getConfig();
  debugLog("bootstrap:config", config);
  backendText.textContent = (config.backendBaseUrl || "").replace(/\/+$/, "");
  dragMode = config.dragMode || "bridge";
  nativeAudioCapture = Boolean(config.nativeAudioCapture);
  toolOptions = Array.isArray(config.toolOptions) ? config.toolOptions : [];
  renderToolChecklist();
  installBridgeDrag(compactDragHandle);
  installBridgeDrag(panelDragHandle);
  setToolPanelExpanded(false);
  await setMode("compact");
  window.setInterval(async () => {
    try {
      const pending = await overlayBridge.getPendingNotification();
      if (pending?.title || pending?.body) {
        stateText.textContent = "提醒";
        replyText.textContent = pending.body || pending.title || "到点了";
        replyMessage.textContent = pending.title || "提醒";
        transcriptText.textContent = pending.body || "到点了";
        parserSource.textContent = "解析来源：到点提醒";
        voiceProvider.textContent = "本地提醒";
        await setMode("expanded");
      }
    } catch (error) {
      // Ignore polling errors to avoid breaking the overlay UI loop.
    }
  }, 1000);
}

async function setMode(mode) {
  isExpanded = mode === "expanded";
  assistantPanel.hidden = !isExpanded;
  const contentHeight = isExpanded ? measureExpandedContentHeight() : measureCompactContentHeight();
  const contentWidth = isExpanded ? undefined : measureCompactContentWidth();
  await overlayBridge.setMode(mode, contentHeight, contentWidth);
  if (isExpanded) {
    queueExpandedWindowSync();
  } else {
    queueCompactWindowSync();
  }
}

function setBusy(label) {
  statusText.textContent = label;
  stateText.textContent = label;
}

function setIdle() {
  statusText.textContent = "待命";
}

function installBridgeDrag(element) {
  if (!element || dragMode !== "bridge") {
    return;
  }
  element.addEventListener("pointerdown", async (event) => {
    if (event.button !== 0) {
      return;
    }
    debugLog("drag:pointerdown", { id: element.id || null, screenX: event.screenX, screenY: event.screenY });
    dragging = true;
    try {
      await overlayBridge.startDrag(event.screenX, event.screenY);
    } catch (_) {
      dragging = false;
    }
  });
}

window.addEventListener("pointermove", (event) => {
  if (!dragging || dragMode !== "bridge") {
    return;
  }
  debugLog("drag:pointermove", { screenX: event.screenX, screenY: event.screenY });
  void overlayBridge.moveDrag(event.screenX, event.screenY);
});

window.addEventListener("pointerup", () => {
  if (!dragging || dragMode !== "bridge") {
    return;
  }
  dragging = false;
  debugLog("drag:pointerup");
  void overlayBridge.endDrag();
});

window.addEventListener("pointercancel", () => {
  if (!dragging || dragMode !== "bridge") {
    return;
  }
  dragging = false;
  debugLog("drag:pointercancel");
  void overlayBridge.endDrag();
});

function setToolPanelExpanded(expanded) {
  toolPanelExpanded = expanded;
  toolPanelBody.hidden = !expanded;
  toolPanelToggleButton.setAttribute("aria-expanded", String(expanded));
  if (isExpanded) {
    queueExpandedWindowSync();
  }
}

function measureExpandedContentHeight() {
  const compactRect = compactBar.getBoundingClientRect();
  const panelRect = assistantPanel.getBoundingClientRect();
  return Math.ceil(panelRect.bottom - compactRect.top);
}

function measureCompactContentHeight() {
  return Math.ceil(compactBar.getBoundingClientRect().height);
}

function measureCompactContentWidth() {
  return Math.ceil(compactBar.getBoundingClientRect().width);
}

function queueExpandedWindowSync() {
  requestAnimationFrame(() => {
    void syncExpandedWindowSize();
    window.setTimeout(() => {
      void syncExpandedWindowSize();
    }, 90);
  });
}

async function syncExpandedWindowSize() {
  if (!isExpanded) {
    return;
  }
  await overlayBridge.setMode("expanded", measureExpandedContentHeight());
}

function queueCompactWindowSync() {
  requestAnimationFrame(() => {
    void syncCompactWindowSize();
    window.setTimeout(() => {
      void syncCompactWindowSize();
    }, 60);
  });
}

async function syncCompactWindowSize() {
  if (isExpanded) {
    return;
  }
  await overlayBridge.setMode("compact", measureCompactContentHeight(), measureCompactContentWidth());
}

function renderToolChecklist() {
  const options = toolOptions.length > 0 ? toolOptions : [
    {
      value: "voice.handle_command",
      label: "语音日历",
      description: "语音识别后交给日历命令和 agent fallback。",
    },
  ];
  toolChecklist.innerHTML = options.map((tool) => `
    <button
      class="tool-toggle"
      type="button"
      data-tool-value="${tool.value}"
      data-enabled="${String(enabledTools.has(tool.value))}"
      aria-pressed="${String(enabledTools.has(tool.value))}"
    >
      <span class="tool-check" aria-hidden="true">${enabledTools.has(tool.value) ? "✓" : ""}</span>
      <span>
        <span class="tool-name">${tool.label}</span>
        <span class="tool-desc">${tool.description}</span>
      </span>
    </button>
  `).join("");
}

function ensureToolSelection(value) {
  if (enabledTools.has(value)) {
    enabledTools.delete(value);
  } else {
    enabledTools.add(value);
  }
  if (enabledTools.size === 0) {
    enabledTools.add("voice.handle_command");
  }
  renderToolChecklist();
}

function shouldUseTool(toolName, transcript) {
  const text = transcript.replace(/\s+/g, "");
  if (toolName === "voice.handle_command" || toolName === "calendar.handle_command") {
    return true;
  }
  if (toolName === "news.get_today_hot_topics") {
    return /(热点|新闻|资讯|今日|今天)/.test(text);
  }
  return true;
}

function buildTextPayload(toolName, text) {
  const basePayload = {
    text,
    locale: "zh-CN",
    timezone: "Asia/Shanghai",
    now: new Date().toISOString(),
  };
  if (toolName === "calendar.handle_command" || toolName === "voice.handle_command") {
    return {
      ...basePayload,
      session_id: sessionId,
    };
  }
  return basePayload;
}

function buildVoicePayload(audioBase64, contentType) {
  return {
    audio_base64: audioBase64,
    filename: "voice-input.webm",
    content_type: contentType,
    locale: "zh-CN",
    timezone: "Asia/Shanghai",
    session_id: sessionId,
    now: new Date().toISOString(),
  };
}

function formatCandidateTime(value) {
  const date = new Date(value);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: date.getSeconds() ? "2-digit" : undefined,
    hour12: false,
  });
}

function renderCandidates(candidates) {
  pendingCandidates = candidates || [];
  candidateCount.textContent = String(pendingCandidates.length);
  candidateList.innerHTML = pendingCandidates.map((candidate, index) => `
    <button class="candidate-button" type="button" data-candidate-index="${index}">
      <strong>${candidate.title}</strong>
      <span>${formatCandidateTime(candidate.start_at)}</span>
    </button>
  `).join("");
  candidatePanel.hidden = pendingCandidates.length === 0;
}

function formatEventSummary(event) {
  if (!event?.start_at) {
    return "";
  }
  const start = new Date(event.start_at);
  const when = start.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: start.getSeconds() ? "2-digit" : undefined,
    hour12: false,
  });
  return `${when} ${event.title || ""}`.trim();
}

function describeParserSource(parser) {
  if (!parser || parser === "rule" || parser === "rule+context") {
    return "解析来源：规则";
  }
  if (String(parser).startsWith("agent:")) {
    return "解析来源：Agent fallback";
  }
  return `解析来源：${parser}`;
}

function applyAgentResult(result) {
  sessionId = result.session_id || sessionId;
  pendingOperationId = result.operation_id || null;
  pendingIntent = result.intent || null;
  pendingSlots = result.slots || {};

  const state = result.state || "unknown";
  let reply = result.reply_text || "已处理。";
  const transcript = result.transcript || result.text || "等待语音输入";

  if (state === "completed" && result.event?.title && result.intent === "create_event") {
    reply = `创建成功：${formatEventSummary(result.event)}`;
  } else if (state === "completed" && result.event?.title && result.intent === "create_reminder") {
    reply = `提醒已设置：${formatEventSummary(result.event)}`;
  } else if (state === "completed" && result.intent === "delete_event") {
    reply = result.deleted_count && result.deleted_count > 1
      ? `已删除 ${result.deleted_count} 个日程`
      : (result.reply_text || "已删除日程");
  }

  stateText.textContent = state;
  replyText.textContent = reply;
  replyMessage.textContent = reply;
  transcriptText.textContent = transcript;
  parserSource.textContent = describeParserSource(result.parser);

  candidatePanel.hidden = true;
  confirmationPanel.hidden = true;

  if (Array.isArray(result.candidates) && result.candidates.length > 0) {
    renderCandidates(result.candidates);
  } else {
    pendingCandidates = [];
  }

  if (result.state === "awaiting_confirmation" && result.operation_id) {
    confirmationPanel.hidden = false;
  }

  if (!result.requires_user_input && result.state !== "awaiting_confirmation") {
    pendingOperationId = null;
    pendingIntent = null;
    pendingSlots = {};
  }

}

function mergeResults(results, transcript, provider) {
  const primary = results.find((item) => item.result?.reply_text || item.result?.state) || results[0];
  if (!primary) {
    return {
      state: "completed",
      transcript,
      reply_text: "已处理。",
      asr_provider: provider,
    };
  }
  return {
    ...primary.result,
    transcript: primary.result?.transcript || transcript,
    asr_provider: primary.result?.asr_provider || provider,
    tool_results: results,
  };
}

async function executeSelectedTools(audioBase64, contentType) {
  const selected = Array.from(enabledTools);
  const hasVoiceAgent = selected.includes("voice.handle_command");
  let transcript = "";
  let provider = "";
  const toolResults = [];

  if (hasVoiceAgent) {
    const result = await overlayBridge.callMcpTool("voice.handle_command", buildVoicePayload(audioBase64, contentType));
    transcript = result.transcript || "";
    provider = result.asr_provider || "voice.handle_command";
    toolResults.push({ tool: "voice.handle_command", result });
  }

  const extraTools = selected.filter((toolName) => toolName !== "voice.handle_command");
  if (extraTools.length > 0 && !transcript) {
    const transcriptResult = await overlayBridge.callMcpTool("voice.transcribe_audio", {
      audio_base64: audioBase64,
      filename: "voice-input.webm",
      content_type: contentType,
      locale: "zh-CN",
    });
    transcript = transcriptResult.transcript?.trim() || "";
    provider = transcriptResult.asr_provider || provider;
  }

  if (!transcript && toolResults.length === 0) {
    throw new Error("未识别到有效语音内容。");
  }

  for (const toolName of extraTools) {
    if (!shouldUseTool(toolName, transcript)) {
      continue;
    }
    const result = await overlayBridge.callMcpTool(toolName, buildTextPayload(toolName, transcript));
    toolResults.push({ tool: toolName, result });
  }

  if (toolResults.length === 0) {
    const result = await overlayBridge.callMcpTool("calendar.handle_command", buildTextPayload("calendar.handle_command", transcript));
    toolResults.push({ tool: "calendar.handle_command", result });
  }

  return {
    result: mergeResults(toolResults, transcript, provider),
    transcript,
    provider,
  };
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("当前环境不支持麦克风采集，请切换系统浏览器或升级 WebKitGTK。");
  }
  if (typeof MediaRecorder === "undefined") {
    throw new Error("当前环境不支持 MediaRecorder，无法开始录音。");
  }

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    if (error?.name === "NotAllowedError") {
      throw new Error("麦克风权限被拒绝，请在系统里允许该应用访问麦克风。");
    }
    if (error?.name === "NotFoundError") {
      throw new Error("未检测到可用麦克风设备。");
    }
    if (error?.name === "NotReadableError") {
      throw new Error("麦克风正在被其他应用占用，请关闭占用后重试。");
    }
    throw new Error(`麦克风初始化失败：${error?.message || error}`);
  }

  mediaStream = stream;
  const tracks = mediaStream.getAudioTracks();
  if (!tracks || tracks.length === 0) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
    throw new Error("麦克风打开成功但没有可用音频轨道。");
  }

  audioChunks = [];
  mediaRecorder = new MediaRecorder(mediaStream);
  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      audioChunks.push(event.data);
    }
  });
  mediaRecorder.addEventListener("stop", async () => {
    const blob = new Blob(audioChunks, { type: mediaRecorder?.mimeType || "audio/webm" });
    audioChunks = [];
    mediaStream?.getTracks().forEach((track) => track.stop());
    mediaStream = null;
    await handleVoiceBlob(blob);
  });
  mediaRecorder.start();
  recording = true;
  recordButton.classList.add("recording");
  setBusy("录音中");
  voiceOrbLabel.textContent = "停止";
}

async function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") {
    return;
  }
  mediaRecorder.stop();
  recording = false;
  recordButton.classList.remove("recording");
  setBusy("识别中");
  voiceOrbLabel.textContent = "处理中";
}

async function startNativeRecording() {
  if (!overlayBridge.startVoiceCapture) {
    throw new Error("当前桌面桥接未启用原生录音接口。");
  }
  const result = await overlayBridge.startVoiceCapture();
  if (!result?.ok) {
    throw new Error(result?.error || "原生录音启动失败。");
  }
  nativeRecording = true;
  recording = true;
  recordButton.classList.add("recording");
  setBusy("录音中");
  voiceOrbLabel.textContent = "停止";
}

async function stopNativeRecording() {
  if (!overlayBridge.stopVoiceCapture) {
    throw new Error("当前桌面桥接未启用原生录音接口。");
  }
  const result = await overlayBridge.stopVoiceCapture();
  nativeRecording = false;
  recording = false;
  recordButton.classList.remove("recording");
  setBusy("识别中");
  voiceOrbLabel.textContent = "处理中";

  if (!result?.ok) {
    throw new Error(result?.error || "原生录音停止失败。");
  }

  const execution = await executeSelectedTools(result.audio_base64, result.content_type || "audio/wav");
  voiceProvider.textContent = result.provider || execution.provider || "native-audio";
  voiceOrbLabel.textContent = "语音";
  applyAgentResult(execution.result);
}

async function handleVoiceBlob(blob) {
  try {
    const audioBase64 = await overlayBridge.audioToBase64(blob);
    const execution = await executeSelectedTools(audioBase64, blob.type || "audio/webm");
    voiceProvider.textContent = execution.provider || "ASR";
    voiceOrbLabel.textContent = "语音";
    applyAgentResult(execution.result);
  } catch (error) {
    voiceOrbLabel.textContent = "重试";
    stateText.textContent = "error";
    const message = String(error.message || error);
    replyText.textContent = message;
    replyMessage.textContent = message;
    parserSource.textContent = "解析来源：未完成";
  } finally {
    setIdle();
  }
}

async function undoLastOperation() {
  setBusy("撤销中");
  try {
    const result = await overlayBridge.callMcpTool("calendar.undo_last_operation", {});
    applyAgentResult({
      ...result,
      intent: "undo_last_operation",
      session_id: sessionId,
      slots: {},
      candidates: [],
      requires_user_input: false,
    });
  } catch (error) {
    stateText.textContent = "error";
    const message = String(error.message || error);
    replyText.textContent = message;
    replyMessage.textContent = message;
    parserSource.textContent = "解析来源：未完成";
  } finally {
    setIdle();
  }
}

async function confirmPendingOperation(confirmed) {
  if (!pendingOperationId) {
    return;
  }
  setBusy(confirmed ? "确认中" : "取消中");
  try {
    const result = await overlayBridge.callMcpTool("calendar.confirm_operation", {
      operation_id: pendingOperationId,
      confirmed,
    });
    applyAgentResult({
      ...result,
      intent: pendingIntent || "confirm_operation",
      session_id: sessionId,
      slots: pendingSlots,
      candidates: [],
      requires_user_input: false,
    });
  } catch (error) {
    stateText.textContent = "error";
    const message = String(error.message || error);
    replyText.textContent = message;
    replyMessage.textContent = message;
    parserSource.textContent = "解析来源：未完成";
  } finally {
    setIdle();
  }
}

async function resolveCandidateSelection(index) {
  const candidate = pendingCandidates[index];
  if (!candidate || !pendingIntent) {
    return;
  }
  setBusy("处理中");
  try {
    const result = await overlayBridge.callMcpTool("calendar.resolve_candidate", {
      intent: pendingIntent,
      candidate_id: candidate.id,
      timezone: "Asia/Shanghai",
      session_id: sessionId,
      slots: pendingSlots,
    });
    applyAgentResult(result);
  } catch (error) {
    stateText.textContent = "error";
    const message = String(error.message || error);
    replyText.textContent = message;
    replyMessage.textContent = message;
  } finally {
    setIdle();
  }
}

expandPanelButton.addEventListener("click", async () => {
  debugLog("click:expand");
  await setMode("expanded");
});

closePanelButton.addEventListener("click", async () => {
  debugLog("click:close");
  await setMode("compact");
});

openCalendarButton.addEventListener("click", async () => {
  debugLog("click:open-calendar");
  try {
    const result = await overlayBridge.openCalendar();
    if (result && result.ok === true) {
      replyMessage.textContent = "已打开浏览器日历页面。";
      replyText.textContent = "已打开浏览器日历页面。";
      return;
    }
    const message = result?.error || "打开浏览器失败。";
    replyMessage.textContent = message;
    replyText.textContent = message;
  } catch (error) {
    const message = String(error?.message || error || "打开浏览器失败。");
    replyMessage.textContent = message;
    replyText.textContent = message;
  }
});

toolChecklist.addEventListener("click", (event) => {
  const button = event.target.closest("[data-tool-value]");
  if (!button) {
    return;
  }
  ensureToolSelection(button.dataset.toolValue);
});

toolPanelToggleButton.addEventListener("click", () => {
  setToolPanelExpanded(!toolPanelExpanded);
});

recordButton.addEventListener("click", async () => {
  debugLog("click:record", { nativeAudioCapture, nativeRecording, recording });
  try {
    if (nativeAudioCapture) {
      if (!nativeRecording) {
        setBusy("请求麦克风");
        await startNativeRecording();
        return;
      }
      await stopNativeRecording();
      setIdle();
      return;
    }

    if (!recording) {
      setBusy("请求麦克风");
      await startRecording();
      return;
    }
    await stopRecording();
  } catch (error) {
    recording = false;
    recordButton.classList.remove("recording");
    voiceOrbLabel.textContent = "重试";
    stateText.textContent = "error";
    const message = String(error.message || error);
    replyText.textContent = message;
    replyMessage.textContent = message;
    parserSource.textContent = "解析来源：未完成";
    setIdle();
  }
});

confirmButton.addEventListener("click", async () => {
  await confirmPendingOperation(true);
});

cancelButton.addEventListener("click", async () => {
  await confirmPendingOperation(false);
});

candidateList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-candidate-index]");
  if (!button) {
    return;
  }
  await resolveCandidateSelection(Number(button.dataset.candidateIndex));
});

bootstrap().catch((error) => {
  debugLog("bootstrap:error", { message: String(error.message || error) });
  backendText.textContent = "连接失败";
  stateText.textContent = "error";
  const message = String(error.message || error);
  replyText.textContent = message;
  replyMessage.textContent = message;
  parserSource.textContent = "解析来源：未初始化";
});

window.addEventListener("error", (event) => {
  debugLog("window:error", {
    message: event.message,
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
  });
});

window.addEventListener("unhandledrejection", (event) => {
  debugLog("window:unhandledrejection", {
    reason: String(event.reason?.message || event.reason || "unknown"),
  });
});
