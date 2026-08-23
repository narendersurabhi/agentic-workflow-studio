import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import WorkflowStudio from "./WorkflowStudio";
import { ShellProvider } from "../../lib/shell";
import { AppQueryProvider } from "../../lib/queryClient";

const searchParams = new URLSearchParams({ definition: "def-1" });

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/studio",
  useSearchParams: () => searchParams,
}));

function jsonResponse(body: unknown, init?: { status?: number }) {
  return {
    ok: (init?.status ?? 200) < 400,
    status: init?.status ?? 200,
    headers: { get: () => null },
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

const DEFINITION = {
  id: "def-1",
  title: "Weekly Report Pipeline",
  goal: "Generate the weekly report",
  context_json: {},
  draft: {
    goal: "Generate the weekly report",
    summary: "Weekly Report Pipeline",
    nodes: [
      {
        id: "node-1",
        taskName: "Fetch Source Data",
        capabilityId: "data.fetch",
        nodeKind: "capability",
      },
    ],
    edges: [],
  },
  metadata: {},
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

function renderStudio() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();

    if (/\/workflows\/definitions(\?.*)?$/.test(url)) {
      return jsonResponse([]);
    }
    if (/\/workflows\/definitions\/def-1$/.test(url)) {
      return jsonResponse(DEFINITION);
    }
    return jsonResponse({});
  });

  vi.stubGlobal("fetch", fetchMock);

  return render(
    <AppQueryProvider>
      <ShellProvider>
        <WorkflowStudio />
      </ShellProvider>
    </AppQueryProvider>,
  );
}

describe("WorkflowStudio", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads a workflow definition from the URL and renders its node on the canvas", async () => {
    renderStudio();

    expect(await screen.findByText("Fetch Source Data")).toBeInTheDocument();
  });
});
