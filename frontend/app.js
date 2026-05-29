(function () {
  "use strict";

  const state = {
    selectedDate: "2026-05-29",
    timezone: "Asia/Shanghai",
    events: [],
    searchTerm: "",
    calendar: null,
    recognition: null,
    listening: false,
  };

  const hotList = document.querySelector("#hot-list");
  const agendaList = document.querySelector("#agenda-list");
  const agendaTitle = document.querySelector("#agenda-title");
  const agendaCount = document.querySelector("#agenda-count");
  const commandForm = document.querySelector("#command-form");
  const commandInput = document.querySelector("#command-input");
  const assistantReply = document.querySelector("#assistant-reply");
  const voiceState = document.querySelector("#voice-state");
  const voicePanel = document.querySelector("#voice-panel");
  const voiceButton = document.querySelector("#voice-button");
  const voiceCancel = document.querySelector("#voice-cancel");
  const searchButton = document.querySelector("#search-button");
  const hotRefresh = document.querySelector("#hot-refresh");
  const quickAdd = document.querySelector("#quick-add");
  const viewTabs = document.querySelector(".view-tabs");
  const calendarElement = document.querySelector("#calendar");
  const monthPickerToggle = document.querySelector("#month-picker-toggle");
  const monthPicker = document.querySelector("#month-picker");
  const yearInput = document.querySelector("#year-input");
  const monthInput = document.querySelector("#month-input");
  const headingYear = document.querySelector("#heading-year");
  const headingMonth = document.querySelector("#heading-month");

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
      navLinks: false,
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
          multiMonthMinWidth: 130,
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
        markSelectedDate();
        renderAgenda();
      },
      eventClick(info) {
        state.selectedDate = info.event.startStr.slice(0, 10);
        markSelectedDate();
        renderAgenda();
      },
    });

    state.calendar.render();
  }

  function updateHeading(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    headingYear.textContent = String(year);
    headingMonth.textContent = month;
    yearInput.value = String(year);
    monthInput.value = String(Number(month));
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
    return filteredEvents().filter((event) => event.start_at.slice(0, 10) === state.selectedDate);
  }

  function filteredEvents() {
    const keyword = state.searchTerm.trim().toLowerCase();
    if (!keyword) return state.events;
    return state.events.filter((event) => {
      return [
        event.title,
        event.description,
        event.location,
        event.type,
      ].some((value) => String(value || "").toLowerCase().includes(keyword));
    });
  }

  function renderAgenda() {
    const agendaEvents = state.searchTerm ? filteredEvents() : selectedDayEvents();
    agendaTitle.textContent = state.searchTerm ? "搜索结果" : "所选日程";
    agendaCount.textContent = String(agendaEvents.length);
    if (!agendaEvents.length) {
      const emptyLabel = state.searchTerm ? "无匹配日程" : "无日程";
      agendaList.innerHTML = `
        <div class="empty-state">
          <div>
            <div aria-hidden="true" class="brand-mark"><span></span></div>
            <b>${emptyLabel}</b>
          </div>
        </div>
      `;
      return;
    }

    agendaList.innerHTML = agendaEvents.map((event) => {
      const start = formatTime(event.start_at);
      const end = event.end_at ? formatTime(event.end_at) : "";
      const date = formatDate(event.start_at);
      return `
        <article class="agenda-item">
          <b>${escapeHtml(event.title)}</b>
          <p>${event.type === "reminder" ? "提醒" : "日程"}</p>
          <div class="agenda-meta">
            <span>${state.searchTerm ? `${date} ` : ""}${start}${end ? `-${end}` : ""}</span>
            <span>${escapeHtml(event.location || "默认日历")}</span>
          </div>
          <button class="delete-event" type="button" data-event-id="${event.id}">删除</button>
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
    refreshCalendarEvents();
    markSelectedDate();
    renderAgenda();
  }

  function refreshCalendarEvents() {
    state.calendar.removeAllEvents();
    state.calendar.addEventSource(filteredEvents().map(toCalendarEvent));
  }

  function applySearch(term) {
    state.searchTerm = term;
    refreshCalendarEvents();
    markSelectedDate();
    renderAgenda();
    assistantReply.textContent = term ? `已筛选包含“${term}”的日程。` : "已清除日程搜索。";
  }

  function parseSearchTerm(value) {
    return value.trim().replace(/^搜索[:：\s]*/, "").trim();
  }

  function markSelectedDate() {
    if (!state.calendar) return;
    calendarElement.querySelectorAll(".is-selected-date").forEach((cell) => {
      cell.classList.remove("is-selected-date");
    });
    const selector = `.fc-day[data-date="${state.selectedDate}"]`;
    calendarElement.querySelectorAll(selector).forEach((cell) => {
      cell.classList.add("is-selected-date");
    });
  }

  function gotoMonth(year, month) {
    if (!state.calendar) return;
    const normalizedMonth = String(month).padStart(2, "0");
    state.selectedDate = `${year}-${normalizedMonth}-01`;
    state.calendar.gotoDate(state.selectedDate);
    monthPicker.hidden = true;
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
    state.recognition = recognition;
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.continuous = false;

    recognition.addEventListener("start", () => {
      state.listening = true;
      voicePanel.classList.add("is-listening");
      voiceCancel.hidden = false;
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
      state.listening = false;
      voicePanel.classList.remove("is-listening");
      voiceCancel.hidden = true;
      if (voiceState.textContent === "正在聆听") voiceState.textContent = "点击说话";
    });
    recognition.addEventListener("error", () => {
      state.listening = false;
      voicePanel.classList.remove("is-listening");
      voiceCancel.hidden = true;
      voiceState.textContent = "识别失败";
      assistantReply.textContent = "可以再点一次，或直接输入文字。";
    });

    voiceButton.addEventListener("click", () => {
      if (state.listening) {
        recognition.abort();
        voiceState.textContent = "已取消";
        assistantReply.textContent = "语音输入已取消。";
        return;
      }
      recognition.start();
    });
    voiceCancel.addEventListener("click", () => {
      recognition.abort();
      voiceState.textContent = "已取消";
      assistantReply.textContent = "语音输入已取消。";
    });
  }

  function formatTime(value) {
    return new Date(value).toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function formatDate(value) {
    return new Date(value).toLocaleDateString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
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
    const value = commandInput.value.trim();
    if (value.startsWith("搜索")) {
      applySearch(parseSearchTerm(value));
      return;
    }
    sendCommand(value);
  });

  searchButton.addEventListener("click", () => {
    const term = parseSearchTerm(commandInput.value);
    if (term) {
      applySearch(term);
      commandInput.select();
      return;
    }
    commandInput.focus();
  });
  commandInput.addEventListener("input", () => {
    if (!commandInput.value.trim() && state.searchTerm) applySearch("");
  });
  hotRefresh.addEventListener("click", () => loadHotTopics(true));
  agendaList.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-event-id]");
    if (!button) return;
    await fetch(`/api/events/${button.dataset.eventId}`, { method: "DELETE" });
    assistantReply.textContent = "已删除日程。";
    await loadCurrentEvents();
  });
  quickAdd.addEventListener("click", () => {
    commandInput.value = "明天下午三点提醒我开项目会";
    commandInput.focus();
  });
  monthPickerToggle.addEventListener("click", () => {
    monthPicker.hidden = !monthPicker.hidden;
    if (!monthPicker.hidden) yearInput.focus();
  });
  monthPicker.addEventListener("submit", (event) => {
    event.preventDefault();
    gotoMonth(Number(yearInput.value), Number(monthInput.value));
  });

  setupVoice();
  initCalendar();
  loadHotTopics(false).catch(() => {
    assistantReply.textContent = "后端暂不可用，请确认 API 已启动。";
  });
})();
