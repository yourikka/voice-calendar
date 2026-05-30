const bubbleToggle = document.querySelector("#bubble-toggle");
const assistantPanel = document.querySelector("#assistant-panel");
const closePanelButton = document.querySelector("#close-panel");
const openCalendarButton = document.querySelector("#open-calendar");
const recordButton = document.querySelector("#record-audio");
const sendButton = document.querySelector("#send-command");
const undoButton = document.querySelector("#undo-button");
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
const voiceProvider = document.querySelector("#voice-provider");
const toolNameInput = document.querySelector("#tool-name");
const commandInput = document.querySelector("#command-input");
const transcriptText = document.querySelector("#transcript-text");
const intentText = document.querySelector("#intent-text");
const resultText = document.querySelector("#result-text");
const voiceOrbLabel = document.querySelector("#voice-orb-label");

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

async function bootstrap() {
  const config = await window.overlayAPI.getConfig();
  backendText.textContent = config.backendBaseUrl;
  await setMode("compact");
}

async function setMode(mode) {
  isExpanded = mode === "expanded";
  assistantPanel.hidden = !isExpanded;
  bubbleToggle.hidden = isExpanded;
  await window.overlayAPI.setMode(mode);
}

function setBusy(label) {
  statusText.textContent = label;
}

function setIdle() {
  statusText.textContent = "待命";
}

function formatCandidateTime(value) {
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
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

function applyAgentResult(result) {
  sessionId = result.session_id || sessionId;
  pendingOperationId = result.operation_id || null;
  pendingIntent = result.intent || null;
  pendingSlots = result.slots || {};

  stateText.textContent = result.state || "unknown";
  replyText.textContent = result.reply_text || "已处理。";
  transcriptText.textContent = result.transcript || "等待语音输入";
  intentText.textContent = result.intent || "unknown";
  resultText.textContent = JSON.stringify(result, null, 2);

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

  undoButton.disabled = result.state !== "completed";
  commandInput.placeholder = result.state === "collecting_slots"
    ? `${result.reply_text} 例如：明天晚上八点`
    : "例如：明晚八点提醒我开周会";
}

async function sendTextCommand() {
  const text = commandInput.value.trim();
  if (!text) return;
  setBusy("执行中");
  try {
    const toolName = normalizeToolName(toolNameInput.value);
    const toolCall = resolveTextToolCall(toolName, text);
    const result = await window.overlayAPI.callMcpTool(toolCall.toolName, toolCall.argumentsPayload);
    applyAgentResult(result);
    commandInput.value = "";
  } catch (error) {
    stateText.textContent = "error";
    replyText.textContent = String(error.message || error);
  } finally {
    setIdle();
  }
}

async function startRecording() {
  mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
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
  setBusy("录音中");
  voiceOrbLabel.textContent = "停止";
  stateText.textContent = "录音中";
}

async function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") return;
  mediaRecorder.stop();
  recording = false;
  setBusy("识别中");
  voiceOrbLabel.textContent = "处理中";
}

async function handleVoiceBlob(blob) {
  try {
    const audioBase64 = await window.overlayAPI.audioToBase64(blob);
    const toolName = normalizeToolName(toolNameInput.value);
    const result = await executeVoiceTool(toolName, audioBase64, blob.type || "audio/webm");
    voiceProvider.textContent = result.asr_provider || toolName;
    voiceOrbLabel.textContent = "按住说";
    applyAgentResult(result);
  } catch (error) {
    voiceOrbLabel.textContent = "重试";
    stateText.textContent = "error";
    replyText.textContent = String(error.message || error);
  } finally {
    setIdle();
  }
}

function normalizeToolName(value) {
  return value.trim() || "voice.handle_command";
}

function buildTextPayload(toolName, text) {
  const basePayload = {
    text,
    locale: "zh-CN",
    timezone: "Asia/Shanghai",
    now: new Date().toISOString(),
  };
  if (toolName === "calendar.handle_command") {
    return {
      ...basePayload,
      session_id: sessionId,
    };
  }
  return basePayload;
}

