(function () {
  "use strict";

  async function getJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    return data;
  }

  window.voiceCalendarApi = {
    listEvents(start, end) {
      return getJson(`/api/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
    },
    listCalendarMeta(start, end) {
      return getJson(
        `/api/calendar/meta?start=${encodeURIComponent(start.slice(0, 10))}&end=${encodeURIComponent(end.slice(0, 10))}`,
      );
    },
    refreshHotTopics(date, timezone) {
      return getJson("/api/news/hot-topics/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date, timezone }),
      });
    },
    getHotTopicPanel(date, timezone, limit = 5) {
      return getJson(
        `/api/calendar/hot-topics?date=${date}&timezone=${encodeURIComponent(timezone)}&limit=${limit}`,
      );
    },
    handleTextCommand(payload) {
      return getJson("/api/text/commands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    },
    getVoiceCapabilities() {
      return getJson("/api/voice/capabilities");
    },
    handleVoiceCommand(formData, signal) {
      return getJson("/api/voice/commands", {
        method: "POST",
        body: formData,
        signal,
      });
    },
    deleteEvent(eventId) {
      return fetch(`/api/events/${eventId}`, { method: "DELETE" });
    },
  };
})();
