"use client";

import { useEffect, useRef } from "react";
import { useTheme } from "next-themes";
import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

export function EquityChart({
  data,
}: {
  data: { time: string; value: number }[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  useEffect(() => {
    if (!containerRef.current) return;

    const chart: IChartApi = createChart(containerRef.current, {
      height: 280,
      layout: { textColor: isDark ? "#94a3b8" : "#475569", background: { color: "transparent" } },
      grid: {
        vertLines: { color: isDark ? "rgba(148,163,184,0.08)" : "rgba(100,116,139,0.10)" },
        horzLines: { color: isDark ? "rgba(148,163,184,0.08)" : "rgba(100,116,139,0.10)" },
      },
    });
    seriesRef.current = chart.addSeries(LineSeries, {
      color: "#2563eb",
      lineWidth: 2,
    });

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);
    handleResize();

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [isDark]);

  useEffect(() => {
    if (!seriesRef.current) return;
    const valuesBySecond = new Map<number, number>();
    for (const point of data) {
      const timestamp = Math.floor(new Date(point.time).getTime() / 1000);
      if (Number.isFinite(timestamp) && Number.isFinite(point.value)) {
        valuesBySecond.set(timestamp, point.value);
      }
    }
    const chartData = [...valuesBySecond.entries()]
      .sort(([left], [right]) => left - right)
      .map(([time, value]) => ({ time: time as UTCTimestamp, value }));
    seriesRef.current.setData(chartData);
  }, [data, isDark]);

  return <div ref={containerRef} className="w-full" />;
}
