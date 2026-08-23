"use client";

import { forwardRef } from "react";
import type { TextareaHTMLAttributes } from "react";

import { cn } from "./cn";

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, disabled, rows = 4, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        disabled={disabled}
        rows={rows}
        className={cn(
          "w-full resize-none rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-sm text-text-hi placeholder:text-text-lo transition outline-none",
          "focus-visible:border-sky-400/50 focus-visible:ring-2 focus-visible:ring-accent-sky",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "aria-[invalid=true]:border-rose-400/50 aria-[invalid=true]:focus-visible:ring-accent-rose",
          className,
        )}
        {...props}
      />
    );
  },
);
Textarea.displayName = "Textarea";

export default Textarea;
