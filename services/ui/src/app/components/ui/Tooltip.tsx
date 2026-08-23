"use client";

import { forwardRef } from "react";
import type { ComponentPropsWithoutRef, ElementRef } from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "./cn";

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export const TooltipContent = forwardRef<
  ElementRef<typeof TooltipPrimitive.Content>,
  ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "z-50 overflow-hidden rounded-lg border border-subtle bg-surface-2 px-2.5 py-1.5 text-xs font-medium text-text-hi shadow-card",
        "data-[state=delayed-open]:animate-fade-up",
        "will-change-[transform,opacity]",
        className,
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
TooltipContent.displayName = "TooltipContent";

export default Tooltip;
