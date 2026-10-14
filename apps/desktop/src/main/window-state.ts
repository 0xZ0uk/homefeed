/** The main window's size and position, saved across launches (`window-state.json`). */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface WindowState {
  bounds: Rect;
  maximized: boolean;
}

export const DEFAULT_SIZE = { width: 1280, height: 800 };
const MIN_VISIBLE = 100; // px of the window that must land on some display

export function loadWindowState(path: string): WindowState | null {
  try {
    const data: unknown = JSON.parse(readFileSync(path, "utf8"));
    return isWindowState(data) ? data : null;
  } catch {
    return null;
  }
}

export function saveWindowState(path: string, state: WindowState): void {
  try {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify(state));
  } catch {
    // Not worth failing over.
  }
}

/**
 * The bounds to open with: the saved ones while they still overlap a display's work area
 * (monitors get unplugged), else the default size, centered (no x/y).
 */
export function initialBounds(
  saved: WindowState | null,
  workAreas: Rect[],
): Partial<Rect> & { width: number; height: number } {
  if (
    saved &&
    workAreas.some((area) => overlaps(saved.bounds, area, MIN_VISIBLE))
  ) {
    return saved.bounds;
  }
  return { ...DEFAULT_SIZE };
}

function overlaps(a: Rect, b: Rect, min: number): boolean {
  const width = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const height = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  return width >= min && height >= min;
}

function isWindowState(value: unknown): value is WindowState {
  if (typeof value !== "object" || value === null) return false;
  const { bounds, maximized } = value as Record<string, unknown>;
  if (
    typeof maximized !== "boolean" ||
    typeof bounds !== "object" ||
    bounds === null
  ) {
    return false;
  }
  const rect = bounds as Record<string, unknown>;
  return (["x", "y", "width", "height"] as const).every(
    (key) => typeof rect[key] === "number" && Number.isFinite(rect[key]),
  );
}
