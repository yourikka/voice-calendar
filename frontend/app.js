(function () {
  "use strict";

  const state = {
    year: 2026,
    month: 4,
    selectedDay: 29,
    timezone: "Asia/Shanghai",
    events: [],
  };

  const lunarLabels = [
    "", "", "", "十七", "青年节", "立夏", "二十", "廿一", "廿二", "廿三",
    "母亲节", "廿五", "廿六", "廿七", "廿八", "廿九", "三十", "四月",
    "初二", "初三", "初四", "小满", "初六", "初七", "初八", "初九",
    "初十", "十一", "十二", "十三", "十四", "十五"
  ];

  const monthGrid = document.querySelector("#month-grid");
  const hotList = document.querySelector("#hot-list");
  const agendaList = document.querySelector("#agenda-list");
  const agendaCount = document.querySelector("#agenda-count");
  const commandForm = document.querySelector("#command-form");
  const commandInput = document.querySelector("#command-input");
  const assistantReply = document.querySelector("#assistant-reply");
  const voiceState = document.querySelector("#voice-state");
  const voicePanel = document.querySelector("#voice-panel");
  const voiceButton = document.querySelector("#voice-button");
  const refreshButton = document.querySelector("#refresh-button");
  const hotRefresh = document.querySelector("#hot-refresh");
  const quickAdd = document.querySelector("#quick-add");

  function isoDate(day) {
    return `2026-05-${String(day).padStart(2, "0")}`;
  }

  function dayRange(day) {
    const date = isoDate(day);
    return {
      start: `${date}T00:00:00+08:00`,
      end: day === 31 ? "2026-06-01T00:00:00+08:00" : `${isoDate(day + 1)}T00:00:00+08:00`,
    };
  }

  function renderCalendar() {
    const firstWeekday = new Date("2026-05-01T00:00:00+08:00").getDay();
    const eventDays = new Set(
      state.events.map((event) => new Date(event.start_at).getDate())
    );
    const cells = [];
    for (let index = 0; index < firstWeekday; index += 1) {
      cells.push("<div></div>");
    }
    for (let day = 1; day <= 31; day += 1) {
      const classes = ["day-cell"];
      if (day === state.selectedDay) classes.push("is-selected");
      if (day === 29) classes.push("is-today");
      if (eventDays.has(day)) classes.push("has-event");
      cells.push(`
        <button class="${classes.join(" ")}" type="button" role="gridcell" data-day="${day}" aria-label="5月${day}日">
          <strong>${day}</strong>
          <small>${lunarLabels[day] || ""}</small>
        </button>
      `);
    }
    monthGrid.innerHTML = cells.join("");
  }

  function renderAgenda() {
    const dayEvents = state.events.filter((event) => {
      return new Date(event.start_at).getDate() === state.selectedDay;
    });
    agendaCount.textContent = String(dayEvents.length);
    if (!dayEvents.length) {
      agendaList.innerHTML = `
        <div class="empty-state">
          <div>
            <div aria-hidden="true" class="brand-mark"><span></span></div>
            <b>无日程</b>
          </div>
        </div>
      `;
      return;
    }
    agendaList.innerHTML = dayEvents.map((event) => {
      const start = new Date(event.start_at).toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      const end = event.end_at
        ? new Date(event.end_at).toLocaleTimeString("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          })
        : "";
      return `
        <article class="agenda-item">
          <b>${escapeHtml(event.title)}</b>
          <p>${event.type === "reminder" ? "提醒" : "日程"}</p>
          <div class="agenda-meta">
            <span>${start}${end ? `-${end}` : ""}</span>
            <span>${escapeHtml(event.location || "默认日历")}</span>
          </div>
        </article>
      `;
    }).join("");
  }

  function renderHotTopics(items) {
    hotList.innerHTML = items.map((item, index) => `
      <article class="hot-item">
        <b>${escapeHtml(item.title)}</b>
        <p>${escapeHtml(item.summary)}</p>
        <div class="hot-meta">
          <span class="hot-rank">#${index + 1}</span>
          <span>${escapeHtml(item.source_name)}</span>
        </div>
      </article>
    `).join("");
  }

  async function loadEvents() {
    const range = {
      start: "2026-05-01T00:00:00+08:00",
      end: "2026-06-01T00:00:00+08:00",
    };
    const response = await fetch(`/api/events?start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}`);
    const data = await response.json();
    state.events = data.items || [];
    renderCalendar();
    renderAgenda();
  }

  async function loadHotTopics(force) {
    if (force) {
      await fetch("/api/news/hot-topics/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: "2026-05-29", timezone: state.timezone }),
      });
    }
    const response = await fetch("/api/calendar/hot-topics?date=2026-05-29&timezone=Asia/Shanghai&limit=5");
    const data = await response.json();
    renderHotTopics(data.items || []);
  }

  async function sendCommand(text) {
    if (!text.trim()) return;
    assistantReply.textContent = "处理中...";
    const response = await fetch("/api/text/commands", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        timezone: state.timezone,
        now: "2026-05-29T10:00:00+08:00",
      }),
    });
    const data = await response.json();
    assistantReply.textContent = data.reply_text || "已处理。";
    commandInput.value = "";
    await Promise.all([loadEvents(), loadHotTopics(false)]);
  }

  function setupVoice() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      voiceState.textContent = "语音不可用";
      assistantReply.textContent = "当前浏览器不支持语音识别，可以直接输入文字。";
      voiceButton.addEventListener("click", () => commandInput.focus());
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.continuous = false;

    recognition.addEventListener("start", () => {
      voicePanel.classList.add("is-listening");
      voiceState.textContent = "正在聆听";
      assistantReply.textContent = "说出你的日程或热点指令。";
    });
    recognition.addEventListener("result", (event) => {
      const transcript = event.results[0][0].transcript;
      voiceState.textContent = "已识别";
      assistantReply.textContent = transcript;
      sendCommand(transcript);
    });
    recognition.addEventListener("end", () => {
      voicePanel.classList.remove("is-listening");
      if (voiceState.textContent === "正在聆听") voiceState.textContent = "点击说话";
    });
    recognition.addEventListener("error", () => {
      voicePanel.classList.remove("is-listening");
      voiceState.textContent = "识别失败";
      assistantReply.textContent = "可以再点一次，或直接输入文字。";
    });

    voiceButton.addEventListener("click", () => recognition.start());
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char]));
  }

  monthGrid.addEventListener("click", (event) => {
    const button = event.target.closest("[data-day]");
    if (!button) return;
    state.selectedDay = Number(button.dataset.day);
    renderCalendar();
    renderAgenda();
  });

  commandForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendCommand(commandInput.value);
  });

  refreshButton.addEventListener("click", () => Promise.all([loadEvents(), loadHotTopics(true)]));
  hotRefresh.addEventListener("click", () => loadHotTopics(true));
  quickAdd.addEventListener("click", () => {
    commandInput.value = "明天下午三点提醒我开项目会";
    commandInput.focus();
  });

  setupVoice();
  renderCalendar();
  Promise.all([loadEvents(), loadHotTopics(false)]).catch(() => {
    assistantReply.textContent = "后端暂不可用，请确认 API 已启动。";
  });
})();
