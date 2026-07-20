import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import type { Label, Series } from "../../api/client";
import type { Theme } from "../../theme";

/** Which envelope to shade behind the mean line. */
export type BandMode = "minmax" | "quantile" | "none";

const PALETTE = [
  "#639922",
  "#378ADD",
  "#C2410C",
  "#7C3AED",
  "#0F766E",
  "#B45309",
];

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value || fallback;
}

/** 21600 -> "6 h", 600 -> "10 min", null -> "raw samples". */
export function describeBucket(seconds: number | null | undefined): string {
  if (seconds == null) return "raw samples";
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

function fmt(value: number | null | undefined, units?: string | null): string {
  if (value == null) return "\u2014";
  const rounded =
    Math.abs(value) >= 1000 ? value.toFixed(0) : Number(value.toPrecision(5));
  return units ? `${rounded} ${units}` : String(rounded);
}

type Prepared = {
  point: Series["points"][number];
  when: string;
  until: string;
};

export interface PendingInterval {
  id: string;
  start: string;
  end: string;
}

export function TelemetryChart({
  series,
  labels,
  intervals = [],
  theme,
  bandMode = "quantile",
  showLine = true,
  axisFor = {},
  colorOffset = 0,
  compact = false,
  showCaption = true,
  clearToken = 0,
  resetZoomToken = 0,
  onBrush,
  onZoomChange,
  onResetView,
}: {
  series: Series[];
  labels: Label[];
  /** Unsaved selections awaiting a label. */
  intervals?: PendingInterval[];
  theme: Theme;
  bandMode?: BandMode;
  showLine?: boolean;
  axisFor?: Record<string, 0 | 1>;
  colorOffset?: number;
  compact?: boolean;
  showCaption?: boolean;
  /** Increment to clear any drawn selection region. */
  clearToken?: number;
  /** Increment to reset the zoom window to full extent. */
  resetZoomToken?: number;
  onBrush?: (start: Date, end: Date) => void;
  onZoomChange?: (zoomed: boolean) => void;
  /** Double-click on the plot: back to the full time range. */
  onResetView?: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  const bucketSeconds = series[0]?.bucket_seconds ?? null;
  const isAggregate = bucketSeconds != null;

  // Timestamps are formatted once here, not on every mouse move. Doing this in
  // the tooltip formatter is the single biggest hover cost.
  const lookup = useMemo(() => {
    const map = new Map<string, Map<number, Prepared>>();
    series.forEach((s) => {
      const span = (s.bucket_seconds ?? 0) * 1000;
      const inner = new Map<number, Prepared>();
      s.points.forEach((p) => {
        const ms = new Date(p.t).getTime();
        inner.set(ms, {
          point: p,
          when: new Date(ms).toISOString().replace("T", " ").slice(0, 16),
          until: span
            ? new Date(ms + span).toISOString().replace("T", " ").slice(11, 16)
            : "",
        });
      });
      map.set(s.channel_id, inner);
    });
    return map;
  }, [series]);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, theme === "dark" ? "dark" : undefined, {
      renderer: "canvas",
    });
    chartRef.current = chart;
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    // Window resize is not enough: the container also shrinks when panels
    // below it grow, and ECharts keeps its old canvas size until told.
    const observer = new ResizeObserver(resize);
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", resize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [theme]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const grid = cssVar("--grid", "#2e2e28");
    const muted = cssVar("--muted", "#9c9a92");
    const text = cssVar("--text", "#e8e6dc");
    const panel = cssVar("--panel", "#1c1c17");
    const panel2 = cssVar("--panel-2", "#232320");
    const border = cssVar("--border", "#2e2e28");
    const accent = cssVar("--accent", "#c96442");

    const dataSeries: echarts.SeriesOption[] = [];
    const colorOf = new Map<string, string>();

    series.forEach((s, index) => {
      const color = PALETTE[(index + colorOffset) % PALETTE.length];
      colorOf.set(s.channel_id, color);
      const axis = axisFor[s.channel_id] ?? 0;

      const lowKey = bandMode === "minmax" ? "lo" : "p05";
      const highKey = bandMode === "minmax" ? "hi" : "p95";
      const hasBand =
        bandMode !== "none" &&
        s.points.some((p) => p[lowKey] !== null && p[highKey] !== null);

      if (hasBand) {
        // stackStrategy "all" keeps the floor at value_min even when negative;
        // the default splits signs and pins the band to zero.
        dataSeries.push({
          name: `${s.mnemonic} __floor`,
          type: "line",
          yAxisIndex: axis,
          data: s.points.map((p) => [p.t, p[lowKey]]),
          lineStyle: { opacity: 0 },
          stack: `band-${s.channel_id}`,
          stackStrategy: "all",
          symbol: "none",
          silent: true,
          tooltip: { show: false },
          legendHoverLink: false,
          animation: false,
          sampling: "lttb",
          z: 1,
        });
        dataSeries.push({
          name: `${s.mnemonic} __band`,
          type: "line",
          yAxisIndex: axis,
          data: s.points.map((p) => {
            const lo = p[lowKey];
            const hi = p[highKey];
            return [p.t, lo !== null && hi !== null ? hi - lo : null];
          }),
          lineStyle: { opacity: 0 },
          areaStyle: { color, opacity: 0.18 },
          stack: `band-${s.channel_id}`,
          stackStrategy: "all",
          symbol: "none",
          silent: true,
          tooltip: { show: false },
          legendHoverLink: false,
          animation: false,
          sampling: "lttb",
          z: 1,
        });
      }

      dataSeries.push({
        name: s.mnemonic,
        type: "line",
        yAxisIndex: axis,
        data: s.points.map((p) => [p.t, p.v]),
        symbol: "circle",
        symbolSize: 6,
        showSymbol: false, // only the hovered point gets a marker
        sampling: "lttb",
        lineStyle: { width: 1.4, color, opacity: showLine ? 1 : 0 },
        itemStyle: { color },
        emphasis: { scale: 1.6, focus: "none" },
        connectNulls: false,
        animation: false,
        z: 3,
        markArea:
          index === 0 && (labels.length || intervals.length)
            ? {
                silent: true,
                data: [
                  // saved labels: solid tint in the taxonomy colour
                  ...labels.map((l) => [
                    {
                      xAxis: l.start,
                      itemStyle: { color: l.color ?? "#993C1D", opacity: 0.18 },
                      name: l.taxonomy_name ?? l.label_class,
                    },
                    { xAxis: l.end },
                  ]),
                  // pending selections: dashed accent outline, clearly unsaved
                  ...intervals.map((iv) => [
                    {
                      xAxis: iv.start,
                      itemStyle: {
                        color: accent,
                        opacity: 0.1,
                        borderColor: accent,
                        borderWidth: 1,
                        borderType: "dashed",
                      },
                    },
                    { xAxis: iv.end },
                  ]),
                ],
              }
            : undefined,
      });
    });

    const usesRight = Object.values(axisFor).includes(1);

    function axisName(index: 0 | 1): string {
      const onAxis = series.filter((s) => (axisFor[s.channel_id] ?? 0) === index);
      if (!onAxis.length) return "";
      const units = new Set(onAxis.map((s) => s.units).filter(Boolean));
      if (units.size === 1) return [...units][0] as string;
      if (units.size > 1) return "mixed units";
      return "no units recorded";
    }

    function tooltipFormatter(params: any): string {
      const list = Array.isArray(params) ? params : [params];
      const stamp = list[0]?.axisValue;
      if (stamp == null) return "";
      const ms = new Date(stamp).getTime();

      const first = lookup.get(series[0]?.channel_id ?? "")?.get(ms);
      let html = `<div style="font-weight:500">${first?.when ?? ""} UTC</div>`;
      if (isAggregate && first?.until) {
        html +=
          `<div style="color:${muted};font-size:11px;margin-bottom:4px">` +
          `covers ${describeBucket(bucketSeconds)} \u2192 ${first.until}</div>`;
      }

      series.forEach((s) => {
        const prepared = lookup.get(s.channel_id)?.get(ms);
        if (!prepared) return;
        const p = prepared.point;
        const color = colorOf.get(s.channel_id) ?? "#888";
        html +=
          `<div style="margin-top:5px"><span style="display:inline-block;` +
          `width:8px;height:8px;border-radius:2px;background:${color};` +
          `margin-right:6px"></span>${s.mnemonic}</div>`;

        if (!isAggregate) {
          html += `<div style="margin-left:14px">value ${fmt(p.v, s.units)}</div>`;
          return;
        }

        const rows: [string, number | null | undefined][] = [
          ["max", p.hi],
          ["q95", p.p95],
          ["mean", p.v],
          ["q05", p.p05],
          ["min", p.lo],
        ];
        html += '<table style="margin-left:14px;border-spacing:0">';
        rows.forEach(([name, value]) => {
          const style =
            name === "mean" ? `color:${text};font-weight:500` : `color:${muted}`;
          html +=
            `<tr><td style="padding-right:10px;${style}">${name}</td>` +
            `<td style="${style}">${fmt(value, s.units)}</td></tr>`;
        });
        html += "</table>";
        if (p.n != null) {
          html +=
            `<div style="margin-left:14px;color:${muted};font-size:11px">` +
            `from ${p.n.toLocaleString()} readings</div>`;
        }
      });
      return html;
    }

    const dayLabel = (value: number) =>
      new Date(value).toISOString().slice(0, 10);

    chart.setOption(
      {
        backgroundColor: "transparent",
        animation: false,
        progressive: 4000,
        progressiveThreshold: 3000,
        // Explicitly off: ECharts otherwise renders small unlabelled brush
        // icons in the corner, which nobody finds.
        toolbox: { show: false },
        grid: {
          left: 64,
          right: usesRight ? 64 : 24,
          top: compact ? 24 : 34,
          bottom: compact ? 30 : 86,
        },
        legend: {
          data: series.map((s) => s.mnemonic),
          textStyle: { color: muted },
          top: 0,
          show: !compact,
        },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "none" },
          triggerOn: "mousemove",
          transitionDuration: 0,
          hideDelay: 40,
          confine: true,
          backgroundColor: panel,
          borderColor: border,
          borderWidth: 1,
          textStyle: { color: text, fontSize: 12 },
          formatter: tooltipFormatter,
        },
        xAxis: {
          type: "time",
          axisLine: { lineStyle: { color: grid } },
          axisTick: { lineStyle: { color: grid } },
          // Year boundaries are drawn larger and brighter than months so the
          // eye can find them without reading every tick.
          splitLine: {
            show: !compact,
            lineStyle: { color: grid, opacity: 0.55, type: "dashed" },
          },
          axisLabel: {
            show: !compact,
            color: muted,
            hideOverlap: true,
            formatter: {
              year: "{yearStyle|{yyyy}}",
              month: "{monthStyle|{MMM}}",
              day: "{dayStyle|{d}}",
              hour: "{dayStyle|{HH}:{mm}}",
              minute: "{dayStyle|{HH}:{mm}}",
              second: "{dayStyle|{HH}:{mm}:{ss}}",
            },
            rich: {
              yearStyle: {
                color: text,
                fontSize: 14,
                fontWeight: "bold",
                padding: [3, 7, 3, 7],
                borderRadius: 4,
                backgroundColor: panel2,
                borderWidth: 1,
                borderColor: border,
              },
              monthStyle: { color: muted, fontSize: 11 },
              dayStyle: { color: muted, fontSize: 11 },
            },
          },
          axisPointer: { show: false },
        },
        yAxis: [
          {
            type: "value",
            scale: true,
            name: axisName(0),
            nameLocation: "end",
            nameGap: 12,
            nameTextStyle: { color: muted, align: "left" },
            splitLine: { lineStyle: { color: grid } },
            axisLabel: { color: muted },
          },
          {
            type: "value",
            scale: true,
            show: usesRight,
            name: axisName(1),
            nameLocation: "end",
            nameGap: 12,
            nameTextStyle: { color: muted, align: "right" },
            splitLine: { show: false },
            axisLabel: { color: muted },
          },
        ],
        // filterMode "filter" drops out-of-range points rather than drawing all
        // of them every frame - the main zoom performance win. The slider is
        // styled heavily because at defaults it is almost invisible.
        dataZoom: compact
          ? [{ type: "inside", filterMode: "filter", moveOnMouseMove: false }]
          : [
              {
                type: "inside",
                filterMode: "filter",
                // Drag belongs to region selection; wheel zooms, slider pans.
                moveOnMouseMove: false,
                zoomOnMouseWheel: true,
              },
              {
                type: "slider",
                filterMode: "filter",
                height: 38,
                bottom: 14,
                borderColor: border,
                backgroundColor: panel2,
                fillerColor: accent + "26",
                dataBackground: {
                  lineStyle: { color: muted, opacity: 0.6, width: 1 },
                  areaStyle: { color: muted, opacity: 0.18 },
                },
                selectedDataBackground: {
                  lineStyle: { color: accent, opacity: 0.9, width: 1 },
                  areaStyle: { color: accent, opacity: 0.28 },
                },
                handleStyle: {
                  color: accent,
                  borderColor: accent,
                  shadowBlur: 0,
                },
                handleSize: "130%",
                moveHandleSize: 6,
                moveHandleStyle: { color: accent, opacity: 0.65 },
                emphasis: {
                  handleStyle: { color: accent, borderColor: accent },
                  moveHandleStyle: { color: accent, opacity: 1 },
                },
                textStyle: { color: muted, fontSize: 11 },
                labelFormatter: dayLabel,
                brushSelect: false,
              },
            ],
        brush: {
          xAxisIndex: 0,
          toolbox: [],
          throttleType: "debounce",
          throttleDelay: 200,
          brushStyle: {
            borderWidth: 1,
            borderColor: accent,
            color: accent + "2e",
          },
        },
        series: dataSeries,
      },
      // dataZoom is deliberately NOT in replaceMerge: replacing it resets the
      // zoom window to full extent on every re-render.
      { replaceMerge: ["series", "yAxis"] }
    );

    const brushHandler = (params: any) => {
      const area = params?.areas?.[0];
      if (!area || !onBrush) return;
      const [a, b] = area.coordRange ?? [];
      if (a != null && b != null) onBrush(new Date(a), new Date(b));
    };
    chart.off("brushEnd");
    chart.on("brushEnd", brushHandler);

    const zoomHandler = () => {
      if (!onZoomChange) return;
      const opt = chart.getOption() as any;
      const dz = opt?.dataZoom?.[0];
      if (!dz) return;
      const full = (dz.start ?? 0) <= 0.5 && (dz.end ?? 100) >= 99.5;
      onZoomChange(!full);
    };
    chart.off("datazoom");
    chart.on("datazoom", zoomHandler);

    const zr = chart.getZr();
    zr.off("dblclick");
    if (onResetView) zr.on("dblclick", () => onResetView());
  }, [
    series,
    labels,
    intervals,
    bandMode,
    showLine,
    axisFor,
    theme,
    onBrush,
    onZoomChange,
    onResetView,
    lookup,
    bucketSeconds,
    isAggregate,
    colorOffset,
    compact,
  ]);

  // Region selection is always available: for time series the only useful
  // brush is a horizontal time range, so there is no mode to switch into.
  // Band series are silent, so hit-testing stays cheap.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.dispatchAction({
      type: "takeGlobalCursor",
      key: "brush",
      brushOption: { brushType: "lineX", brushMode: "single" },
    });
  }, [series, theme]);

  // Clearing from outside (the Clear button) wipes the drawn region.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || clearToken === 0) return;
    chart.dispatchAction({ type: "brush", areas: [] });
  }, [clearToken]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || resetZoomToken === 0) return;
    chart.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
    onZoomChange?.(false);
  }, [resetZoomToken, onZoomChange]);

  const bandText =
    bandMode === "none"
      ? null
      : bandMode === "minmax"
        ? "shaded band = min to max"
        : "shaded band = 5th to 95th percentile";

  const pointCount = series[0]?.points.length ?? 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div
        ref={ref}
        style={{ flex: 1, minHeight: 0, cursor: "crosshair" }}
      />
      {showCaption && (
        <div className="caption">
          {showLine && (
            <>
              <span className="swatch-line" aria-hidden="true" />
              <span>line = mean</span>
            </>
          )}
          {bandText && (
            <>
              <span className="swatch-band" aria-hidden="true" />
              <span>{bandText}</span>
            </>
          )}
          <span className="dot" aria-hidden="true">
            &middot;
          </span>
          <span>
            each point summarises {describeBucket(bucketSeconds)}
            {isAggregate ? " of telemetry" : ""}
          </span>
          {pointCount > 0 && (
            <>
              <span className="dot" aria-hidden="true">
                &middot;
              </span>
              <span>{pointCount.toLocaleString()} points</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}