import { useEffect, useState } from "react";
import { api, type Satellite, type Subsystem } from "../../api/client";

// The tree stops at subsystem on purpose. With thousands of channels per
// satellite the fourth level is a search problem, handled by ChannelFinder.
export function CatalogTree({
  onSelectSubsystem,
  selectedId,
}: {
  onSelectSubsystem: (s: Subsystem, satellite: Satellite) => void;
  selectedId?: string;
}) {
  const [satellites, setSatellites] = useState<Satellite[]>([]);
  const [expanded, setExpanded] = useState<Record<string, Subsystem[]>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.satellites().then(setSatellites).catch((e) => setError(String(e)));
  }, []);

  async function toggle(sat: Satellite) {
    if (expanded[sat.id]) {
      const next = { ...expanded };
      delete next[sat.id];
      setExpanded(next);
      return;
    }
    const subs = await api.subsystems(sat.id);
    setExpanded({ ...expanded, [sat.id]: subs });
  }

  if (error) return <div className="muted">catalog unavailable: {error}</div>;

  return (
    <div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
        Satellites
      </div>
      {satellites.map((sat) => (
        <div key={sat.id}>
          <div className="tree-item" onClick={() => toggle(sat)}>
            {expanded[sat.id] ? "\u25be" : "\u25b8"} {sat.designator}
          </div>
          {expanded[sat.id]?.map((sub) => (
            <div
              key={sub.id}
              className={`tree-item ${selectedId === sub.id ? "active" : ""}`}
              style={{ paddingLeft: 20 }}
              onClick={() => onSelectSubsystem(sub, sat)}
            >
              {sub.code}{" "}
              <span className="muted" style={{ fontSize: 12 }}>
                {sub.channel_count}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}