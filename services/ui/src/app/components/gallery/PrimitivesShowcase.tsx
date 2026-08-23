"use client";

import { useState } from "react";

import { useAppTheme, SHELL_THEMES, type ShellTheme } from "../../lib/theme";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui";

const BUTTON_VARIANTS = ["primary", "secondary", "ghost", "destructive"] as const;
const BUTTON_SIZES = ["sm", "md", "lg"] as const;
const BADGE_VARIANTS = ["neutral", "sky", "emerald", "rose", "amber"] as const;

function SubsectionHeading({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-4">
      <h3 className="text-lg font-semibold tracking-tight text-text-hi">{title}</h3>
      <p className="mt-1 text-sm text-text-md">{description}</p>
    </div>
  );
}

function ThemeControls() {
  const { mounted, theme, shellTheme, toggleTheme, setShellTheme } = useAppTheme();
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-subtle bg-surface-1 px-4 py-3">
      <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-lo">
        Live preview controls
      </span>
      <Button type="button" variant="secondary" size="sm" onClick={toggleTheme}>
        {mounted && theme === "light" ? "Switch to dark" : "Switch to light"}
      </Button>
      <div className="min-w-[200px]">
        <Select
          value={mounted ? shellTheme : "ocean"}
          onValueChange={(value) => setShellTheme(value as ShellTheme)}
        >
          <SelectTrigger aria-label="Shell theme">
            <SelectValue placeholder="Shell theme" />
          </SelectTrigger>
          <SelectContent>
            {SHELL_THEMES.map((t) => (
              <SelectItem key={t.id} value={t.id}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <span className="text-xs text-text-lo">
        Toggle dark/light and the shell theme to verify every primitive below still reads
        correctly against the current tokens.
      </span>
    </div>
  );
}

function ButtonShowcase() {
  return (
    <div>
      <SubsectionHeading
        title="Button"
        description="Variants × sizes, disabled state, and asChild rendering a real anchor for link-styled actions."
      />
      <div className="space-y-4">
        {BUTTON_VARIANTS.map((variant) => (
          <div key={variant} className="flex flex-wrap items-center gap-3">
            <span className="w-24 shrink-0 text-xs font-semibold uppercase tracking-[0.12em] text-text-lo">
              {variant}
            </span>
            {BUTTON_SIZES.map((size) => (
              <Button key={size} variant={variant} size={size}>
                {variant === "destructive" ? "Delete" : "Continue"}
              </Button>
            ))}
            <Button variant={variant} disabled>
              Disabled
            </Button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-3">
          <span className="w-24 shrink-0 text-xs font-semibold uppercase tracking-[0.12em] text-text-lo">
            asChild
          </span>
          <Button asChild variant="secondary">
            <a href="#buttons">Rendered as &lt;a&gt;</a>
          </Button>
        </div>
      </div>
    </div>
  );
}

function InputShowcase() {
  const [value, setValue] = useState("");
  return (
    <div>
      <SubsectionHeading
        title="Input & Textarea"
        description="Text fields styled against surface/border tokens, with focus, disabled, and invalid states."
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="showcase-input-default" className="text-xs font-semibold text-text-lo">
            Default
          </label>
          <Input
            id="showcase-input-default"
            placeholder="Workflow name"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="showcase-input-disabled" className="text-xs font-semibold text-text-lo">
            Disabled
          </label>
          <Input id="showcase-input-disabled" placeholder="Not editable" disabled />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="showcase-input-invalid" className="text-xs font-semibold text-text-lo">
            Invalid
          </label>
          <Input
            id="showcase-input-invalid"
            placeholder="you@example.com"
            defaultValue="not-an-email"
            aria-invalid="true"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="showcase-textarea" className="text-xs font-semibold text-text-lo">
            Textarea
          </label>
          <Textarea id="showcase-textarea" placeholder="Describe the workflow goal…" rows={3} />
        </div>
      </div>
    </div>
  );
}

function SelectShowcase() {
  const [provider, setProvider] = useState<string | undefined>(undefined);
  return (
    <div>
      <SubsectionHeading
        title="Select"
        description="Keyboard-navigable listbox (Radix Select) with typeahead, scroll buttons, and a checkmark on the selected item."
      />
      <div className="max-w-xs space-y-1.5">
        <label className="text-xs font-semibold text-text-lo" id="showcase-select-label">
          LLM provider
        </label>
        <Select value={provider} onValueChange={setProvider}>
          <SelectTrigger aria-labelledby="showcase-select-label">
            <SelectValue placeholder="Choose a provider" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="gemini">Google Gemini</SelectItem>
            <SelectItem value="openai">OpenAI</SelectItem>
            <SelectItem value="bedrock-anthropic">Bedrock (Anthropic)</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

function DialogShowcase() {
  return (
    <div>
      <SubsectionHeading
        title="Dialog"
        description="Focus-trapped modal (Radix Dialog) with a labelled title/description, close button, and footer actions."
      />
      <Dialog>
        <DialogTrigger asChild>
          <Button variant="primary">Open dialog</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename workflow</DialogTitle>
            <DialogDescription>
              This name is shown in the workflow library and run history.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <Input placeholder="Workflow name" defaultValue="Customer onboarding" />
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost">Cancel</Button>
            <Button variant="primary">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function TooltipShowcase() {
  return (
    <div>
      <SubsectionHeading
        title="Tooltip"
        description="Hover/focus hint (Radix Tooltip) — reachable by keyboard, dismissible with Escape."
      />
      <TooltipProvider>
        <div className="flex flex-wrap gap-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="secondary" size="icon" aria-label="Run workflow">
                ▶
              </Button>
            </TooltipTrigger>
            <TooltipContent>Run this workflow</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="secondary" size="icon" aria-label="Duplicate workflow">
                ⧉
              </Button>
            </TooltipTrigger>
            <TooltipContent>Duplicate</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="destructive" size="icon" aria-label="Delete workflow">
                ✕
              </Button>
            </TooltipTrigger>
            <TooltipContent>Delete permanently</TooltipContent>
          </Tooltip>
        </div>
      </TooltipProvider>
    </div>
  );
}

function BadgeShowcase() {
  return (
    <div>
      <SubsectionHeading title="Badge" description="Status/tag pill in each accent tone." />
      <div className="flex flex-wrap gap-2">
        {BADGE_VARIANTS.map((variant) => (
          <Badge key={variant} variant={variant}>
            {variant}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function CardShowcase() {
  return (
    <div>
      <SubsectionHeading
        title="Card"
        description="Panel surface for grouped content, composed from Header / Title / Description / Content / Footer."
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Customer onboarding</CardTitle>
              <Badge variant="emerald">Active</Badge>
            </div>
            <CardDescription>Runs when a new lead is created in CRM.</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-text-md">
            4 steps · Last run 2 hours ago · 98% success rate
          </CardContent>
          <CardFooter>
            <Button variant="secondary" size="sm">
              View runs
            </Button>
            <Button variant="ghost" size="sm">
              Edit
            </Button>
          </CardFooter>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Invoice reminder</CardTitle>
              <Badge variant="amber">Paused</Badge>
            </div>
            <CardDescription>Sends a reminder 3 days before an invoice is due.</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-text-md">
            2 steps · Last run 3 days ago · 1 failure this week
          </CardContent>
          <CardFooter>
            <Button variant="secondary" size="sm">
              View runs
            </Button>
            <Button variant="ghost" size="sm">
              Edit
            </Button>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}

export default function PrimitivesShowcase() {
  return (
    <section className="mt-6 overflow-hidden rounded-[30px] border border-subtle bg-surface-page shadow-card">
      <div className="border-b border-subtle bg-gradient-panel-deep px-6 py-4">
        <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-text-sky-token">
          Phase 0 — Design System Foundation
        </div>
        <h2 className="mt-2 text-4xl font-semibold tracking-[-0.04em] text-text-hi md:text-5xl">
          Radix Primitives on Existing Tokens
        </h2>
        <p className="mt-3 max-w-3xl text-base text-text-md">
          Owned-code component layer (`app/components/ui/`) built on Radix primitives, styled
          entirely against the existing <code>@theme</code> tokens — no new tokens introduced.
          Use the controls below to flip dark/light mode and shell theme; every primitive should
          keep reading correctly.
        </p>
      </div>

      <div className="space-y-10 px-6 py-8 text-text-hi">
        <ThemeControls />
        <ButtonShowcase />
        <InputShowcase />
        <SelectShowcase />
        <DialogShowcase />
        <TooltipShowcase />
        <BadgeShowcase />
        <CardShowcase />
      </div>
    </section>
  );
}
