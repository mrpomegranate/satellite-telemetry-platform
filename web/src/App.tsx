import { useCallback, useEffect, useState } from "react";
import { CatalogTree } from "./features/catalog/CatalogTree";
import { ChannelFinder } from "./features/catalog/ChannelFinder";
import { ChartPanes, type ChartLayout } from "./features/chart/ChartPanes";
import { type BandMode } from "./features/chart/TelemetryChart";
import { LabelPanel } from "./features/labeling/LabelPanel";
import { useTheme } from "./theme";
import { api, type Channel, type Label, type Series } from "./api/client";

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [subsystemId, setSubsystemId] = useState<string | undefined>();
  const [selected, setSelected] = useState<Channel[]>([]);
  const [series, setSeries] = useState<Series[]>([]);
  const [labels, setLabels] = useState<Label[]>([]);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const [selection, setSelection] = useState<{ start: Date; end: Date } | null>(null);
  const [clearToken, setClearToken] = useState(0);
  const [tier, setTier] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [bandMode, setBandMode] = useState<BandMode>("quantile");
  const [showLine, setShowLine] = useState(true);
  const [layout, setLayout] = useState<ChartLayout>("overlay");
  const [axisFor, setAxisFor] = useState<Record<string, 0 | 1>>({});
  const [zoomed, setZoomed] = useState(false);
  const [resetZoomToken, setResetZoomToken] = useState(0);

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
    setLoading(true);
    api
      .timeseries(selected.map((c) => c.id), range.start, range.end)
      .then((res) => {
        setSeries(res.series);
        setTier(res.tier);
      })
      .catch(() => setSeries([]))
      .finally(() => setLoading(false));
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

  function flipAxis(channelId: string) {
    setAxisFor((prev) => ({ ...prev, [channelId]: prev[channelId] === 1 ? 0 : 1 }));
  }

  function clearSelection() {
    setSelection(null);
    setClearToken((t) => t + 1);
  }

  const hasData = series.length > 0;

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
        {/* Row 1: what is plotted, and the primary action */}
        <div className="toolbar toolbar-primary">
          <div className="chips">
            {selected.length === 0 ? (
              <span className="muted">No channels selected</span>
            ) : (
              selected.map((c) => (
                <span key={c.id} className="chip">
                  {c.mnemonic}
                  {layout === "overlay" && (
                    <button
                      className="chip-btn"
                      title="Move to the other Y axis"
                      onClick={() => flipAxis(c.id)}
                    >
                      {axisFor[c.id] === 1 ? "R" : "L"}
                    </button>
                  )}
                  <button
                    className="chip-btn"
                    title="Remove from chart"
                    onClick={() => toggleChannel(c)}
                  >
                    &times;
                  </button>
                </span>
              ))
            )}
          </div>

          <span className="spacer" />

          {loading && <span className="muted">loading\u2026</span>}

          {zoomed && (
            <button
              onClick={() => setResetZoomToken((t) => t + 1)}
              title="Show the full time range again"
            >
              Reset zoom
            </button>
          )}

          {hasData && !selection && (
            <span className="hint">
              Drag across the chart to select a time window
            </span>
          )}
        </div>

        {/* Row 2: display options, grouped and labelled */}
        <div className="toolbar toolbar-options">
          <div className="control-group">
            <span className="control-label">Layout</span>
            <div className="seg">
              {(
                [
                  ["overlay", "One chart"],
                  ["stacked", "Split"],
                ] as [ChartLayout, string][]
              ).map(([mode, text]) => (
                <button
                  key={mode}
                  className={layout === mode ? "active" : ""}
                  onClick={() => setLayout(mode)}
                >
                  {text}
                </button>
              ))}
            </div>
          </div>

          <div className="control-group">
            <span className="control-label">Shaded band</span>
            <div className="seg">
              {(
                [
                  ["quantile", "5\u201395%"],
                  ["minmax", "Min/max"],
                  ["none", "Off"],
                ] as [BandMode, string][]
              ).map(([mode, text]) => (
                <button
                  key={mode}
                  className={bandMode === mode ? "active" : ""}
                  onClick={() => setBandMode(mode)}
                >
                  {text}
                </button>
              ))}
            </div>
          </div>

          <div className="control-group">
            <span className="control-label">Mean line</span>
            <div className="seg">
              <button
                className={showLine ? "active" : ""}
                onClick={() => setShowLine(true)}
              >
                Show
              </button>
              <button
                className={!showLine ? "active" : ""}
                onClick={() => setShowLine(false)}
              >
                Hide
              </button>
            </div>
          </div>

          <span className="spacer" />

          {tier && (
            <span className="badge" title="Resolution chosen for this time window">
              {tier} resolution
            </span>
          )}

          <button
            className="icon-btn"
            onClick={toggleTheme}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            aria-label="Toggle theme"
          >
            {theme === "dark" ? "\u263c" : "\u263e"}
          </button>
        </div>

        {/* Row 3: selection and labeling, only when relevant */}
        {selection && (
          <div className="toolbar toolbar-selection">
            <>
                <span className="badge badge-accent">
                  {selection.start.toISOString().slice(0, 16).replace("T", " ")}
                  {"  \u2192  "}
                  {selection.end.toISOString().slice(0, 16).replace("T", " ")}
                </span>
                <LabelPanel
                  selection={selection}
                  groupId={groupId}
                  onSaved={() => {
                    clearSelection();
                    reloadLabels();
                  }}
                />
              <span className="spacer" />
              <button onClick={clearSelection}>Clear</button>
            </>
          </div>
        )}

        <div className="chart-wrap">
          <ChartPanes
            series={series}
            labels={labels}
            theme={theme}
            layout={layout}
            bandMode={bandMode}
            showLine={showLine}
            axisFor={axisFor}
            clearToken={clearToken}
            resetZoomToken={resetZoomToken}
            onZoomChange={setZoomed}
            onBrush={(start, end) => setSelection({ start, end })}
          />
        </div>
      </main>
    </div>
  );
}