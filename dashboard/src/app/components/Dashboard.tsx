"use client";

import React, { useEffect, useMemo, useState } from "react";
import Chart from "./Chart";
import type { MetricsResponse, SpreadPoint, PositionPoint } from "../lib/types";

const ranges = [
  { key: "5m", label: "5分钟" },
  { key: "15m", label: "15分钟" },
  { key: "60m", label: "60分钟" },
  { key: "4h", label: "4小时" },
  { key: "8h", label: "8小时" },
  { key: "1d", label: "1天" },
  { key: "7d", label: "7天" },
];

function formatPct(value?: number) {
  if (value === undefined || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(3)}%`;
}

export default function Dashboard() {
  const [range, setRange] = useState("60m");
  const [symbol, setSymbol] = useState("ETH");
  const [data, setData] = useState<MetricsResponse | null>(null);
  const [connected, setConnected] = useState(false);
  const [zoom, setZoom] = useState<{ start?: number; end?: number }>({});

  useEffect(() => {
    let aborted = false;
    fetch(`/api/metrics?range=${range}&symbol=${symbol}`)
      .then((res) => res.json())
      .then((json: MetricsResponse) => {
        if (!aborted) setData(json);
      })
      .catch(() => undefined);
    return () => {
      aborted = true;
    };
  }, [range, symbol]);

  useEffect(() => {
    const es = new EventSource(`/api/stream?symbol=${symbol}`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { spread?: SpreadPoint; position?: PositionPoint };
        setData((prev) => {
          if (!prev) return prev;
          const spreads = payload.spread ? [...prev.spreads, payload.spread] : prev.spreads;
          const positions = payload.position ? [...prev.positions, payload.position] : prev.positions;
          return { ...prev, spreads, positions, latest: payload };
        });
      } catch {
        // ignore malformed
      }
    };
    return () => es.close();
  }, [symbol]);

  const spreadSeries = useMemo(() => data?.spreads ?? [], [data]);
  const positionSeries = useMemo(() => data?.positions ?? [], [data]);

  const latestSpread = data?.latest?.spread ?? spreadSeries[spreadSeries.length - 1];
  const latestPosition = data?.latest?.position ?? positionSeries[positionSeries.length - 1];
  const extTotal = latestPosition?.extTotal ?? 0;
  const ligTotal = latestPosition?.ligTotal ?? 0;
  const totalSum = extTotal + ligTotal;

  const buildDataZoom = (len: number) => {
    if (len < 2) return [];
    return [
      {
        type: "inside",
        xAxisIndex: 0,
        zoomOnMouseWheel: true,
        moveOnMouseWheel: true,
        start: zoom.start,
        end: zoom.end,
      },
    ];
  };

  const onZoom = (params: unknown) => {
    const p = params as { start?: number; end?: number };
    if (typeof p.start === "number" && typeof p.end === "number") {
      setZoom({ start: p.start, end: p.end });
    }
  };

  const spreadOption = useMemo(() => {
    const labels = spreadSeries.map((p) => p.t);
    return {
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#c7d6ce" } },
      grid: { left: 30, right: 30, top: 30, bottom: 30 },
      dataZoom: buildDataZoom(labels.length),
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: "#90a39a" },
        boundaryGap: false,
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: "#90a39a",
          formatter: (val: number) => `${(val * 100).toFixed(2)}%`,
        },
        splitLine: { lineStyle: { color: "#1e2722" } },
      },
      series: [
        {
          name: "开仓价差",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.open),
          lineStyle: { color: "#6fe3a1" },
        },
        {
          name: "平仓价差",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.close),
          lineStyle: { color: "#5bb2ff" },
        },
        {
          name: "中轴",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.mid),
          lineStyle: { color: "#9aa7ff", type: "dashed" },
        },
        {
          name: "上轨",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.upper),
          lineStyle: { color: "#ffb86b", type: "dotted" },
        },
        {
          name: "下轨",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.lower),
          lineStyle: { color: "#ff7a7a", type: "dotted" },
        },
      ],
    };
  }, [spreadSeries, zoom]);

  const positionOption = useMemo(() => {
    const labels = positionSeries.map((p) => p.t);
    return {
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#c7d6ce" } },
      grid: { left: 30, right: 30, top: 30, bottom: 30 },
      dataZoom: buildDataZoom(labels.length),
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: "#90a39a" },
        boundaryGap: false,
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#90a39a" },
        splitLine: { lineStyle: { color: "#1e2722" } },
      },
      series: [
        {
          name: "Ext仓位",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.ext),
          lineStyle: { color: "#6fe3a1" },
        },
        {
          name: "Lig仓位",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.lig),
          lineStyle: { color: "#5bb2ff" },
        },
      ],
    };
  }, [positionSeries, zoom]);

  const totalBalanceOption = useMemo(() => {
    const labels = positionSeries.map((p) => p.t);
    return {
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#c7d6ce" } },
      grid: { left: 30, right: 40, top: 30, bottom: 30 },
      dataZoom: buildDataZoom(labels.length),
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: "#90a39a" },
        boundaryGap: false,
      },
      yAxis: [
        {
          type: "value",
          axisLabel: { color: "#90a39a" },
          splitLine: { lineStyle: { color: "#1e2722" } },
        },
        {
          type: "value",
          axisLabel: {
            color: "#90a39a",
            formatter: (val: number) => `${(val * 100).toFixed(2)}%`,
          },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "Ext总金额",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.extTotal ?? 0),
          lineStyle: { color: "#6fe3a1" },
        },
        {
          name: "Lig总金额",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.ligTotal ?? 0),
          lineStyle: { color: "#5bb2ff" },
        },
        {
          name: "合计",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => (p.extTotal ?? 0) + (p.ligTotal ?? 0)),
          lineStyle: { color: "#ffb86b" },
        },
        {
          name: "当前利润率",
          type: "line",
          smooth: true,
          yAxisIndex: 1,
          data: positionSeries.map((p) => p.profitRate ?? 0),
          lineStyle: { color: "#c77dff" },
        },
      ],
    };
  }, [positionSeries, zoom]);

  return (
    <main>
      <div className="grid grid-2">
        <div>
          <h1>套利监控台</h1>
          <p className="muted">实时价差、仓位、布林带与收益概览</p>
        </div>
        <div className="panel">
          <div className="controls">
            {ranges.map((r) => (
              <button
                key={r.key}
                className={range === r.key ? "active" : ""}
                onClick={() => setRange(r.key)}
              >
                {r.label}
              </button>
            ))}
            <button className={connected ? "active" : ""}>{connected ? "实时连接" : "断开"}</button>
          </div>
        </div>
      </div>

      <div className="grid grid-3" style={{ marginTop: 16 }}>
        <div className="panel kpi">
          <div className="label">实时开仓价差</div>
          <div className="value">{formatPct(latestSpread?.open)}</div>
        </div>
        <div className="panel kpi">
          <div className="label">实时平仓价差</div>
          <div className="value">{formatPct(latestSpread?.close)}</div>
        </div>
        <div className="panel kpi">
          <div className="label">实时利润率</div>
          <div className="value">
            {formatPct(
              latestSpread && latestSpread.close !== undefined
                ? (latestSpread.open ?? 0) - (latestSpread.close ?? 0)
                : undefined
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <div className="panel">
          <h3>价差 + 布林带</h3>
          <Chart option={spreadOption} onEvents={{ datazoom: onZoom }} />
        </div>
        <div className="panel">
          <h3>两边仓位变化</h3>
          <Chart option={positionOption} onEvents={{ datazoom: onZoom }} />
        </div>
      </div>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <div className="panel">
          <h3>两边总金额</h3>
          <div className="grid grid-3">
            <div className="kpi">
              <div className="label">Extended 总金额</div>
              <div className="value">{extTotal.toFixed(2)}</div>
            </div>
            <div className="kpi">
              <div className="label">Lighter 总金额</div>
              <div className="value">{ligTotal.toFixed(2)}</div>
            </div>
            <div className="kpi">
              <div className="label">合计</div>
              <div className="value">{totalSum.toFixed(2)}</div>
            </div>
          </div>
          <p className="muted" style={{ marginTop: 8 }}>每1分钟采样一次</p>
        </div>
        <div className="panel">
          <h3>总金额趋势（{ranges.find((r) => r.key === range)?.label ?? range}）</h3>
          <Chart option={totalBalanceOption} onEvents={{ datazoom: onZoom }} />
        </div>
      </div>

      <div className="grid" style={{ marginTop: 16 }}>
        <div className="panel kpi">
          <div className="label">Symbol</div>
          <div className="value">{symbol}</div>
        </div>
      </div>
    </main>
  );
}
