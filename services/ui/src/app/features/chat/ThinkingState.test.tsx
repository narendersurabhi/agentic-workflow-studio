import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ThinkingState } from "./ThinkingState";

describe("ThinkingState", () => {
  it("renders the assistant thinking indicator", () => {
    render(<ThinkingState />);
    expect(screen.getByText("assistant")).toBeInTheDocument();
    expect(screen.getByText("Thinking")).toBeInTheDocument();
  });
});
