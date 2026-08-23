import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent } from "./Tooltip";
import Button from "./Button";

function renderDeleteTooltip() {
  return render(
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button aria-label="Delete workflow">Delete</Button>
        </TooltipTrigger>
        <TooltipContent>Permanently delete this workflow</TooltipContent>
      </Tooltip>
    </TooltipProvider>,
  );
}

describe("Tooltip", () => {
  it("renders the trigger and keeps the tooltip text hidden until shown", () => {
    renderDeleteTooltip();
    expect(screen.getByRole("button", { name: "Delete workflow" })).toBeInTheDocument();
    expect(screen.queryByText("Permanently delete this workflow")).not.toBeInTheDocument();
  });

  it("shows the tooltip on keyboard focus and hides it again on blur", async () => {
    const user = userEvent.setup();
    renderDeleteTooltip();

    await user.tab();
    expect(screen.getByRole("button", { name: "Delete workflow" })).toHaveFocus();

    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Permanently delete this workflow",
    );

    await user.tab();
    await waitFor(() => {
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    });
  });
});
