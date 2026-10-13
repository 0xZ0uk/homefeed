import { useEffect } from "react";

/**
 * Suppresses CSS transitions for one frame when the OS color scheme flips, so
 * colors snap to the new theme instead of animating through it.
 */
export function DisableThemeTransitions() {
  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const style = document.createElement("style");
      style.textContent = "*,*::before,*::after{transition:none !important}";
      document.head.appendChild(style);
      void document.body.offsetHeight;
      requestAnimationFrame(() => requestAnimationFrame(() => style.remove()));
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return null;
}
