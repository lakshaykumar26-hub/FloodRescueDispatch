import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// RTL auto-cleanup between tests. NOTE: do NOT call unstubAllGlobals() here —
// it would remove the ResizeObserver/matchMedia stubs below that recharts needs.
afterEach(() => {
  cleanup();
});

// Recharts renders inside ResponsiveContainer which needs ResizeObserver.
class FakeResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal(
  "ResizeObserver",
  FakeResizeObserver as unknown as typeof ResizeObserver,
);

// matchMedia is used by some UI libs; jsdom lacks it.
if (!window.matchMedia) {
  window.matchMedia = (() => ({
    matches: false,
    media: "",
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

if (!window.scrollTo) {
  window.scrollTo = () => {};
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}
