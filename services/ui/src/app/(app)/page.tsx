"use client";

import { Suspense } from "react";
import { LegacyAwareHomeContent } from "../WorkspaceSurfaceContent";

export default function Home() {
  return (
    <Suspense fallback={<div className="min-h-screen" />}>
      <LegacyAwareHomeContent />
    </Suspense>
  );
}
