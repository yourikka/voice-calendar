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

let mediaRecorder = null;
let mediaStream = null;
let audioChunks = [];
let sessionId = null;
let recording = false;

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
    sessionId = result.session_id || sessionId;
    intentText.textContent = result.intent || "unknown";
    resultText.textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    resultText.textContent = String(error.message || error);
    intentText.textContent = "error";
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
    const response = await window.overlayAPI.transcribeAudio(blob, "zh-CN");
    transcriptText.textContent = response.transcript || "";
    voiceProvider.textContent = response.asr_provider || "unknown";
    commandInput.value = response.transcript || "";
    await sendCommand(response.transcript || "");
  } catch (error) {
    transcriptText.textContent = String(error.message || error);
    voiceProvider.textContent = "error";
    intentText.textContent = "error";
    resultText.textContent = "语音转写失败";
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

bootstrap().catch((error) => {
  backendText.textContent = "连接失败";
  resultText.textContent = String(error.message || error);
});
