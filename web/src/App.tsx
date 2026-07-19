import { useCallback, useEffect, useState } from "react";
import { CatalogTree } from "./features/catalog/CatalogTree";
import { ChannelFinder } from "./features/catalog/ChannelFinder";
import { TelemetryChart } from "./features/chart/TelemetryChart";
import { LabelPanel } from "./features/labeling/LabelPanel";
import { api, type Channel, type Label, type Series } from "./api/client";

export default function App() {
  const [subsystemId, setSubsystemId] = useState<string | undefined>();
  const [selected, setSelected] = useState<Channel[]>([]);
  const [series, setSeries] = useState<Series[]>([]);
  const [labels, setLabels] = useState<Label[]>([]);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const [selection, setSelection] = useState<{ start: Date; end: Date } | null>(null);
  const [tier, setTier] = useState<string>("");

  // Frame the initial view from the first selected channel's extent.
  useEffect(() => {
    if (!selected.length) {
      setSeries([]);
      setRange(null);
      return;
    }
    api.extent(selected[0].id).then((e) => {
      if (e.first && e.last) setRange({ start: e.first, end: e.last });
    });
  }, [selected]);

  useEffect(() => {
    if (!selected.length || !range) return;
    api
      .timeseries(selected.map((c) => c.id), range.start, range.end)
      .then((res) => {
        setSeries(res.series);
        setTier(res.tier);
      })
      .catch(() => setSeries([]));
  }, [selected, range]);

  const reloadLabels = useCallback(() => {
    if (!groupId || !range) return;
    api.labels(groupId, range.start, range.end).then(setLabels).catch(() => setLabels([]));
  }, [groupId, range]);

  useEffect(reloadLabels, [reloadLabels]);

  function toggleChannel(c: Channel) {
    setSelected((prev) =>
      prev.some((x) => x.id === c.id)
        ? prev.filter((x) => x.id !== c.id)
        : [...prev, c]
    );
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <CatalogTree
          selectedId={subsystemId}
          onSelectSubsystem={(sub) => setSubsystemId(sub.id)}
        />
        <ChannelFinder
          subsystemId={subsystemId}
          selected={selected}
          onToggle={toggleChannel}
        />
      </aside>

      <main className="main">
        <div className="toolbar">
          {selected.length === 0 && (
            <span className="muted">pick channels from the finder</span>
          )}
          {selected.map((c) => (
            <span key={c.id} className="chip">
              {c.mnemonic}
              <button
                style={{ padding: "0 4px", border: "none", background: "none" }}
                onClick={() => toggleChannel(c)}
              >
                &times;
              </button>
            </span>
          ))}
          {tier && <span className="muted">tier: {tier}</span>}
        </div>

        <div className="toolbar">
          <LabelPanel
            selection={selection}
            groupId={groupId}
            onSaved={() => {
              setSelection(null);
              reloadLabels();
            }}
          />
        </div>

        <div className="chart-wrap">
          {series.length ? (
            <TelemetryChart
              series={series}
              labels={labels}
              onBrush={(start, end) => setSelection({ start, end })}
            />
          ) : (
            <div className="muted" style={{ padding: 24 }}>
              no data loaded
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
