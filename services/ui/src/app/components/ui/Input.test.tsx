import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import Input from "./Input";
import Textarea from "./Textarea";

describe("Input", () => {
  it("renders a labeled text input", () => {
    render(
      <label htmlFor="name">
        Name
        <Input id="name" placeholder="Your name" />
      </label>,
    );
    const input = screen.getByPlaceholderText("Your name");
    expect(input).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBe(input);
  });

  it("is reachable via Tab and accepts typed input", async () => {
    const user = userEvent.setup();
    render(<Input aria-label="Search" />);

    await user.tab();
    const input = screen.getByLabelText("Search");
    expect(input).toHaveFocus();

    await user.type(input, "hello");
    expect(input).toHaveValue("hello");
  });

  it("respects disabled state", () => {
    render(<Input aria-label="disabled field" disabled />);
    expect(screen.getByLabelText("disabled field")).toBeDisabled();
  });

  it("reflects invalid state via aria-invalid styling hook", () => {
    render(<Input aria-label="email" aria-invalid="true" />);
    expect(screen.getByLabelText("email")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("Textarea", () => {
  it("renders with the given number of rows", () => {
    render(<Textarea aria-label="notes" rows={6} />);
    expect(screen.getByLabelText("notes")).toHaveAttribute("rows", "6");
  });
});
