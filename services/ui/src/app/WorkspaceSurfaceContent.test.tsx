import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { WorkspaceSurfaceContent } from "./WorkspaceSurfaceContent";
import { ShellProvider } from "./lib/shell";

class FakeEventSource {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  close() {}
}

function jsonResponse(body: unknown, init?: { status?: number }) {
  return {
    ok: (init?.status ?? 200) < 400,
    status: init?.status ?? 200,
    headers: { get: () => null },
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

function sseResponse(events: Array<Record<string, unknown>>) {
  const encoder = new TextEncoder();
  const chunks = events.map((event) => encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
  let index = 0;
  return {
    ok: true,
    status: 200,
    headers: { get: () => null },
    text: async () => "",
    json: async () => ({}),
    body: {
      getReader: () => ({
        read: async () => {
          if (index < chunks.length) {
            return { done: false, value: chunks[index++] };
          }
          return { done: true, value: undefined };
        },
      }),
    },
  };
}

const SESSION_ID = "session-1";

function renderChatScreen() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();

    if (url.endsWith("/jobs") && method === "GET") {
      return jsonResponse([]);
    }
    if (url.includes("/capabilities?with_schemas=true")) {
      return jsonResponse({ mode: "enforce", items: [] });
    }
    if (url.includes("/skills?owner_id=default") && method === "GET") {
      return jsonResponse([]);
    }
    if (url.endsWith("/chat/sessions") && method === "POST") {
      return jsonResponse({
        id: SESSION_ID,
        title: "New chat",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        metadata: {},
        active_job_id: null,
        messages: [],
      });
    }
    if (url.includes(`/chat/sessions/${SESSION_ID}/messages/stream`) && method === "POST") {
      const now = new Date().toISOString();
      return sseResponse([
        {
          type: "done",
          session: {
            id: SESSION_ID,
            title: "New chat",
            created_at: now,
            updated_at: now,
            metadata: {},
            active_job_id: null,
            messages: [
              {
                id: "msg-user-1",
                session_id: SESSION_ID,
                role: "user",
                content: "Hello there, can you help?",
                created_at: now,
              },
              {
                id: "msg-assistant-1",
                session_id: SESSION_ID,
                role: "assistant",
                content: "Sure — happy to help with that workflow.",
                created_at: now,
              },
            ],
          },
        },
      ]);
    }
    // Non-fatal background calls (feedback lookups, etc.) — respond emptily.
    return jsonResponse({});
  });

  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", FakeEventSource);

  const utils = render(
    <ShellProvider>
      <WorkspaceSurfaceContent screen="chat" />
    </ShellProvider>,
  );
  return { ...utils, fetchMock };
}

describe("WorkspaceSurfaceContent (chat screen)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends a message and renders the assistant's reply", async () => {
    const user = userEvent.setup();
    renderChatScreen();

    const composer = await screen.findByPlaceholderText(
      "Ask for work in natural language. Type / for Skills. Cmd/Ctrl+Enter sends.",
    );
    await user.type(composer, "Hello there, can you help?");

    const sendButton = screen.getByRole("button", { name: "Send" });
    await user.click(sendButton);

    expect(await screen.findByText("Sure — happy to help with that workflow.")).toBeInTheDocument();
    expect(screen.getByText("Hello there, can you help?")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    });
  });
});
