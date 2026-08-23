"use client";

import { forwardRef } from "react";
import type { HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "./cn";

export const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.1em] whitespace-nowrap",
  {
    variants: {
      variant: {
        neutral: "border-subtle bg-surface-1 text-text-md",
        sky: "border-sky-400/30 bg-accent-sky text-text-sky-token",
        emerald: "border-emerald-400/30 bg-accent-emerald text-text-emerald-token",
        rose: "border-rose-400/30 bg-accent-rose text-text-rose-token",
        amber: "border-amber-400/30 bg-accent-amber text-text-amber-token",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  },
);

export type BadgeProps = HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>;

const Badge = forwardRef<HTMLSpanElement, BadgeProps>(({ className, variant, ...props }, ref) => (
  <span ref={ref} className={cn(badgeVariants({ variant }), className)} {...props} />
));
Badge.displayName = "Badge";

export default Badge;
