import { Suspense } from "react";
import ObservabilityScreen from "../../features/observability/ObservabilityScreen";

export default function ObservabilityPage() {
  return (
    <Suspense fallback={<div className="min-h-screen" />}>
      <ObservabilityScreen />
    </Suspense>
  );
}
