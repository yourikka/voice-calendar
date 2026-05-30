const commandInput = document.querySelector("#command-input");
const sendButton = document.querySelector("#send-command");
const recordButton = document.querySelector("#record-audio");
const openCalendarButton = document.querySelector("#open-calendar");
const statusText = document.querySelector("#status-text");
const backendText = document.querySelector("#backend-text");
const transcriptText = document.querySelector("#transcript-text");
const resultText = document.querySelector("#result-text");
const intentText = document.querySelector("#intent-text");
const voiceProvider = document.querySelector("#voice-provider");
const replyText = document.querySelector("#reply-text");
const stateText = document.querySelector("#state-text");
const candidatePanel = document.querySelector("#candidate-panel");
const candidateCount = document.querySelector("#candidate-count");
const candidateList = document.querySelector("#candidate-list");
const confirmationPanel = document.querySelector("#confirmation-panel");
const confirmButton = document.querySelector("#confirm-button");
const cancelButton = document.querySelector("#cancel-button");

let mediaRecorder = null;
let mediaStream = null;
let audioChunks = [];
let sessionId = null;
let recording = false;
let pendingOperationId = null;
let pendingCandidates = [];
let pendingIntent = null;
let pendingSlots = {};

async function bootstrap() {
  const config = await window.overlayAPI.getConfig();
  backendText.textContent = config.backendBaseUrl;
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
  intentText.textContent = result.intent || "unknown";
  stateText.textContent = result.state || "unknown";
  replyText.textContent = result.reply_text || "已处理。";
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
}

async function sendCommand(text) {
  const trimmed = text.trim();
  if (!trimmed) return;

  setBusy("执行中");
  try {
    const result = await window.overlayAPI.callMcpTool("calendar.handle_command", {
      text: trimmed,
      timezone: "Asia/Shanghai",
      locale: "zh-CN",
      session_id: sessionId,
      now: new Date().toISOString(),
    });
    applyAgentResult(result);
    commandInput.value = "";
  } catch (error) {
    replyText.textContent = String(error.message || error);
    resultText.textContent = String(error.message || error);
    intentText.textContent = "error";
    stateText.textContent = "error";
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
    await transcribeAndSend(blob);
  });
  mediaRecorder.start();
  recording = true;
  recordButton.textContent = "停止录音";
  setBusy("录音中");
}

async function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") return;
  mediaRecorder.stop();
  recording = false;
  recordButton.textContent = "语音输入";
  setBusy("转写中");
}

async function transcribeAndSend(blob) {
  try {
    const audioBase64 = await window.overlayAPI.audioToBase64(blob);
    const result = await window.overlayAPI.callMcpTool("voice.handle_command", {
      audio_base64: audioBase64,
      filename: "voice-input.webm",
      content_type: blob.type || "audio/webm",
      timezone: "Asia/Shanghai",
      locale: "zh-CN",
      session_id: sessionId,
      now: new Date().toISOString(),
    });
    transcriptText.textContent = result.transcript || "";
    voiceProvider.textContent = result.asr_provider || "unknown";
    commandInput.value = result.transcript || "";
    applyAgentResult(result);
    setIdle();
  } catch (error) {
    transcriptText.textContent = String(error.message || error);
    voiceProvider.textContent = "error";
    intentText.textContent = "error";
    stateText.textContent = "error";
    replyText.textContent = "语音转写失败";
    resultText.textContent = "语音转写失败";
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
    if (!confirmed) {
      replyText.textContent = result.reply_text || "已取消操作。";
    }
  } catch (error) {
    replyText.textContent = String(error.message || error);
    stateText.textContent = "error";
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
    replyText.textContent = String(error.message || error);
    stateText.textContent = "error";
  } finally {
    setIdle();
  }
}

sendButton.addEventListener("click", async () => {
  await sendCommand(commandInput.value);
});

recordButton.addEventListener("click", async () => {
  if (!recording) {
    await startRecording();
    return;
  }
  await stopRecording();
});

openCalendarButton.addEventListener("click", async () => {
  await window.overlayAPI.openCalendar();
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
  replyText.textContent = String(error.message || error);
  resultText.textContent = String(error.message || error);
});
