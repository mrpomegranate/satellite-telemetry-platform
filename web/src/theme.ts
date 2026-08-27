import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "telemetry-theme";

function initialTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

/**
 * Apply immediately rather than in an effect.
 *
 * React runs child effects before parent effects, so a chart that reads CSS
 * variables in its own effect would see the previous palette if the attribute
 * were only set in this hook's effect. Writing it synchronously in the setter
 * guarantees the variables are current before anything re-renders.
 */
function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(STORAGE_KEY, theme);
}

/** Theme state, persisted and reflected onto <html data-theme>. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    const initial = initialTheme();
    applyTheme(initial); // before first paint, not after
    return initial;
  });

  // Covers hot reloads and any external change to the attribute.
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      applyTheme(next);
      return next;
    });
  }, []);

  return [theme, toggle];
}