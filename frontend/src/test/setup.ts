import "@testing-library/jest-dom/vitest";

// jsdom implements no media queries at all, and `window.matchMedia` is simply absent —
// so any component that asks about the viewport throws on render. Reporting "not a
// desktop" gives component tests the mobile layout, which is the narrower of the two and
// therefore the stricter thing to assert against.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
