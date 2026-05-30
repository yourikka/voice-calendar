(function () {
  "use strict";

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

  function getNthWeekdayOfMonth(year, month, weekday, nth) {
    const first = new Date(`${year}-${String(month).padStart(2, "0")}-01T12:00:00+08:00`);
    const firstWeekday = first.getUTCDay();
    const offset = (weekday - firstWeekday + 7) % 7;
    const day = 1 + offset + ((nth - 1) * 7);
    return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
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

  window.voiceCalendarDateUtils = {
    formatDateKey,
    getChineseCalendarInfo,
    getCustomFestival,
    getNthWeekdayOfMonth,
    getShanghaiDateParts,
  };
})();
