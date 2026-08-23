import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "./Select";

describe("Select", () => {
  it("renders a trigger with placeholder text when closed", () => {
    render(
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
    const trigger = screen.getByRole("combobox", { name: "Provider" });
    expect(trigger).toBeInTheDocument();
    expect(screen.getByText("Choose a provider")).toBeInTheDocument();
  });
});
