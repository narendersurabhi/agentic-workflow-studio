import { Suspense } from "react";
import { WorkspaceSurfaceContent } from "../../WorkspaceSurfaceContent";

export default function ComposePage() {
  return (
    <Suspense fallback={<div className="min-h-screen" />}>
      <WorkspaceSurfaceContent screen="compose" />
    </Suspense>
  );
}
