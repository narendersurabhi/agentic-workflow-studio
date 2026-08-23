import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "./Card";
import Badge from "./Badge";

describe("Card", () => {
  it("renders a composed card with header, content, and footer", () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Workflow run</CardTitle>
          <CardDescription>Started 2 minutes ago</CardDescription>
        </CardHeader>
        <CardContent>Body content</CardContent>
        <CardFooter>Footer content</CardFooter>
      </Card>,
    );
    expect(screen.getByText("Workflow run")).toBeInTheDocument();
    expect(screen.getByText("Started 2 minutes ago")).toBeInTheDocument();
    expect(screen.getByText("Body content")).toBeInTheDocument();
    expect(screen.getByText("Footer content")).toBeInTheDocument();
  });
});

describe("Badge", () => {
  it("renders children with the requested variant class", () => {
    render(<Badge variant="emerald">Success</Badge>);
    const badge = screen.getByText("Success");
    expect(badge.className).toContain("bg-accent-emerald");
  });
});
