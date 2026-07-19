import { useEffect, useState } from "react";
import { api, type TaxonomyItem } from "../../api/client";

// Anomaly vs off-nominal is a distinction satellite operators draw, so it is
// native to the UI rather than a note field.
export function LabelPanel({
  selection,
  groupId,
  onSaved,
}: {
  selection: { start: Date; end: Date } | null;
  groupId: string | null;
  onSaved: () => void;
}) {
  const [taxonomy, setTaxonomy] = useState<TaxonomyItem[]>([]);
  const [code, setCode] = useState<string>("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.taxonomy().then((items) => {
      setTaxonomy(items);
      if (items.length) setCode(items[0].code);
    });
  }, []);

  if (!selection) {
    return (
      <span className="muted">
        drag on the chart to select a window
      </span>
    );
  }
  if (!groupId) {
    return <span className="muted">create a group before labeling</span>;
  }

  const chosen = taxonomy.find((t) => t.code === code);

  async function save() {
    if (!chosen || !selection || !groupId) return;
    setBusy(true);
    try {
      await api.createLabel({
        group_id: groupId,
        start: selection.start.toISOString(),
        end: selection.end.toISOString(),
        label_class: chosen.label_class,
        taxonomy_code: chosen.code,
        note: note || undefined,
      });
      setNote("");
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <span className="chip">
        {selection.start.toISOString().slice(0, 16)} &rarr;{" "}
        {selection.end.toISOString().slice(0, 16)}
      </span>
      <select value={code} onChange={(e) => setCode(e.target.value)}>
        <optgroup label="Anomaly">
          {taxonomy
            .filter((t) => t.label_class === "anomaly")
            .map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
        </optgroup>
        <optgroup label="Off-nominal">
          {taxonomy
            .filter((t) => t.label_class === "off_nominal")
            .map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
        </optgroup>
      </select>
      <input
        placeholder="note (optional)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        style={{ width: 180 }}
      />
      <button onClick={save} disabled={busy}>
        {busy ? "saving..." : "Save label"}
      </button>
    </>
  );
}
