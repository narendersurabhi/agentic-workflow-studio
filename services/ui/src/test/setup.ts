import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement these; Radix's Select/Popper positioning and
// pointer-capture logic call them unconditionally during interaction tests.
if (!window.HTMLElement.prototype.hasPointerCapture) {
  window.HTMLElement.prototype.hasPointerCapture = () => false;
}
if (!window.HTMLElement.prototype.releasePointerCapture) {
  window.HTMLElement.prototype.releasePointerCapture = () => {};
}
if (!window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = () => {};
}
if (typeof window.ResizeObserver === "undefined") {
  window.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// Node 22+'s built-in global `localStorage` (unconfigured, no --localstorage-file)
// shadows jsdom's spec-compliant Storage and lacks getItem/setItem/clear. Replace
// it with a real in-memory Storage implementation so app code that reads/writes
// localStorage works the same in tests regardless of the host Node version.
function needsStoragePolyfill(storage: unknown): boolean {
  return (
    !storage ||
    typeof (storage as Storage).getItem !== "function" ||
    typeof (storage as Storage).setItem !== "function" ||
    typeof (storage as Storage).removeItem !== "function" ||
    typeof (storage as Storage).clear !== "function"
  );
}

function createMemoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key: string) => (data.has(key) ? data.get(key)! : null),
    key: (index: number) => Array.from(data.keys())[index] ?? null,
    removeItem: (key: string) => {
      data.delete(key);
    },
    setItem: (key: string, value: string) => {
      data.set(key, String(value));
    },
  };
}

if (needsStoragePolyfill(window.localStorage)) {
  Object.defineProperty(window, "localStorage", {
    value: createMemoryStorage(),
    writable: true,
    configurable: true,
  });
}
if (needsStoragePolyfill(window.sessionStorage)) {
  Object.defineProperty(window, "sessionStorage", {
    value: createMemoryStorage(),
    writable: true,
    configurable: true,
  });
}
