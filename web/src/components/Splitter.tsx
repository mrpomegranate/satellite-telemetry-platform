import { useCallback, useEffect, useRef } from "react";

/**
 * Drag handle between two panes. Reports a delta in pixels; the parent owns
 * the size so it can clamp and persist it.
 */
export function Splitter({
  orientation,
  onResize,
  onDoubleClick,
}: {
  /** "vertical" = a vertical bar resizing width; "horizontal" resizes height. */
  orientation: "vertical" | "horizontal";
  onResize: (delta: number) => void;
  onDoubleClick?: () => void;
}) {
  const last = useRef<number | null>(null);

  const move = useCallback(
    (event: PointerEvent) => {
      if (last.current === null) return;
      const position = orientation === "vertical" ? event.clientX : event.clientY;
      onResize(position - last.current);
      last.current = position;
    },
    [orientation, onResize]
  );

  const stop = useCallback(() => {
    last.current = null;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  }, []);

  useEffect(() => {
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
  }, [move, stop]);

  return (
    <div
      className={`splitter splitter-${orientation}`}
      role="separator"
      aria-orientation={orientation}
      onDoubleClick={onDoubleClick}
      onPointerDown={(event) => {
        last.current =
          orientation === "vertical" ? event.clientX : event.clientY;
        document.body.style.cursor =
          orientation === "vertical" ? "col-resize" : "row-resize";
        document.body.style.userSelect = "none";
      }}
    >
      <span className="splitter-grip" />
    </div>
  );
}