import { useMemo, useState } from "react";
import { api, type Label } from "../../api/client";

/**
 * The review queue. Until this existed a detection run wrote proposals that
 * nobody could see as a list, let alone act on - the chart showed them but
 * offered no verdict, so the feedback loop only ran halfway.
 *
 * Filter options are derived from the labels themselves rather than
 * hardcoded. Run a second detector and its algorithm appears in the dropdown
 * with no change here, which is the whole point of returning `algorithm` from
 * the API instead of a version uuid.
 */
export function FindingsPanel({
  height,
  labels,
  onZoomTo,
  onReviewed,
}: {
  height: number;
  labels: Label[];
  onZoomTo: (label: Label) => void;
  onReviewed: () => void;
}) {
  const [algorithm, setAlgorithm] = useState("");
  const [taxonomy, setTaxonomy] = useState("");
  const [status, setStatus] = useState("proposed");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const options = useMemo(() => {
    const collect = (pick: (l: Label) => string | null | undefined) =>
      [...new Set(labels.map(pick).filter(Boolean))].sort() as string[];
    return {
      algorithms: collect((l) => l.algorithm),
      taxonomies: collect((l) => l.taxonomy_code),
      statuses: collect((l) => l.review_status),
    };
  }, [labels]);

  const shown = useMemo(
    () =>
      labels
        .filter((l) => !algorithm || l.algorithm === algorithm)
        .filter((l) => !taxonomy || l.taxonomy_code === taxonomy)
        .filter((l) => !status || l.review_status === status)
        .sort((a, b) => a.start.localeCompare(b.start)),
    [labels, algorithm, taxonomy, status]
  );

  async function review(label: Label, verdict: "accepted" | "rejected") {
    setBusy(label.id);
    setError(null);
    try {
      await api.reviewLabel(label.id, verdict);
      onReviewed();
    } catch {
      setError("could not save that verdict");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="findings-panel" style={{ height }}>
      <div className="panel-head">
        <span className="panel-title">
          Findings <span className="muted">({shown.length})</span>
        </span>

        <div className="findings-filters">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any status</option>
            {options.statuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>

          {options.algorithms.length > 1 && (
            <select
              value={algorithm}
              onChange={(e) => setAlgorithm(e.target.value)}
            >
              <option value="">Any detector</option>
              {options.algorithms.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          )}

          <select value={taxonomy} onChange={(e) => setTaxonomy(e.target.value)}>
            <option value="">Any type</option>
            {options.taxonomies.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="group-error">{error}</div>}

      {shown.length === 0 ? (
        <div className="muted panel-empty">
          {labels.length
            ? "Nothing matches these filters."
            : "No findings yet. Run a detector over this group."}
        </div>
      ) : (
        <div className="findings-list">
          {shown.map((l) => (
            <div className="finding-row" key={l.id}>
              <span
                className="finding-swatch"
                style={{ background: l.color ?? "#993C1D" }}
                title={l.taxonomy_name ?? l.label_class}
              />

              <button
                className="finding-when link-btn"
                onClick={() => onZoomTo(l)}
                title="Zoom the chart to this finding"
              >
                {l.start.slice(0, 16).replace("T", " ")}
              </button>

              <span className="finding-type">
                {l.taxonomy_name ?? l.label_class}
              </span>

              <span className="muted finding-meta">
                {/* the detector, not the version uuid: this is what an analyst
                    uses to decide how much weight to give the finding */}
                {l.algorithm ?? l.source}
                {l.confidence != null && ` \u00b7 ${l.confidence.toFixed(2)}`}
              </span>

              {l.review_status === "proposed" ? (
                <span className="finding-actions">
                  <button
                    disabled={busy === l.id}
                    onClick={() => review(l, "accepted")}
                  >
                    Accept
                  </button>
                  <button
                    disabled={busy === l.id}
                    onClick={() => review(l, "rejected")}
                  >
                    Reject
                  </button>
                </span>
              ) : (
                <span className={`badge badge-${l.review_status}`}>
                  {l.review_status}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}