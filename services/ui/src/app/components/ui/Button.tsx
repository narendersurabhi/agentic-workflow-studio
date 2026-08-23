"use client";

import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "./cn";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl font-semibold transition disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-sky focus-visible:ring-offset-2 focus-visible:ring-offset-surface-page",
  {
    variants: {
      variant: {
        primary:
          "border border-sky-400/30 bg-accent-sky text-text-sky-token hover:border-sky-400/50 hover:bg-accent-sky/80",
        secondary:
          "border border-subtle bg-surface-1 text-text-hi hover:border-default-theme hover:bg-surface-2",
        ghost:
          "border border-transparent bg-transparent text-text-md hover:bg-surface-1 hover:text-text-hi",
        destructive:
          "border border-rose-400/30 bg-accent-rose text-text-rose-token hover:border-rose-400/50 hover:bg-accent-rose/80",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
        icon: "h-10 w-10 p-0",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, type = "button", ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        type={asChild ? undefined : type}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export default Button;
