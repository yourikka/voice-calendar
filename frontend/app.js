(function () {
  "use strict";

  const state = {
    selectedDate: "2026-05-29",
    timezone: "Asia/Shanghai",
    events: [],
    calendar: null,
  };

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
  const viewTabs = document.querySelector(".view-tabs");
  const calendarElement = document.querySelector("#calendar");

  function initCalendar() {
    if (!window.FullCalendar) {
      assistantReply.textContent = "日历组件加载失败，请检查网络。";
      return;
    }

    state.calendar = new window.FullCalendar.Calendar(calendarElement, {
      locale: "zh-cn",
      timeZone: "Asia/Shanghai",
      initialDate: state.selectedDate,
      initialView: "dayGridMonth",
      headerToolbar: false,
      height: "auto",
      firstDay: 0,
      navLinks: true,
      nowIndicator: true,
      dayMaxEvents: 3,
      selectable: true,
      allDaySlot: false,
      dayCellContent(info) {
        return { html: `<span>${info.date.getDate()}</span>` };
      },
      slotMinTime: "07:00:00",
      slotMaxTime: "23:00:00",
      views: {
        multiMonthYear: {
          type: "multiMonth",
          duration: { years: 1 },
          multiMonthMaxColumns: 3,
        },
        listMonth: {
          buttonText: "日程",
        },
      },
      datesSet(info) {
        updateHeading(info.view.currentStart);
        updateActiveTab(info.view.type);
        loadEventsForRange(info.startStr, info.endStr);
      },
      dateClick(info) {
        state.selectedDate = info.dateStr.slice(0, 10);
        renderAgenda();
      },
      eventClick(info) {
        state.selectedDate = info.event.startStr.slice(0, 10);
        renderAgenda();
      },
    });

    state.calendar.render();
  }

  function updateHeading(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const heading = document.querySelector("#calendar-title");
    heading.innerHTML = `<span>${year}</span><i>/</i><strong>${month}</strong>`;
  }

  function updateActiveTab(viewType) {
    viewTabs.querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-selected", String(button.dataset.view === viewType));
    });
  }

  function toCalendarEvent(event) {
    return {
      id: event.id,
      title: event.title,
      start: event.start_at,
      end: event.end_at,
      allDay: event.type === "reminder" && !event.end_at,
      classNames: [`event-${event.type}`],
      extendedProps: event,
    };
  }

  function selectedDayEvents() {
    return state.events.filter((event) => event.start_at.slice(0, 10) === state.selectedDate);
  }

  function renderAgenda() {
    const dayEvents = selectedDayEvents();
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
      const start = formatTime(event.start_at);
      const end = event.end_at ? formatTime(event.end_at) : "";
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

  async function loadEventsForRange(start, end) {
    const response = await fetch(`/api/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
    const data = await response.json();
    state.events = data.items || [];
    state.calendar.removeAllEvents();
    state.calendar.addEventSource(state.events.map(toCalendarEvent));
    renderAgenda();
  }

  async function loadCurrentEvents() {
    if (!state.calendar) return;
    const view = state.calendar.view;
    await loadEventsForRange(toApiDateTime(view.activeStart), toApiDateTime(view.activeEnd));
  }

  async function loadHotTopics(force) {
    if (force) {
      await fetch("/api/news/hot-topics/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: state.selectedDate, timezone: state.timezone }),
      });
    }
    const response = await fetch(`/api/calendar/hot-topics?date=${state.selectedDate}&timezone=Asia/Shanghai&limit=5`);
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
    await Promise.all([loadCurrentEvents(), loadHotTopics(false)]);
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

  function formatTime(value) {
    return new Date(value).toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function toApiDateTime(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hour = String(date.getHours()).padStart(2, "0");
    const minute = String(date.getMinutes()).padStart(2, "0");
    const second = String(date.getSeconds()).padStart(2, "0");
    return `${year}-${month}-${day}T${hour}:${minute}:${second}+08:00`;
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

  viewTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (!button || !state.calendar) return;
    state.calendar.changeView(button.dataset.view);
  });

  commandForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendCommand(commandInput.value);
  });

  refreshButton.addEventListener("click", () => Promise.all([loadCurrentEvents(), loadHotTopics(true)]));
  hotRefresh.addEventListener("click", () => loadHotTopics(true));
  quickAdd.addEventListener("click", () => {
    commandInput.value = "明天下午三点提醒我开项目会";
    commandInput.focus();
  });

  setupVoice();
  initCalendar();
  loadHotTopics(false).catch(() => {
    assistantReply.textContent = "后端暂不可用，请确认 API 已启动。";
  });
})();
