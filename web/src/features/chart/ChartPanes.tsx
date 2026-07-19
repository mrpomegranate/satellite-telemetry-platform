import { TelemetryChart, type BandMode } from "./TelemetryChart";
import type { Label, Series } from "../../api/client";
import type { Theme } from "../../theme";

export type ChartLayout = "overlay" | "stacked";

/**
 * Overlay puts every channel on one plot - right for comparing shapes and
 * spotting relationships. Stacked gives each channel its own pane and its own
 * Y scale - right when the values differ by orders of magnitude, which is the
 * usual case across subsystems.
 *
 * A saved telemetry group is just a named set of channels plus this layout, so
 * the panes here are what a group renders as when groups are wired up.
 */
export function ChartPanes({
  series,
  labels,
  theme,
  layout,
  bandMode,
  showLine,
  axisFor,
  onBrush,
}: {
  series: Series[];
  labels: Label[];
  theme: Theme;
  layout: ChartLayout;
  bandMode: BandMode;
  showLine: boolean;
  axisFor: Record<string, 0 | 1>;
  onBrush?: (start: Date, end: Date) => void;
}) {
  if (!series.length) {
    return (
      <div className="muted" style={{ padding: 24 }}>
        no data loaded
      </div>
    );
  }

  if (layout === "overlay") {
    return (
      <TelemetryChart
        series={series}
        labels={labels}
        theme={theme}
        bandMode={bandMode}
        showLine={showLine}
        axisFor={axisFor}
        onBrush={onBrush}
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
              theme={theme}
              bandMode={bandMode}
              showLine={showLine}
              colorOffset={index}
              compact
              showCaption={false}
              onBrush={onBrush}
            />
          </div>
        </div>
      ))}
    </div>
  );
}