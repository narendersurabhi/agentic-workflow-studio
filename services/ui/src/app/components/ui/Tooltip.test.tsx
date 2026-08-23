import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent } from "./Tooltip";
import Button from "./Button";

describe("Tooltip", () => {
  it("renders the trigger and keeps the tooltip text hidden until shown", () => {
    render(
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button aria-label="Delete workflow">Delete</Button>
          </TooltipTrigger>
          <TooltipContent>Permanently delete this workflow</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    );
    expect(screen.getByRole("button", { name: "Delete workflow" })).toBeInTheDocument();
    expect(screen.queryByText("Permanently delete this workflow")).not.toBeInTheDocument();
  });
});
