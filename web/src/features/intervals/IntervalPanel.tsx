import type { PendingInterval } from "../chart/TelemetryChart";

/** ISO string -> value for <input type="datetime-local"> */
function toLocalInput(iso: string): string {
  return iso.slice(0, 16);
}

/** datetime-local value -> ISO string */
function fromLocalInput(value: string): string {
  return new Date(value + "Z").toISOString();
}

function durationText(start: string, end: string): string {
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms <= 0) return "invalid";
  const hours = ms / 3_600_000;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  const days = hours / 24;
  if (days < 60) return `${days.toFixed(1)} d`;
  return `${(days / 30.44).toFixed(1)} mo`;
}

/**
 * Time intervals are collected before labelling rather than one at a time.
 * An analyst reviewing a mission usually finds several regions worth marking,
 * and forcing a save between each one loses their place in the data.
 */
export function IntervalPanel({
  height,
  intervals,
  onChange,
  onRemove,
  onClearAll,
  onZoomTo,
}: {
  height: number;
  intervals: PendingInterval[];
  onChange: (id: string, patch: Partial<PendingInterval>) => void;
  onRemove: (id: string) => void;
  onClearAll: () => void;
  onZoomTo: (interval: PendingInterval) => void;
}) {
  if (!intervals.length) {
    return (
      <div className="interval-panel" style={{ height }}>
        <div className="panel-head">
          <span className="panel-title">Time intervals</span>
        </div>
        <div className="muted panel-empty">
          Drag across the chart to add an interval. Add as many as you need
          before labelling.
        </div>
      </div>
    );
  }

  return (
    <div className="interval-panel" style={{ height }}>
      <div className="panel-head">
        <span className="panel-title">
          Time intervals <span className="muted">({intervals.length})</span>
        </span>
        <button className="link-btn" onClick={onClearAll}>
          Clear all
        </button>
      </div>

      <div className="interval-list">
        {intervals.map((iv, index) => {
          const invalid = new Date(iv.end) <= new Date(iv.start);
          return (
            <div className={`interval-row ${invalid ? "invalid" : ""}`} key={iv.id}>
              <span className="interval-index">{index + 1}</span>

              <input
                type="datetime-local"
                value={toLocalInput(iv.start)}
                onChange={(e) =>
                  onChange(iv.id, { start: fromLocalInput(e.target.value) })
                }
                title="Interval start (UTC)"
              />
              <span className="muted">&rarr;</span>
              <input
                type="datetime-local"
                value={toLocalInput(iv.end)}
                onChange={(e) =>
                  onChange(iv.id, { end: fromLocalInput(e.target.value) })
                }
                title="Interval end (UTC)"
              />

              <span className="badge duration">
                {durationText(iv.start, iv.end)}
              </span>

              <button
                className="chip-btn"
                title="Zoom the chart to this interval"
                onClick={() => onZoomTo(iv)}
              >
                &#9678;
              </button>
              <button
                className="chip-btn"
                title="Remove this interval"
                onClick={() => onRemove(iv.id)}
              >
                &times;
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}