import { useCallback, useEffect, useMemo, useState } from "react";
import { Splitter } from "./components/Splitter";
import { CatalogTree } from "./features/catalog/CatalogTree";
import { ChannelFinder } from "./features/catalog/ChannelFinder";
import { ChartPanes, type ChartLayout } from "./features/chart/ChartPanes";
import { type BandMode, type PendingInterval } from "./features/chart/TelemetryChart";
import { GroupPicker } from "./features/groups/GroupPicker";
import { FindingsPanel } from "./features/findings/FindingsPanel";
import { IntervalPanel } from "./features/intervals/IntervalPanel";
import { useTheme } from "./theme";
import { api, type Channel, type Group, type Label, type Series } from "./api/client";

let intervalSeq = 0;

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [subsystemIds, setSubsystemIds] = useState<string[]>([]);
  const [selected, setSelected] = useState<Channel[]>([]);
  const [series, setSeries] = useState<Series[]>([]);
  const [labels, setLabels] = useState<Label[]>([]);
  const [group, setGroup] = useState<Group | null>(null);
  const groupId = group?.id ?? null;
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  // Full extent of the data, kept so the view can always be restored.
  const [fullRange, setFullRange] = useState<{ start: string; end: string } | null>(null);
  const [intervals, setIntervals] = useState<PendingInterval[]>([]);
  const [clearToken, setClearToken] = useState(0);
  const [tier, setTier] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [bandMode, setBandMode] = useState<BandMode>("quantile");
  const [showLine, setShowLine] = useState(true);
  const [layout, setLayout] = useState<ChartLayout>("overlay");
  const [axisFor, setAxisFor] = useState<Record<string, 0 | 1>>({});
  const [zoomed, setZoomed] = useState(false);
  const [emptyChannels, setEmptyChannels] = useState<string[]>([]);
  // Pane sizes are user-adjustable; clamped so neither pane can vanish.
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [panelHeight, setPanelHeight] = useState(230);
  const [resetZoomToken, setResetZoomToken] = useState(0);
  // Tabs rather than stacking: the chart is the reason anyone is here, and two
  // stacked panels take the height it needs.
  const [panelTab, setPanelTab] = useState<"findings" | "intervals">("findings");

  // Frame the view from the union of every selected channel's extent. Asking
  // only the first one breaks as soon as it is a catalog row with no samples
  // (the demo seed, or a channel whose tier has not been ingested).
  useEffect(() => {
    if (!selected.length) {
      setSeries([]);
      setRange(null);
      setFullRange(null);
      setEmptyChannels([]);
      return;
    }
    let cancelled = false;
    Promise.all(
      selected.map((c) =>
        api
          .extent(c.id)
          .then((e) => ({ channel: c, extent: e }))
          .catch(() => ({ channel: c, extent: null }))
      )
    ).then((results) => {
      if (cancelled) return;
      const withData = results.filter((r) => r.extent?.first && r.extent?.last);
      setEmptyChannels(
        results.filter((r) => !r.extent?.first).map((r) => r.channel.mnemonic)
      );
      if (!withData.length) {
        setSeries([]);
        setRange(null);
        setFullRange(null);
        return;
      }
      const start = withData
        .map((r) => r.extent!.first as string)
        .sort()[0];
      const end = withData
        .map((r) => r.extent!.last as string)
        .sort()
        .slice(-1)[0];
      setRange({ start, end });
      setFullRange({ start, end });
    });
    return () => {
      cancelled = true;
    };
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

  // Memoised: an inline arrow here changes identity every render, which
  // re-runs the chart's setOption effect and used to reset the zoom window.
  const handleBrush = useCallback((start: Date, end: Date) => {
    setIntervals((prev) => [
      ...prev,
      {
        id: `iv-${++intervalSeq}`,
        start: start.toISOString(),
        end: end.toISOString(),
      },
    ]);
    setClearToken((t) => t + 1); // wipe the drawn box; the panel owns it now
  }, []);

  const handleZoomChange = useCallback((value: boolean) => setZoomed(value), []);

  const resetView = useCallback(() => {
    if (fullRange) setRange(fullRange);
    setResetZoomToken((t) => t + 1);
  }, [fullRange]);

  const updateInterval = useCallback(
    (id: string, patch: Partial<PendingInterval>) =>
      setIntervals((prev) =>
        prev.map((iv) => (iv.id === id ? { ...iv, ...patch } : iv))
      ),
    []
  );

  const removeInterval = useCallback(
    (id: string) => setIntervals((prev) => prev.filter((iv) => iv.id !== id)),
    []
  );

  const clearIntervals = useCallback(() => setIntervals([]), []);

  const zoomToInterval = useCallback((iv: PendingInterval) => {
    setRange({ start: iv.start, end: iv.end });
  }, []);

  // Zooming to a label's exact bounds is useless twice over: a six-hour region
  // fills the screen with none of the behaviour it is supposed to contrast
  // against, and a window that narrow makes the API reach for a finer tier
  // that may not be ingested, so the chart comes back empty. Two weeks either
  // side keeps the 6h tier in play and still centres the event.
  const zoomToLabel = useCallback(
    (label: Label) => {
      const from = new Date(label.start).getTime();
      const to = new Date(label.end).getTime();
      const pad = Math.max(3 * (to - from), 14 * 24 * 3600 * 1000);
      const lo = fullRange ? new Date(fullRange.start).getTime() : -Infinity;
      const hi = fullRange ? new Date(fullRange.end).getTime() : Infinity;
      setRange({
        start: new Date(Math.max(lo, from - pad)).toISOString(),
        end: new Date(Math.min(hi, to + pad)).toISOString(),
      });
    },
    [fullRange]
  );

  // Loading a group replaces the chart contents rather than adding to them:
  // a group is a working set, and merging it into whatever was already there
  // would make "what am I looking at" unanswerable. Real Channel rows are
  // fetched because group members carry no subsystem, which the finder needs.
  const loadGroup = useCallback(async (next: Group) => {
    setGroup(next);
    const wanted = new Set(next.members.map((m) => m.channel_id));
    try {
      const all = await api.channels({ satellite_id: next.satellite_id });
      setSelected(all.filter((c) => wanted.has(c.id)));
    } catch {
      setSelected([]);
    }
    setAxisFor(
      Object.fromEntries(
        next.members.map((m) => [m.channel_id, (m.axis === 1 ? 1 : 0) as 0 | 1])
      )
    );
  }, []);

  const clearGroup = useCallback(() => {
    setGroup(null);
    setLabels([]);
  }, []);

  const setManyChannels = useCallback((channels: Channel[], on: boolean) => {
    setSelected((prev) => {
      if (on) {
        const have = new Set(prev.map((c) => c.id));
        return [...prev, ...channels.filter((c) => !have.has(c.id))];
      }
      const drop = new Set(channels.map((c) => c.id));
      return prev.filter((c) => !drop.has(c.id));
    });
  }, []);

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

  const resizeSidebar = useCallback(
    (delta: number) =>
      setSidebarWidth((w) => Math.min(560, Math.max(190, w + delta))),
    []
  );

  const resizePanel = useCallback(
    (delta: number) =>
      setPanelHeight((h) =>
        Math.min(window.innerHeight - 320, Math.max(72, h - delta))
      ),
    []
  );

  const hasData = series.length > 0;
  const validIntervals = useMemo(
    () => intervals.filter((iv) => new Date(iv.end) > new Date(iv.start)),
    [intervals]
  );

  return (
    <div
      className="layout"
      style={{ gridTemplateColumns: `${sidebarWidth}px 4px 1fr` }}
    >
      <aside className="sidebar">
        <GroupPicker
          selected={selected}
          activeGroup={group}
          onLoad={loadGroup}
          onClear={clearGroup}
        />
        <CatalogTree
          selectedIds={subsystemIds}
          onSelectSubsystems={(ids) => setSubsystemIds(ids)}
        />
        <ChannelFinder
          subsystemIds={subsystemIds}
          selected={selected}
          onToggle={toggleChannel}
          onSetMany={setManyChannels}
        />
      </aside>

      <Splitter
        orientation="vertical"
        onResize={resizeSidebar}
        onDoubleClick={() => setSidebarWidth(280)}
      />

      <main className="main">
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

          {emptyChannels.length > 0 && (
            <span
              className="badge badge-warn"
              title={`No telemetry ingested for: ${emptyChannels.join(", ")}`}
            >
              {emptyChannels.length} channel
              {emptyChannels.length === 1 ? "" : "s"} with no data
            </span>
          )}

          {hasData && (
            <span className="hint">
              Drag to add an interval &middot; double-click to reset view
            </span>
          )}

          {(zoomed || (fullRange && range && range.start !== fullRange.start)) && (
            <button onClick={resetView} title="Back to the full time range">
              Reset view
            </button>
          )}
        </div>

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

        <div className="chart-wrap">
          <ChartPanes
            series={series}
            labels={labels}
            intervals={validIntervals}
            theme={theme}
            layout={layout}
            bandMode={bandMode}
            showLine={showLine}
            axisFor={axisFor}
            clearToken={clearToken}
            resetZoomToken={resetZoomToken}
            onZoomChange={handleZoomChange}
            onResetView={resetView}
            onBrush={handleBrush}
            onLabelClick={zoomToLabel}
          />
        </div>

        <Splitter
          orientation="horizontal"
          onResize={resizePanel}
          onDoubleClick={() => setPanelHeight(230)}
        />

        <div className="panel-tabs">
          <button
            className={panelTab === "findings" ? "active" : ""}
            onClick={() => setPanelTab("findings")}
          >
            Findings{labels.length ? ` (${labels.length})` : ""}
          </button>
          <button
            className={panelTab === "intervals" ? "active" : ""}
            onClick={() => setPanelTab("intervals")}
          >
            Time intervals{intervals.length ? ` (${intervals.length})` : ""}
          </button>
        </div>

        {panelTab === "findings" ? (
          <FindingsPanel
            height={panelHeight}
            labels={labels}
            onZoomTo={zoomToLabel}
            onReviewed={reloadLabels}
          />
        ) : (
          <IntervalPanel
            height={panelHeight}
            intervals={intervals}
            onChange={updateInterval}
            onRemove={removeInterval}
            onClearAll={clearIntervals}
            onZoomTo={zoomToInterval}
          />
        )}
      </main>
    </div>
  );
}