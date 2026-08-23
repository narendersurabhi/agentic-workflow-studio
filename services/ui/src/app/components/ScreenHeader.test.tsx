import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import ScreenHeader from "./ScreenHeader";

describe("ScreenHeader", () => {
  it("renders eyebrow, title, and description", () => {
    render(
      <ScreenHeader eyebrow="Studio" title="Workflows" description="Build and run agent workflows." />,
    );
    expect(screen.getByText("Studio")).toBeInTheDocument();
    expect(screen.getByText("Workflows")).toBeInTheDocument();
    expect(screen.getByText("Build and run agent workflows.")).toBeInTheDocument();
  });

  it("renders provided actions and children", () => {
    render(
      <ScreenHeader eyebrow="Studio" title="Workflows" description="desc">
        <div data-testid="child">child content</div>
      </ScreenHeader>,
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });
});
