import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import Button from "./Button";

describe("Button", () => {
  it("renders a real button element with type=button by default", () => {
    render(<Button>Click me</Button>);
    const button = screen.getByRole("button", { name: "Click me" });
    expect(button.tagName).toBe("BUTTON");
    expect(button).toHaveAttribute("type", "button");
  });

  it("fires onClick and respects disabled", () => {
    const onClick = vi.fn();
    render(
      <Button onClick={onClick} disabled>
        Save
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("applies variant and size classes", () => {
    render(
      <Button variant="destructive" size="lg">
        Delete
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button.className).toContain("bg-accent-rose");
    expect(button.className).toContain("h-12");
  });

  it("renders as a child element (e.g. an anchor) when asChild is set", () => {
    render(
      <Button asChild>
        <a href="/workflows">Go to workflows</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "Go to workflows" });
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "/workflows");
  });

  it("has a visible focus-ring utility class for keyboard users", () => {
    render(<Button>Focus me</Button>);
    const button = screen.getByRole("button", { name: "Focus me" });
    expect(button.className).toContain("focus-visible:ring-2");
  });

  it("is reachable via Tab and activates on both Enter and Space", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save</Button>);

    await user.tab();
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledTimes(1);

    await user.keyboard(" ");
    expect(onClick).toHaveBeenCalledTimes(2);
  });
});
