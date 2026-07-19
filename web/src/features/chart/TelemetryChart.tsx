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

export function TelemetryChart({
  series,
  labels,
  theme,
  bandMode = "quantile",
  showLine = true,
  axisFor = {},
  colorOffset = 0,
  compact = false,
  showCaption = true,
  onBrush,
}: {
  series: Series[];
  labels: Label[];
  theme: Theme;
  bandMode?: BandMode;
  /** Hide the mean line to inspect the envelope alone. */
  showLine?: boolean;
  axisFor?: Record<string, 0 | 1>;
  /** Keeps colours stable when several charts each render one channel. */
  colorOffset?: number;
  /** Tighter chrome for stacked panes. */
  compact?: boolean;
  showCaption?: boolean;
  onBrush?: (start: Date, end: Date) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  const bucketSeconds = series[0]?.bucket_seconds ?? null;
  const isAggregate = bucketSeconds != null;

  const lookup = useMemo(() => {
    const map = new Map<string, Map<number, Series["points"][number]>>();
    series.forEach((s) => {
      const inner = new Map<number, Series["points"][number]>();
      s.points.forEach((p) => inner.set(new Date(p.t).getTime(), p));
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
    return () => {
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
    const border = cssVar("--border", "#2e2e28");

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
        // stackStrategy "all" is essential: telemetry crosses zero, and the
        // default strategy stacks negatives and positives separately, which
        // pins the band's floor to zero instead of to value_min.
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
          z: 1,
        });
      }

      dataSeries.push({
        name: s.mnemonic,
        type: "line",
        yAxisIndex: axis,
        data: s.points.map((p) => [p.t, p.v]),
        symbol: "none",
        sampling: "lttb",
        lineStyle: {
          width: 1.4,
          color,
          opacity: showLine ? 1 : 0,
        },
        itemStyle: { color },
        connectNulls: false,
        z: 3,
        markArea:
          index === 0 && labels.length
            ? {
                silent: true,
                itemStyle: { opacity: 0.18 },
                data: labels.map((l) => [
                  {
                    xAxis: l.start,
                    itemStyle: { color: l.color ?? "#993C1D" },
                    name: l.taxonomy_name ?? l.label_class,
                  },
                  { xAxis: l.end },
                ]),
              }
            : undefined,
      });
    });

    const usesRight = Object.values(axisFor).includes(1);

    // Units come from catalog.channel.units; say so plainly when absent.
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
      const startText = new Date(ms).toISOString().replace("T", " ").slice(0, 16);

      let html = `<div style="font-weight:500;margin-bottom:2px">${startText} UTC</div>`;
      if (isAggregate) {
        const endText = new Date(ms + bucketSeconds! * 1000)
          .toISOString()
          .replace("T", " ")
          .slice(11, 16);
        html +=
          `<div style="color:${muted};font-size:11px;margin-bottom:6px">` +
          `covers ${describeBucket(bucketSeconds)} \u2192 ${endText}</div>`;
      }

      series.forEach((s) => {
        const point = lookup.get(s.channel_id)?.get(ms);
        if (!point) return;
        const color = colorOf.get(s.channel_id) ?? "#888";
        html +=
          `<div style="margin-top:6px"><span style="display:inline-block;` +
          `width:8px;height:8px;border-radius:2px;background:${color};` +
          `margin-right:6px"></span>${s.mnemonic}</div>`;

        if (!isAggregate) {
          html += `<div style="margin-left:14px">value ${fmt(point.v, s.units)}</div>`;
          return;
        }

        const rows: [string, number | null | undefined][] = [
          ["max", point.hi],
          ["q95", point.p95],
          ["mean", point.v],
          ["q05", point.p05],
          ["min", point.lo],
        ];
        html += '<table style="margin-left:14px;border-spacing:0">';
        rows.forEach(([name, value]) => {
          const emphasis =
            name === "mean" ? `color:${text};font-weight:500` : `color:${muted}`;
          html +=
            `<tr><td style="padding-right:10px;${emphasis}">${name}</td>` +
            `<td style="${emphasis}">${fmt(value, s.units)}</td></tr>`;
        });
        html += "</table>";
        if (point.n != null) {
          html +=
            `<div style="margin-left:14px;color:${muted};font-size:11px">` +
            `from ${point.n.toLocaleString()} readings</div>`;
        }
      });
      return html;
    }

    chart.setOption(
      {
        backgroundColor: "transparent",
        animation: false,
        grid: {
          left: 64,
          right: usesRight ? 64 : 24,
          top: compact ? 24 : 34,
          bottom: compact ? 28 : 62,
        },
        legend: {
          data: series.map((s) => s.mnemonic),
          textStyle: { color: muted },
          top: 0,
          show: !compact,
        },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "cross" },
          backgroundColor: panel,
          borderColor: border,
          textStyle: { color: text, fontSize: 12 },
          formatter: tooltipFormatter,
        },
        xAxis: {
          type: "time",
          axisLine: { lineStyle: { color: grid } },
          axisLabel: { color: muted, show: !compact },
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
        dataZoom: compact
          ? [{ type: "inside", filterMode: "none" }]
          : [
              { type: "inside", filterMode: "none" },
              { type: "slider", height: 22, bottom: 12 },
            ],
        brush: {
          toolbox: ["lineX", "clear"],
          xAxisIndex: 0,
          throttleType: "debounce",
          throttleDelay: 300,
        },
        series: dataSeries,
      },
      { replaceMerge: ["series", "yAxis"] }
    );

    const handler = (params: any) => {
      const area = params?.areas?.[0];
      if (!area || !onBrush) return;
      const [a, b] = area.coordRange ?? [];
      if (a != null && b != null) onBrush(new Date(a), new Date(b));
    };
    chart.off("brushEnd");
    chart.on("brushEnd", handler);
  }, [
    series,
    labels,
    bandMode,
    showLine,
    axisFor,
    theme,
    onBrush,
    lookup,
    bucketSeconds,
    isAggregate,
    colorOffset,
    compact,
  ]);

  const bandText =
    bandMode === "none"
      ? null
      : bandMode === "minmax"
        ? "shaded band = min to max"
        : "shaded band = 5th to 95th percentile";

  const pointCount = series[0]?.points.length ?? 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div ref={ref} style={{ flex: 1, minHeight: 0 }} />
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