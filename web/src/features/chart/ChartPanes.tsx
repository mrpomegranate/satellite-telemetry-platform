import {
  TelemetryChart,
  type BandMode,
  type PendingInterval,
} from "./TelemetryChart";
import type { Label, Series } from "../../api/client";
import type { Theme } from "../../theme";

export type ChartLayout = "overlay" | "stacked";

/**
 * Overlay puts every channel on one plot - right for comparing shapes and
 * spotting relationships. Split gives each channel its own pane and Y scale -
 * right when values differ by orders of magnitude, which is usual across
 * subsystems.
 *
 * A saved telemetry group is a named set of channels plus this arrangement, so
 * these panes are what a group renders as once groups are wired up.
 */
export function ChartPanes({
  series,
  labels,
  intervals = [],
  theme,
  layout,
  bandMode,
  showLine,
  axisFor,
  clearToken = 0,
  resetZoomToken = 0,
  onBrush,
  onZoomChange,
  onResetView,
}: {
  series: Series[];
  labels: Label[];
  intervals?: PendingInterval[];
  theme: Theme;
  layout: ChartLayout;
  bandMode: BandMode;
  showLine: boolean;
  axisFor: Record<string, 0 | 1>;
  clearToken?: number;
  resetZoomToken?: number;
  onBrush?: (start: Date, end: Date) => void;
  onZoomChange?: (zoomed: boolean) => void;
  onResetView?: () => void;
}) {
  if (!series.length) {
    return (
      <div className="empty-state">
        <div className="empty-title">No channels selected</div>
        <div className="muted">
          Pick a subsystem on the left, then choose channels to plot.
        </div>
      </div>
    );
  }

  if (layout === "overlay") {
    return (
      <TelemetryChart
        series={series}
        labels={labels}
        intervals={intervals}
        theme={theme}
        bandMode={bandMode}
        showLine={showLine}
        axisFor={axisFor}
        clearToken={clearToken}
        resetZoomToken={resetZoomToken}
        onBrush={onBrush}
        onZoomChange={onZoomChange}
        onResetView={onResetView}
      />
    );
  }

  return (
    <div className="panes">
      {series.map((s, index) => (
        <div className="pane" key={s.channel_id}>
          <div className="pane-title">
            {s.mnemonic}
            {s.units ? <span className="muted"> ({s.units})</span> : null}
          </div>
          <div className="pane-chart">
            <TelemetryChart
              series={[s]}
              labels={labels}
              intervals={intervals}
              theme={theme}
              bandMode={bandMode}
              showLine={showLine}
              colorOffset={index}
              compact
              showCaption={false}
              clearToken={clearToken}
              onBrush={onBrush}
              onResetView={onResetView}
            />
          </div>
        </div>
      ))}
    </div>
  );
}