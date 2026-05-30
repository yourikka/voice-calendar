(function () {
  "use strict";

  const state = {
    selectedDate: new Intl.DateTimeFormat("sv-SE", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date()),
    timezone: "Asia/Shanghai",
    events: [],
    dayMetaByDate: {},
    searchTerm: "",
    sessionId: null,
    calendar: null,
    recognition: null,
    listening: false,
    mediaRecorder: null,
    mediaStream: null,
    audioChunks: [],
    recording: false,
    recordingCancelled: false,
    pendingVoiceRequest: null,
    voiceMode: "none",
    voiceCapabilities: null,
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
  const headingDivider = monthPickerToggle.querySelector("i");
  const yearLegend = document.querySelector("#year-legend");
  const yearLegendLeft = document.querySelector("#year-legend-left");
  const yearLegendRight = document.querySelector("#year-legend-right");
  const lunarSummary = document.querySelector("#lunar-summary");

  const lunarDayLabels = {
    1: "初一",
    2: "初二",
    3: "初三",
    4: "初四",
    5: "初五",
    6: "初六",
    7: "初七",
    8: "初八",
    9: "初九",
    10: "初十",
    11: "十一",
    12: "十二",
    13: "十三",
    14: "十四",
    15: "十五",
    16: "十六",
    17: "十七",
    18: "十八",
    19: "十九",
    20: "二十",
    21: "廿一",
    22: "廿二",
    23: "廿三",
    24: "廿四",
    25: "廿五",
    26: "廿六",
    27: "廿七",
    28: "廿八",
    29: "廿九",
    30: "三十",
  };

  const zodiacByBranch = {
    "子": "鼠",
    "丑": "牛",
    "寅": "虎",
    "卯": "兔",
    "辰": "龙",
    "巳": "蛇",
    "午": "马",
    "未": "羊",
    "申": "猴",
    "酉": "鸡",
    "戌": "狗",
    "亥": "猪",
  };

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
        return info.view.type === "multiMonthYear"
          ? { html: `${info.date.getDate()}` }
          : { html: `<span>${info.date.getDate()}</span>` };
      },
      dayCellDidMount(info) {
        decorateDayCell(info);
      },
      dayHeaderContent(info) {
        if (info.view.type === "dayGridMonth" || info.view.type === "multiMonthYear") {
          return info.text.replace(/^周/, "");
        }
        return info.text;
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
        timeGridWeek: {
          firstDay: 1,
        },
        listMonth: {
          buttonText: "日程",
        },
      },
      datesSet(info) {
        const visibleStart = info.startStr.slice(0, 10);
        const visibleEnd = info.endStr.slice(0, 10);
        if (info.view.type === "timeGridDay") {
          state.selectedDate = dateKeyFromViewDate(info.view.currentStart);
        } else if (!isDateWithinRange(state.selectedDate, visibleStart, visibleEnd)) {
          state.selectedDate = visibleStart;
        }
        syncViewChrome(info.view.type, info.view.currentStart);
        updateActiveTab(info.view.type);
        loadViewData(info.startStr, info.endStr);
        markSelectedDate();
      },
      dateClick(info) {
        if (info.view.type === "multiMonthYear") {
          openMonthView(info.dateStr.slice(0, 10));
          return;
        }
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

  function getShanghaiDateParts(date) {
    const shifted = new Date(date.getTime() + (8 * 60 * 60 * 1000));
    return {
      year: shifted.getUTCFullYear(),
      month: shifted.getUTCMonth() + 1,
      day: shifted.getUTCDate(),
    };
  }

  function formatDateKey(date) {
    const parts = getShanghaiDateParts(date);
    return `${parts.year}-${String(parts.month).padStart(2, "0")}-${String(parts.day).padStart(2, "0")}`;
  }

  function getChineseCalendarInfo(dateKey) {
    const date = new Date(`${dateKey}T12:00:00+08:00`);
    const formatted = new Intl.DateTimeFormat("zh-CN-u-ca-chinese", {
      year: "numeric",
      month: "long",
      day: "numeric",
    }).format(date);
    const match = formatted.match(/^(\d+)(.+?)年(.+?)(\d+)$/);
    if (!match) {
      return {
        cyclicalYear: "丙午",
        monthLabel: "四月",
        dayLabel: "十三",
        zodiac: "马",
      };
    }
    const cyclicalYear = match[2];
    const monthLabel = match[3];
    const dayLabel = lunarDayLabels[Number(match[4])] || match[4];
    const zodiac = zodiacByBranch[cyclicalYear.slice(-1)] || "马";
    return { cyclicalYear, monthLabel, dayLabel, zodiac };
  }

  function getMonthCellMeta(dateKey) {
    const lunar = getChineseCalendarInfo(dateKey);
    const remoteMeta = state.dayMetaByDate[dateKey] || {};
    const customFestival = getCustomFestival(dateKey);
    return {
      badge: remoteMeta.is_holiday ? "休" : (remoteMeta.is_adjusted_workday ? "班" : ""),
      dot: hasEventsOnDate(dateKey),
      isFestival: Boolean(remoteMeta.solar_term || customFestival.label || remoteMeta.holiday_name),
      label: remoteMeta.solar_term
        || customFestival.label
        || remoteMeta.holiday_name
        || (lunar.dayLabel === "初一" ? lunar.monthLabel : lunar.dayLabel),
    };
  }

  function getCustomFestival(dateKey) {
    const [yearText, monthText, dayText] = dateKey.split("-");
    const year = Number(yearText);
    const month = Number(monthText);
    const day = Number(dayText);
    if (month === 5 && day === 4) return { label: "青年节" };
    if (month === 5 && dateKey === getNthWeekdayOfMonth(year, 5, 0, 2)) {
      return { label: "母亲节" };
    }
    return { label: "" };
  }

  function hasEventsOnDate(dateKey) {
    return state.events.some((event) => event.start_at.slice(0, 10) === dateKey);
  }

  function getNthWeekdayOfMonth(year, month, weekday, nth) {
    const first = new Date(`${year}-${String(month).padStart(2, "0")}-01T12:00:00+08:00`);
    const firstWeekday = first.getUTCDay();
    const offset = (weekday - firstWeekday + 7) % 7;
    const day = 1 + offset + ((nth - 1) * 7);
    return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }

  function syncViewChrome(viewType, date) {
    updateHeading(viewType, date);
    updateYearLegend(viewType);
    decorateYearView();
    updateLunarSummary();
    document.body.dataset.calendarView = viewType;
  }

  function updateHeading(viewType, date) {
    const { year, month } = getShanghaiDateParts(date);
    const yearText = String(year);
    const monthText = String(month).padStart(2, "0");
    if (viewType === "multiMonthYear") {
      headingYear.textContent = yearText.slice(0, 2);
      headingMonth.textContent = yearText.slice(2);
      headingDivider.hidden = true;
    } else {
      headingYear.textContent = yearText;
      headingMonth.textContent = monthText;
      headingDivider.hidden = false;
      headingDivider.textContent = "/";
    }
    yearInput.value = yearText;
    monthInput.value = String(Number(monthText));
  }

  function updateYearLegend(viewType) {
    const lunar = getChineseCalendarInfo(state.selectedDate);
    yearLegend.hidden = viewType !== "multiMonthYear";
    yearLegendLeft.textContent = `一 ${lunar.cyclicalYear}${lunar.zodiac}年`;
    yearLegendRight.textContent = "一 农历初一";
  }

  function updateLunarSummary() {
    const lunar = getChineseCalendarInfo(state.selectedDate);
    const remoteMeta = state.dayMetaByDate[state.selectedDate] || {};
    const suffix = remoteMeta.solar_term ? ` ${remoteMeta.solar_term}` : "";
    lunarSummary.textContent = `${lunar.monthLabel}${lunar.dayLabel} ${lunar.cyclicalYear}年 [${lunar.zodiac}]${suffix}`;
  }

  function decorateDayCell(info) {
    decorateDayCellElement(info.el, info.view.type, info.isOther, formatDateKey(info.date));
  }

  function decorateYearView() {
    requestAnimationFrame(() => {
      if (!state.calendar || state.calendar.view.type !== "multiMonthYear") return;
      const currentMonth = state.selectedDate.slice(5, 7);
      calendarElement.querySelectorAll(".fc-multimonth-month").forEach((monthElement) => {
        const title = monthElement.querySelector(".fc-multimonth-title");
        const monthDate = monthElement.dataset.date;
        if (!title || !monthDate) return;
        const monthText = monthDate.slice(5, 7);
        title.dataset.month = monthText;
        monthElement.classList.toggle("is-current-month", monthText === currentMonth);
      });
    });
  }

  function decorateVisibleDayCells() {
    if (!state.calendar) return;
    const viewType = state.calendar.view.type;
    calendarElement.querySelectorAll(".fc-daygrid-day[data-date]").forEach((cell) => {
      decorateDayCellElement(
        cell,
        viewType,
        cell.classList.contains("fc-day-other"),
        cell.dataset.date,
      );
    });
  }

  function decorateDayCellElement(cell, viewType, isOther, dateKey) {
    const frame = cell.querySelector(".fc-daygrid-day-frame");
    if (!frame) return;
    frame.querySelectorAll(".month-cell-meta, .month-cell-status").forEach((node) => node.remove());
    if (viewType !== "dayGridMonth" || isOther) return;
    const meta = getMonthCellMeta(dateKey);
    if (meta.badge) {
      const status = document.createElement("span");
      status.className = `month-cell-status ${meta.badge === "班" ? "is-work" : "is-rest"}`;
      status.textContent = meta.badge;
      frame.append(status);
    }
    const detail = document.createElement("div");
    detail.className = `month-cell-meta ${meta.isFestival ? "is-festival" : ""}`;
    detail.innerHTML = `
      <span class="month-cell-text">${meta.label}</span>
      ${meta.dot ? '<span class="month-cell-dot" aria-hidden="true"></span>' : ""}
    `;
    frame.insertBefore(detail, frame.querySelector(".fc-daygrid-day-events"));
  }

  function updateActiveTab(viewType) {
    viewTabs.querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-selected", String(button.dataset.view === viewType));
    });
  }

  function firstDayForView(viewType) {
    return viewType === "timeGridWeek" ? 1 : 0;
  }

  function dateKeyFromViewDate(date) {
    return formatDateKey(date);
  }

  function isDateWithinRange(dateKey, start, end) {
    return dateKey >= start.slice(0, 10) && dateKey < end.slice(0, 10);
  }

  function changeCalendarView(viewType, dateText) {
    if (!state.calendar) return;
    state.calendar.setOption("firstDay", firstDayForView(viewType));
    const targetDate = dateText || state.selectedDate;
    state.calendar.changeView(viewType, targetDate);
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
    decorateVisibleDayCells();
    markSelectedDate();
    renderAgenda();
  }

  async function loadCalendarMetaForRange(start, end) {
    const response = await fetch(
      `/api/calendar/meta?start=${encodeURIComponent(start.slice(0, 10))}&end=${encodeURIComponent(end.slice(0, 10))}`,
    );
    const data = await response.json();
    state.dayMetaByDate = Object.fromEntries((data.items || []).map((item) => [item.date, item]));
    decorateVisibleDayCells();
    updateLunarSummary();
    updateYearLegend(state.calendar?.view.type || "dayGridMonth");
  }

  async function loadViewData(start, end) {
    await Promise.all([
      loadEventsForRange(start, end),
      loadCalendarMetaForRange(start, end),
    ]);
  }

  function refreshCalendarEvents() {
    state.calendar.removeAllEvents();
    state.calendar.addEventSource(filteredEvents().map(toCalendarEvent));
  }

  function applySearch(term) {
    state.searchTerm = term;
    refreshCalendarEvents();
    decorateVisibleDayCells();
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
    const selector = [
      `.fc-daygrid-day[data-date="${state.selectedDate}"]`,
      `.fc-timegrid-col[data-date="${state.selectedDate}"]`,
      `.fc-timegrid-axis-cushion[data-date="${state.selectedDate}"]`,
    ].join(", ");
    calendarElement.querySelectorAll(selector).forEach((cell) => {
      cell.classList.add("is-selected-date");
    });
    updateLunarSummary();
  }

  function openMonthView(dateText) {
    if (!state.calendar) return;
    state.selectedDate = dateText;
    changeCalendarView("dayGridMonth", dateText);
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
    const response = await fetch(
      `/api/calendar/hot-topics?date=${state.selectedDate}&timezone=${encodeURIComponent(state.timezone)}&limit=5`,
    );
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
        session_id: state.sessionId,
        now: new Date().toISOString(),
      }),
    });
    const data = await response.json();
    if (data.session_id) state.sessionId = data.session_id;
    assistantReply.textContent = data.reply_text || "已处理。";
    commandInput.value = "";
    await Promise.all([loadCurrentEvents(), loadHotTopics(false)]);
  }

  function resetVoicePanel(defaultLabel) {
    voicePanel.classList.remove("is-listening");
    voiceCancel.hidden = true;
    if (defaultLabel) voiceState.textContent = defaultLabel;
  }

  function stopMediaStream() {
    if (!state.mediaStream) return;
    state.mediaStream.getTracks().forEach((track) => track.stop());
    state.mediaStream = null;
  }

  function setupBrowserRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

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
      if (!state.pendingVoiceRequest && !state.recording) resetVoicePanel("点击说话");
    });
    recognition.addEventListener("error", () => {
      state.listening = false;
      resetVoicePanel("识别失败");
      assistantReply.textContent = "可以再点一次，或直接输入文字。";
    });
  }

  async function loadVoiceCapabilities() {
    try {
      const response = await fetch("/api/voice/capabilities");
      if (!response.ok) throw new Error("capabilities");
      const data = await response.json();
      state.voiceCapabilities = data;
      return data;
    } catch (_) {
      const fallback = { server_asr_available: false, browser_fallback_recommended: true };
      state.voiceCapabilities = fallback;
      return fallback;
    }
  }

  function describeVoiceCapabilities(capabilities) {
    if (!capabilities?.server_asr_available) {
      return "后端 ASR 不可用。";
    }
    if (capabilities.ready) {
      return "语音模型已就绪。";
    }
    if (capabilities.warming) {
      return "语音模型预热中，首次识别会稍慢。";
    }
    return capabilities.detail || "语音模型可用，首次点击录音会触发加载。";
  }

  function encodeWavBlob(audioBuffer) {
    const channels = audioBuffer.numberOfChannels;
    const sampleRate = audioBuffer.sampleRate;
    const source = [];
    for (let channel = 0; channel < channels; channel += 1) {
      source.push(audioBuffer.getChannelData(channel));
    }
    const frameCount = audioBuffer.length;
    const pcm = new Int16Array(frameCount);
    for (let index = 0; index < frameCount; index += 1) {
      let sample = 0;
      for (let channel = 0; channel < channels; channel += 1) {
        sample += source[channel][index];
      }
      sample /= channels;
      const clipped = Math.max(-1, Math.min(1, sample));
      pcm[index] = clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff;
    }

    const buffer = new ArrayBuffer(44 + (pcm.length * 2));
    const view = new DataView(buffer);
    const writeAscii = (offset, value) => {
      for (let index = 0; index < value.length; index += 1) {
        view.setUint8(offset + index, value.charCodeAt(index));
      }
    };

    writeAscii(0, "RIFF");
    view.setUint32(4, 36 + (pcm.length * 2), true);
    writeAscii(8, "WAVE");
    writeAscii(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeAscii(36, "data");
    view.setUint32(40, pcm.length * 2, true);
    pcm.forEach((sample, index) => {
      view.setInt16(44 + (index * 2), sample, true);
    });
    return new Blob([buffer], { type: "audio/wav" });
  }

  async function prepareVoiceUpload(blob, mimeType) {
    const resolvedType = mimeType || blob.type || "application/octet-stream";
    if (resolvedType === "audio/wav") {
      return { blob, mimeType: "audio/wav", filename: "voice-input.wav" };
    }

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      return { blob, mimeType: resolvedType, filename: "voice-input.webm" };
    }

    const audioContext = new AudioContextClass();
    try {
      const arrayBuffer = await blob.arrayBuffer();
      const decoded = await audioContext.decodeAudioData(arrayBuffer.slice(0));
      return {
        blob: encodeWavBlob(decoded),
        mimeType: "audio/wav",
        filename: "voice-input.wav",
      };
    } catch (_) {
      return { blob, mimeType: resolvedType, filename: "voice-input.webm" };
    } finally {
      await audioContext.close();
    }
  }

  async function sendVoiceAudio(blob, mimeType) {
    const controller = new AbortController();
    const upload = await prepareVoiceUpload(blob, mimeType);
    const formData = new FormData();
    formData.append("audio", new File([upload.blob], upload.filename, { type: upload.mimeType }));
    formData.append("timezone", state.timezone);
    formData.append("locale", "zh-CN");
    if (state.sessionId) formData.append("session_id", state.sessionId);
    formData.append("now", new Date().toISOString());
    state.pendingVoiceRequest = controller;
    voicePanel.classList.add("is-listening");
    voiceCancel.hidden = false;
    voiceState.textContent = "识别中";
    assistantReply.textContent = "正在转写语音...";

    try {
      const response = await fetch("/api/voice/commands", {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "语音处理失败。");
      if (data.session_id) state.sessionId = data.session_id;
      state.voiceCapabilities = {
        ...(state.voiceCapabilities || {}),
        server_asr_available: true,
        ready: true,
        warming: false,
        detail: "语音模型已就绪。",
      };
      voiceState.textContent = "已识别";
      assistantReply.textContent = data.state === "unsupported" && data.transcript
        ? `暂时无法理解。识别到的内容是：${data.transcript}`
        : (data.reply_text || data.transcript || "已处理。");
      commandInput.value = data.transcript || "";
      await Promise.all([loadCurrentEvents(), loadHotTopics(false)]);
    } catch (error) {
      if (controller.signal.aborted) {
        voiceState.textContent = "已取消";
        assistantReply.textContent = "语音输入已取消。";
      } else {
        resetVoicePanel(state.voiceMode === "server" ? "点击录音" : "点击说话");
        assistantReply.textContent = error.message || "语音处理失败。";
      }
    } finally {
      state.pendingVoiceRequest = null;
      if (voiceState.textContent !== "已取消") {
        resetVoicePanel(state.voiceMode === "server" ? "点击录音" : "点击说话");
      } else {
        voicePanel.classList.remove("is-listening");
        voiceCancel.hidden = true;
      }
    }
  }

  async function startServerRecording() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      throw new Error("当前浏览器不支持录音上传。");
    }
    state.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    state.audioChunks = [];
    state.recordingCancelled = false;
    state.recording = true;
    state.mediaRecorder = new MediaRecorder(state.mediaStream);
    state.mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data && event.data.size) state.audioChunks.push(event.data);
    });
    state.mediaRecorder.addEventListener("stop", async () => {
      const mimeType = state.mediaRecorder?.mimeType || "audio/webm";
      const chunks = state.audioChunks.slice();
      const cancelled = state.recordingCancelled;
      state.audioChunks = [];
      state.mediaRecorder = null;
      state.recording = false;
      stopMediaStream();
      if (cancelled || !chunks.length) return;
      await sendVoiceAudio(new Blob(chunks, { type: mimeType }), mimeType);
    });
    state.mediaRecorder.start();
    voicePanel.classList.add("is-listening");
    voiceCancel.hidden = false;
    voiceState.textContent = "录音中";
    assistantReply.textContent = "再次点击语音球完成录音，或点取消丢弃。";
  }

  function finishServerRecording() {
    if (!state.mediaRecorder || state.mediaRecorder.state === "inactive") return;
    voiceState.textContent = "上传中";
    assistantReply.textContent = "正在上传语音...";
    state.mediaRecorder.stop();
  }

  function cancelCurrentVoice() {
    if (state.pendingVoiceRequest) {
      state.pendingVoiceRequest.abort();
      return;
    }
    if (state.recording) {
      state.recordingCancelled = true;
      if (state.mediaRecorder && state.mediaRecorder.state !== "inactive") {
        state.mediaRecorder.stop();
      }
      stopMediaStream();
      resetVoicePanel(state.voiceMode === "server" ? "点击录音" : "点击说话");
      voiceState.textContent = "已取消";
      assistantReply.textContent = "语音输入已取消。";
      return;
    }
    if (state.listening && state.recognition) {
      state.recognition.abort();
      voiceState.textContent = "已取消";
      assistantReply.textContent = "语音输入已取消。";
    }
  }

  async function handleVoiceButtonClick() {
    if (state.pendingVoiceRequest) {
      cancelCurrentVoice();
      return;
    }

    if (state.voiceMode === "server") {
      if (state.recording) {
        finishServerRecording();
        return;
      }
      try {
        await startServerRecording();
      } catch (error) {
        if (state.recognition) {
          state.voiceMode = "browser";
          voiceState.textContent = "点击说话";
          assistantReply.textContent = "后端录音不可用，已切回浏览器语音识别。";
          state.recognition.start();
          return;
        }
        voiceState.textContent = "语音不可用";
        assistantReply.textContent = error.message || "当前环境无法使用语音。";
      }
      return;
    }

    if (state.voiceMode === "browser" && state.recognition) {
      if (state.listening) {
        cancelCurrentVoice();
        return;
      }
      state.recognition.start();
      return;
    }

    commandInput.focus();
  }

  async function setupVoice() {
    setupBrowserRecognition();
    const capabilities = await loadVoiceCapabilities();
    const canRecord = Boolean(window.MediaRecorder && navigator.mediaDevices?.getUserMedia);

    if (capabilities.server_asr_available && canRecord) {
      state.voiceMode = "server";
      voiceState.textContent = capabilities.ready ? "点击录音" : (capabilities.warming ? "语音预热中" : "点击录音");
      assistantReply.textContent = describeVoiceCapabilities(capabilities);
      if (capabilities.warming && !capabilities.ready) {
        window.setTimeout(() => {
          loadVoiceCapabilities().then((latest) => {
            if (state.voiceMode === "server") {
              voiceState.textContent = latest.ready ? "点击录音" : "语音预热中";
              assistantReply.textContent = describeVoiceCapabilities(latest);
            }
          });
        }, 4000);
      }
      return;
    }
    if (state.recognition) {
      state.voiceMode = "browser";
      voiceState.textContent = "点击说话";
      assistantReply.textContent = capabilities.server_asr_available
        ? `${describeVoiceCapabilities(capabilities)} 当前浏览器不支持录音上传，已切换到浏览器语音识别。`
        : "后端 ASR 未配置，当前使用浏览器语音识别。";
      return;
    }
    state.voiceMode = "none";
    voiceState.textContent = "语音不可用";
    assistantReply.textContent = "当前环境不支持语音输入，可以直接输入文字。";
  }

  function formatTime(value) {
    const date = new Date(value);
    return date.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: date.getSeconds() ? "2-digit" : undefined,
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
    changeCalendarView(button.dataset.view);
  });

  calendarElement.addEventListener("click", (event) => {
    const title = event.target.closest(".fc-multimonth-title");
    if (!title || !state.calendar || state.calendar.view.type !== "multiMonthYear") return;
    const month = title.closest(".fc-multimonth-month");
    const monthDate = month?.dataset.date;
    if (!monthDate) return;
    openMonthView(`${monthDate}-01`);
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
  voiceButton.addEventListener("click", () => {
    handleVoiceButtonClick();
  });
  voiceCancel.addEventListener("click", () => {
    cancelCurrentVoice();
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

  async function bootstrap() {
    initCalendar();
    await setupVoice();
    await loadHotTopics(false);
  }

  bootstrap().catch(() => {
    assistantReply.textContent = "后端暂不可用，请确认 API 已启动。";
  });
})();
