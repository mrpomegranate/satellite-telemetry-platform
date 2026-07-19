import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { Label, Series } from "../../api/client";

// ECharts is enough because the API caps points per channel. Aggregate tiers
// carry min/q05/q95/max, drawn as a translucent envelope behind the mean.
export function TelemetryChart({
  series,
  labels,
  onBrush,
}: {
  series: Series[];
  labels: Label[];
  onBrush?: (start: Date, end: Date) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, "dark", { renderer: "canvas" });
    chartRef.current = chart;
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const dataSeries: echarts.SeriesOption[] = [];

    series.forEach((s) => {
      const hasEnvelope = s.points.some((p) => p.lo !== null && p.hi !== null);

      if (hasEnvelope) {
        // Band drawn as a floor plus a stacked delta with area fill.
        dataSeries.push({
          name: `${s.mnemonic} lo`,
          type: "line",
          data: s.points.map((p) => [p.t, p.lo]),
          lineStyle: { opacity: 0 },
          stack: `band-${s.channel_id}`,
          symbol: "none",
          silent: true,
          tooltip: { show: false },
        });
        dataSeries.push({
          name: `${s.mnemonic} band`,
          type: "line",
          data: s.points.map((p) => [
            p.t,
            p.hi !== null && p.lo !== null ? p.hi - p.lo : null,
          ]),
          lineStyle: { opacity: 0 },
          areaStyle: { opacity: 0.15 },
          stack: `band-${s.channel_id}`,
          symbol: "none",
          silent: true,
          tooltip: { show: false },
        });
      }

      dataSeries.push({
        name: s.mnemonic,
        type: "line",
        data: s.points.map((p) => [p.t, p.v]),
        symbol: "none",
        sampling: "lttb",
        lineStyle: { width: 1.4 },
        connectNulls: false, // gaps are real; do not bridge them
        markArea: labels.length
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

    chart.setOption(
      {
        backgroundColor: "transparent",
        animation: false,
        grid: { left: 60, right: 24, top: 30, bottom: 60 },
        legend: {
          data: series.map((s) => s.mnemonic),
          textStyle: { color: "#9c9a92" },
          top: 0,
        },
        tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
        xAxis: { type: "time", axisLine: { lineStyle: { color: "#2e2e28" } } },
        yAxis: {
          type: "value",
          scale: true,
          splitLine: { lineStyle: { color: "#2e2e28" } },
        },
        dataZoom: [
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
      { replaceMerge: ["series"] }
    );

    const handler = (params: any) => {
      const area = params?.areas?.[0];
      if (!area || !onBrush) return;
      const [a, b] = area.coordRange ?? [];
      if (a != null && b != null) onBrush(new Date(a), new Date(b));
    };
    chart.off("brushEnd");
    chart.on("brushEnd", handler);
  }, [series, labels, onBrush]);

  return <div ref={ref} style={{ width: "100%", height: "100%" }} />;
}
