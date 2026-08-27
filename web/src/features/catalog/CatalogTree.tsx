import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Satellite, type Subsystem } from "../../api/client";

/**
 * The tree stops at subsystem on purpose: with thousands of channels per
 * satellite the fourth level is a search problem, handled by ChannelFinder.
 *
 * Subsystems multi-select. Plain click replaces the selection, Ctrl/Cmd-click
 * adds or removes, Shift-click extends from the last clicked row, and
 * "Select all" takes every subsystem on that satellite.
 * Each satellite has its own filter, since a real bus carries far more
 * subsystems than GOCE's eight.
 */
export function CatalogTree({
  onSelectSubsystems,
  selectedIds,
}: {
  onSelectSubsystems: (ids: string[], satellite: Satellite) => void;
  selectedIds: string[];
}) {
  const [satellites, setSatellites] = useState<Satellite[]>([]);
  const [expanded, setExpanded] = useState<Record<string, Subsystem[]>>({});
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  // Anchor for shift-click ranges: the last row clicked without shift.
  const anchor = useRef<{ satelliteId: string; subsystemId: string } | null>(null);

  useEffect(() => {
    api
      .satellites()
      .then(async (sats) => {
        setSatellites(sats);
        if (sats.length) {
          const subs = await api.subsystems(sats[0].id);
          setExpanded({ [sats[0].id]: subs });
        }
      })
      .catch((e) => setError(String(e)));
  }, []);

  async function toggleSatellite(sat: Satellite) {
    if (expanded[sat.id]) {
      const next = { ...expanded };
      delete next[sat.id];
      setExpanded(next);
      return;
    }
    const subs = await api.subsystems(sat.id);
    setExpanded({ ...expanded, [sat.id]: subs });
  }

  function clickSubsystem(
    event: React.MouseEvent,
    sub: Subsystem,
    sat: Satellite,
    rows: Subsystem[]
  ) {
    const additive = event.ctrlKey || event.metaKey;

    // Shift-click: select the span between the anchor and this row, inclusive.
    // Ranges run over the rows as displayed, so an active filter is respected.
    if (event.shiftKey && anchor.current?.satelliteId === sat.id) {
      const from = rows.findIndex((s) => s.id === anchor.current!.subsystemId);
      const to = rows.findIndex((s) => s.id === sub.id);
      if (from !== -1 && to !== -1) {
        const [lo, hi] = from <= to ? [from, to] : [to, from];
        const span = rows.slice(lo, hi + 1).map((s) => s.id);
        // Ctrl+Shift adds the span to what is already selected.
        const next = additive
          ? [...new Set([...selectedIds, ...span])]
          : span;
        onSelectSubsystems(next, sat);
        return;
      }
    }

    anchor.current = { satelliteId: sat.id, subsystemId: sub.id };

    if (!additive) {
      // Clicking the only selected subsystem clears it, so there is always a
      // way back to "show everything" without hunting for a button.
      const only = selectedIds.length === 1 && selectedIds[0] === sub.id;
      onSelectSubsystems(only ? [] : [sub.id], sat);
      return;
    }
    onSelectSubsystems(
      selectedIds.includes(sub.id)
        ? selectedIds.filter((id) => id !== sub.id)
        : [...selectedIds, sub.id],
      sat
    );
  }

  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);

  if (error) {
    return <div className="muted panel-empty">Catalog unavailable: {error}</div>;
  }

  return (
    <div className="tree">
      <div className="panel-head">
        <span className="panel-title">Satellites</span>
        <span className="muted">{satellites.length}</span>
      </div>

      {satellites.map((sat) => {
        const subs = expanded[sat.id];
        const open = Boolean(subs);
        const filter = (filters[sat.id] ?? "").toLowerCase();
        const visible = open
          ? subs.filter(
              (s) =>
                !filter ||
                s.code.toLowerCase().includes(filter) ||
                (s.name ?? "").toLowerCase().includes(filter)
            )
          : [];
        const allSelected =
          visible.length > 0 && visible.every((s) => selected.has(s.id));

        return (
          <div key={sat.id} className="tree-branch">
            <button
              className={`tree-node ${open ? "open" : ""}`}
              onClick={() => toggleSatellite(sat)}
            >
              <span className="caret" aria-hidden="true">
                {open ? "\u25be" : "\u25b8"}
              </span>
              <span className="tree-node-name">{sat.designator}</span>
              {sat.launch_date && (
                <span
                  className="muted tree-node-meta"
                  title={`Launched ${sat.launch_date}`}
                >
                  launched {sat.launch_date.slice(0, 4)}
                </span>
              )}
            </button>

            {open && (
              <div className="subsystem-block">
                <div className="subsystem-search">
                  <span className="finder-icon" aria-hidden="true">
                    &#9906;
                  </span>
                  <input
                    placeholder={`Filter ${subs.length} subsystems`}
                    value={filters[sat.id] ?? ""}
                    onChange={(e) =>
                      setFilters({ ...filters, [sat.id]: e.target.value })
                    }
                    aria-label={`Filter subsystems on ${sat.designator}`}
                  />
                  {filters[sat.id] && (
                    <button
                      className="chip-btn"
                      onClick={() => setFilters({ ...filters, [sat.id]: "" })}
                      title="Clear filter"
                    >
                      &times;
                    </button>
                  )}
                </div>

                <div className="subsystem-actions">
                  <button
                    className={`link-btn ${allSelected ? "on" : ""}`}
                    onClick={() =>
                      onSelectSubsystems(
                        allSelected ? [] : visible.map((s) => s.id),
                        sat
                      )
                    }
                  >
                    {allSelected ? "Clear all" : "Select all"}
                  </button>
                </div>

                {visible.map((sub) => (
                  <button
                    key={sub.id}
                    className={`subsystem-row ${selected.has(sub.id) ? "on" : ""}`}
                    onMouseDown={(event) => {
                      if (event.shiftKey) event.preventDefault();
                    }}
                    onClick={(event) => clickSubsystem(event, sub, sat, visible)}
                    title={sub.name ?? sub.code}
                  >
                    <span className="subsystem-tag">{sub.code}</span>
                    <span className="subsystem-name">{sub.name ?? ""}</span>
                    <span className="count-pill">{sub.channel_count ?? 0}</span>
                  </button>
                ))}

                {visible.length === 0 && (
                  <div className="muted finder-empty">
                    No subsystem matches "{filters[sat.id]}".
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}