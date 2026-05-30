import { OverlayMcpClient } from "../mcpClient.mjs";

const client = new OverlayMcpClient(process.env.VOICE_CALENDAR_MCP_BASE || "http://127.0.0.1:8001");

try {
  const result = await client.callTool("calendar.handle_command", {
    text: "明早八点提醒我带身份证",
    timezone: "Asia/Shanghai",
    locale: "zh-CN",
    now: "2026-05-29T10:00:00+08:00",
  });
  console.log(JSON.stringify(result, null, 2));
} finally {
  await client.close();
}
