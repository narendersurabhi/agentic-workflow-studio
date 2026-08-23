"use client";

import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";

import { cn } from "./cn";

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, disabled, ...props }, ref) => {
    return (
      <input
        ref={ref}
        disabled={disabled}
        className={cn(
          "w-full rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-sm text-text-hi placeholder:text-text-lo transition outline-none",
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
Input.displayName = "Input";

export default Input;
