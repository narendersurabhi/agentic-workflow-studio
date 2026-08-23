import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "./Select";

function renderProviderSelect() {
  return render(
    <Select>
      <SelectTrigger aria-label="Provider">
        <SelectValue placeholder="Choose a provider" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="openai">OpenAI</SelectItem>
        <SelectItem value="gemini">Gemini</SelectItem>
      </SelectContent>
    </Select>,
  );
}

describe("Select", () => {
  it("renders a trigger with placeholder text when closed", () => {
    renderProviderSelect();
    const trigger = screen.getByRole("combobox", { name: "Provider" });
    expect(trigger).toBeInTheDocument();
    expect(screen.getByText("Choose a provider")).toBeInTheDocument();
  });

  it("opens on click, lists options, and commits the chosen value to the trigger", async () => {
    const user = userEvent.setup();
    renderProviderSelect();

    const trigger = screen.getByRole("combobox", { name: "Provider" });
    await user.click(trigger);

    const option = await screen.findByRole("option", { name: "Gemini" });
    await user.click(option);

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("Gemini");
    });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("supports keyboard navigation: open with Enter, move with ArrowDown, commit with Enter", async () => {
    const user = userEvent.setup();
    renderProviderSelect();

    await user.tab();
    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveFocus();

    await user.keyboard("{Enter}");
    await screen.findByRole("listbox");

    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("Gemini");
    });
  });
});
