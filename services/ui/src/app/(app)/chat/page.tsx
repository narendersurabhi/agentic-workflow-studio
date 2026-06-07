import { Suspense } from "react";
import { WorkspaceSurfaceContent } from "../../WorkspaceSurfaceContent";

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="min-h-screen" />}>
      <WorkspaceSurfaceContent screen="chat" />
    </Suspense>
  );
}
