import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { CallToolResultSchema } from "@modelcontextprotocol/sdk/types.js";

export class OverlayMcpClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.client = null;
    this.transport = null;
    this.connecting = null;
  }

  async connect() {
    if (this.client) {
      return this.client;
    }
    if (this.connecting) {
      return this.connecting;
    }

    this.connecting = (async () => {
      try {
        const client = new Client(
          {
            name: "voice-calendar-overlay",
            version: "0.1.0",
          },
          {
            capabilities: {},
          },
        );
        const transport = new StreamableHTTPClientTransport(new URL(`${this.baseUrl}/mcp`));
        await client.connect(transport);
        this.client = client;
        this.transport = transport;
        return client;
      } finally {
        this.connecting = null;
      }
    })();

    return this.connecting;
  }

  async callTool(name, args) {
    const client = await this.connect();
    const result = await client.request(
      {
        method: "tools/call",
        params: {
          name,
          arguments: args,
        },
      },
      CallToolResultSchema,
    );

    if (result.structuredContent) {
      return result.structuredContent;
    }
    if (result.content?.length === 1 && result.content[0].type === "text") {
      try {
        return JSON.parse(result.content[0].text);
      } catch (_) {
        return { reply_text: result.content[0].text };
      }
    }
    return result;
  }

  async close() {
    if (this.transport) {
      await this.transport.close();
    }
    this.transport = null;
    this.client = null;
    this.connecting = null;
  }
}