function buildVoicePayload(toolName, audioBase64, contentType) {
  const basePayload = {
    audio_base64: audioBase64,
    filename: "voice-input.webm",
    content_type: contentType,
    locale: "zh-CN",
    timezone: "Asia/Shanghai",
    now: new Date().toISOString(),
  };
  if (toolName === "voice.handle_command" || toolName === "calendar.handle_command") {
    return {
      ...basePayload,
      session_id: sessionId,
    };
  }
  return basePayload;
}

function resolveTextToolCall(toolName, text) {
  if (toolName === "voice.handle_command") {
    return {
      toolName: "calendar.handle_command",
      argumentsPayload: buildTextPayload("calendar.handle_command", text),
    };
  }
  return {
    toolName,
    argumentsPayload: buildTextPayload(toolName, text),
  };
}

async function executeVoiceTool(toolName, audioBase64, contentType) {
  if (toolName === "voice.handle_command") {
    return window.overlayAPI.callMcpTool(
      "voice.handle_command",
      buildVoicePayload("voice.handle_command", audioBase64, contentType),
    );
  }

  const transcriptResult = await window.overlayAPI.callMcpTool(
    "voice.transcribe_audio",
    buildVoicePayload("voice.transcribe_audio", audioBase64, contentType),
  );
  const transcript = transcriptResult.transcript?.trim();
  if (!transcript) {
    throw new Error("未识别到有效语音内容。");
  }

  const targetTool = toolName === "voice.transcribe_audio" ? "calendar.handle_command" : toolName;
  const targetResult = await window.overlayAPI.callMcpTool(
    targetTool,
    buildTextPayload(targetTool, transcript),
  );
  return {
    ...targetResult,
    transcript,
    asr_provider: transcriptResult.asr_provider || targetResult.asr_provider,
  };
}

async function undoLastOperation() {
  setBusy("撤销中");
  try {
    const result = await window.overlayAPI.callMcpTool("calendar.undo_last_operation", {});
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
    replyText.textContent = String(error.message || error);
  } finally {
    setIdle();
  }
}

async function confirmPendingOperation(confirmed) {
  if (!pendingOperationId) return;
  setBusy(confirmed ? "确认中" : "取消中");
  try {
    const result = await window.overlayAPI.callMcpTool("calendar.confirm_operation", {
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
    replyText.textContent = String(error.message || error);
  } finally {
    setIdle();
  }
}

async function resolveCandidateSelection(index) {
  const candidate = pendingCandidates[index];
  if (!candidate || !pendingIntent) return;
  setBusy("处理中");
  try {
    const result = await window.overlayAPI.callMcpTool("calendar.resolve_candidate", {
      intent: pendingIntent,
      candidate_id: candidate.id,
      timezone: "Asia/Shanghai",
      session_id: sessionId,
      slots: pendingSlots,
    });
    applyAgentResult(result);
  } catch (error) {
    stateText.textContent = "error";
    replyText.textContent = String(error.message || error);
  } finally {
    setIdle();
  }
}

bubbleToggle.addEventListener("click", async () => {
  await setMode("expanded");
});

closePanelButton.addEventListener("click", async () => {
  await setMode("compact");
});

openCalendarButton.addEventListener("click", async () => {
  await window.overlayAPI.openCalendar();
});

recordButton.addEventListener("click", async () => {
  if (!recording) {
    await startRecording();
    return;
  }
  await stopRecording();
});

sendButton.addEventListener("click", async () => {
  await sendTextCommand();
});

undoButton.addEventListener("click", async () => {
  await undoLastOperation();
});

confirmButton.addEventListener("click", async () => {
  await confirmPendingOperation(true);
});

cancelButton.addEventListener("click", async () => {
  await confirmPendingOperation(false);
});

candidateList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-candidate-index]");
  if (!button) return;
  await resolveCandidateSelection(Number(button.dataset.candidateIndex));
});

bootstrap().catch((error) => {
  backendText.textContent = "连接失败";
  stateText.textContent = "error";
  replyText.textContent = String(error.message || error);
});
