import { useEffect, useMemo, useState } from "react";
import { api, type Channel } from "../../api/client";

/**
 * Finding one channel among thousands is typing, not scrolling. Results group
 * by subsystem, and each group can be selected wholesale - useful once several
 * subsystems are chosen in the tree.
 */
export function ChannelFinder({
  subsystemIds,
  selected,
  onToggle,
  onSetMany,
}: {
  subsystemIds: string[];
  selected: Channel[];
  onToggle: (c: Channel) => void;
  /** Add or remove a batch at once (group or global select-all). */
  onSetMany: (channels: Channel[], on: boolean) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Channel[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setBusy(true);
    const handle = setTimeout(() => {
      // The API filters by one subsystem at a time; fan out and merge.
      const requests = subsystemIds.length
        ? subsystemIds.map((id) =>
            api.channels({ q: q || undefined, subsystem_id: id })
          )
        : [api.channels({ q: q || undefined })];

      Promise.all(requests)
        .then((lists) => {
          const seen = new Set<string>();
          const merged: Channel[] = [];
          lists.flat().forEach((c) => {
            if (!seen.has(c.id)) {
              seen.add(c.id);
              merged.push(c);
            }
          });
          merged.sort((a, b) => a.mnemonic.localeCompare(b.mnemonic));
          setResults(merged);
        })
        .catch(() => setResults([]))
        .finally(() => setBusy(false));
    }, 200);
    return () => clearTimeout(handle);
  }, [q, subsystemIds]);

  const selectedIds = useMemo(
    () => new Set(selected.map((c) => c.id)),
    [selected]
  );

  const grouped = useMemo(() => {
    const map = new Map<string, Channel[]>();
    results.forEach((c) => {
      const key = c.subsystem_code ?? "\u2014";
      const list = map.get(key);
      if (list) list.push(c);
      else map.set(key, [c]);
    });
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [results]);

  const allShown = results.length > 0 && results.every((c) => selectedIds.has(c.id));

  return (
    <div className="finder">
      <div className="finder-search">
        <span className="finder-icon" aria-hidden="true">
          &#9906;
        </span>
        <input
          placeholder="Search channels"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search channels"
        />
        {q && (
          <button className="chip-btn" onClick={() => setQ("")} title="Clear search">
            &times;
          </button>
        )}
      </div>

      <div className="finder-meta">
        {busy ? (
          <span className="muted">searching\u2026</span>
        ) : (
          <span className="muted">
            {results.length} channel{results.length === 1 ? "" : "s"}
            {selectedIds.size > 0 && ` \u00b7 ${selectedIds.size} plotted`}
          </span>
        )}
        {results.length > 0 && (
          <button
            className="link-btn"
            onClick={() => onSetMany(results, !allShown)}
          >
            {allShown ? "Deselect all" : "Select all"}
          </button>
        )}
      </div>

      <div className="finder-results">
        {grouped.map(([code, channels]) => {
          const allInGroup = channels.every((c) => selectedIds.has(c.id));
          return (
            <div className="finder-group" key={code}>
              <div className="finder-group-head">
                <span className="subsystem-tag">{code}</span>
                <span className="muted">{channels.length}</span>
                <button
                  className="link-btn"
                  onClick={() => onSetMany(channels, !allInGroup)}
                  title={allInGroup ? "Remove this subsystem" : "Plot this subsystem"}
                >
                  {allInGroup ? "none" : "all"}
                </button>
              </div>
              {channels.map((c) => {
                const on = selectedIds.has(c.id);
                return (
                  <button
                    key={c.id}
                    className={`channel-row ${on ? "on" : ""}`}
                    onClick={() => onToggle(c)}
                    title={c.display_name ?? c.mnemonic}
                  >
                    <span className={`checkbox ${on ? "on" : ""}`} aria-hidden="true">
                      {on ? "\u2713" : ""}
                    </span>
                    <span className="channel-name">{c.mnemonic}</span>
                    {c.units && <span className="channel-units">{c.units}</span>}
                  </button>
                );
              })}
            </div>
          );
        })}

        {!busy && results.length === 0 && (
          <div className="finder-empty muted">
            No channels match {q ? `"${q}"` : "this selection"}.
          </div>
        )}
      </div>
    </div>
  );
}