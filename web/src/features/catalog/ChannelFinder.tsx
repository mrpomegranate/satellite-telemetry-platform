import { useEffect, useState } from "react";
import { api, type Channel } from "../../api/client";

// Finding one channel among thousands is typing, not scrolling.
export function ChannelFinder({
  subsystemId,
  selected,
  onToggle,
}: {
  subsystemId?: string;
  selected: Channel[];
  onToggle: (c: Channel) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Channel[]>([]);

  useEffect(() => {
    const handle = setTimeout(() => {
      api
        .channels({ q: q || undefined, subsystem_id: subsystemId })
        .then(setResults)
        .catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(handle);
  }, [q, subsystemId]);

  const selectedIds = new Set(selected.map((c) => c.id));

  return (
    <div style={{ marginTop: 14 }}>
      <input
        placeholder="search channels..."
        value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ width: "100%" }}
      />
      <div style={{ marginTop: 8 }}>
        {results.map((c) => (
          <div
            key={c.id}
            className={`tree-item ${selectedIds.has(c.id) ? "active" : ""}`}
            onClick={() => onToggle(c)}
            title={c.display_name ?? c.mnemonic}
          >
            {selectedIds.has(c.id) ? "\u2713 " : ""}
            {c.mnemonic}
          </div>
        ))}
        {results.length === 0 && (
          <div className="muted" style={{ fontSize: 12 }}>
            no matches
          </div>
        )}
      </div>
    </div>
  );
}
