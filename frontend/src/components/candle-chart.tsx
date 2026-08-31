"use client";

import { useEffect, useRef } from "react";
import { useTheme } from "next-themes";
import {
  createChart,
  CrosshairMode,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import type { OhlcvBar } from "@/lib/api";

export function CandleChart({ data, height = 440 }: { data: OhlcvBar[]; height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const ma20Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma60Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  useEffect(() => {
    if (!containerRef.current) return;

    const chart: IChartApi = createChart(containerRef.current, {
      height,
      layout: {
        textColor: isDark ? "#94a3b8" : "#475569",
        background: { color: "transparent" },
      },
      grid: {
        vertLines: { color: isDark ? "rgba(148,163,184,0.08)" : "rgba(100,116,139,0.10)" },
        horzLines: { color: isDark ? "rgba(148,163,184,0.08)" : "rgba(100,116,139,0.10)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.22 } },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;
    seriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: "#dc2626",
      downColor: "#2563eb",
      borderVisible: false,
      wickUpColor: "#dc2626",
      wickDownColor: "#2563eb",
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });
    ma20Ref.current = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });
    ma60Ref.current = chart.addSeries(LineSeries, {
      color: "#8b5cf6",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });
    volumeRef.current = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);
    handleResize();

    return () => {
      window.removeEventListener("resize", handleResize);
      chartRef.current = null;
      seriesRef.current = null;
      ma20Ref.current = null;
      ma60Ref.current = null;
      volumeRef.current = null;
      chart.remove();
    };
  }, [height, isDark]);

  useEffect(() => {
    if (!seriesRef.current) return;
    const sortedData = Array.from(new Map(data.map((bar) => [bar.date, bar])).values())
      .sort((left, right) => left.date.localeCompare(right.date));
    seriesRef.current.setData(
      sortedData.map((bar) => ({
        time: bar.date,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }))
    );
    ma20Ref.current?.setData(movingAverage(sortedData, 20));
    ma60Ref.current?.setData(movingAverage(sortedData, 60));
    volumeRef.current?.setData(
      sortedData.map((bar) => ({
        time: bar.date,
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(220,38,38,0.28)" : "rgba(37,99,235,0.28)",
      }))
    );
    if (sortedData.length > 0 && containerRef.current) {
      chartRef.current?.timeScale().fitContent();
    }
  }, [data]);

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}

function movingAverage(data: OhlcvBar[], window: number) {
  return data.slice(window - 1).map((bar, index) => {
    const sourceIndex = index + window - 1;
    const values = data.slice(sourceIndex - window + 1, sourceIndex + 1);
    return {
      time: bar.date,
      value: values.reduce((sum, item) => sum + item.close, 0) / window,
    };
  });
}
