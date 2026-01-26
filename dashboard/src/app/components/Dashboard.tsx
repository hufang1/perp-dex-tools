"use client";

import React, { useEffect, useMemo, useState } from "react";
import Chart from "./Chart";
import type { MetricsResponse, SpreadPoint, PositionPoint } from "../lib/types";
import { DateTimePicker } from "./DateTimePicker";

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

function formatTimeLabel(iso: string) {
  const d = new Date(iso);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${mm}:${dd} ${hh}:${mi}:${ss}`;
}

export default function Dashboard() {
  const [range, setRange] = useState("60m");
  const [symbol, setSymbol] = useState("ETH");
  const [data, setData] = useState<MetricsResponse | null>(null);
  const [connected, setConnected] = useState(false);
  const [zoom, setZoom] = useState<{ start?: number; end?: number }>({});
  const [startAt, setStartAt] = useState<Date | undefined>(undefined);
  const [endAt, setEndAt] = useState<Date | undefined>(undefined);

  useEffect(() => {
    let aborted = false;
    const params = new URLSearchParams({ range, symbol });
    if (startAt) params.set("start", startAt.toISOString());
    if (endAt) params.set("end", endAt.toISOString());
    fetch(`/api/metrics?${params.toString()}`)
      .then((res) => res.json())
      .then((json: MetricsResponse) => {
        if (!aborted) setData(json);
      })
      .catch(() => undefined);
    return () => {
      aborted = true;
    };
  }, [range, symbol, startAt, endAt]);

  useEffect(() => {
    const es = new EventSource(`/api/stream?symbol=${symbol}`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as {
          spread?: SpreadPoint;
          position?: PositionPoint;
          pnl?: { t: string; entry: number; close: number; ideal: number; actual: number; cumulative: number };
        };
        setData((prev) => {
          if (!prev) return prev;
          const spreads = payload.spread ? [...prev.spreads, payload.spread] : prev.spreads;
          const positions = payload.position ? [...prev.positions, payload.position] : prev.positions;
          const pnls = payload.pnl ? [...(prev.pnls ?? []), payload.pnl] : prev.pnls;
          return { ...prev, spreads, positions, pnls, latest: payload };
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
  const pnlSeries = useMemo(() => data?.pnls ?? [], [data]);
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
      tooltip: {
        trigger: "axis",
        formatter: (params: Array<{ seriesName: string; value: number }>) => {
          if (!Array.isArray(params) || params.length === 0) return "";
          const header = params[0]?.axisValue ?? "";
          const lines = params.map((p) => {
            if (p.seriesName === "总资金(USDT)") {
              return `${p.seriesName}: ${Number(p.value).toFixed(2)}`;
            }
            return `${p.seriesName}: ${(Number(p.value) * 100).toFixed(3)}%`;
          });
          return [header, ...lines].join("<br/>");
        },
      },
      legend: { textStyle: { color: "#c7d6ce" } },
      grid: { left: 30, right: 30, top: 30, bottom: 30 },
      dataZoom: buildDataZoom(labels.length),
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: "#90a39a", formatter: (value: string) => formatTimeLabel(value) },
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
      tooltip: {
        trigger: "axis",
        valueFormatter: (val: number) => `${(val * 100).toFixed(3)}%`,
      },
      legend: { textStyle: { color: "#c7d6ce" } },
      grid: { left: 30, right: 30, top: 30, bottom: 30 },
      dataZoom: buildDataZoom(labels.length),
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: "#90a39a", formatter: (value: string) => formatTimeLabel(value) },
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
      tooltip: {
        trigger: "axis",
        valueFormatter: (val: number) => `${(val * 100).toFixed(3)}%`,
      },
      legend: { textStyle: { color: "#c7d6ce" } },
      grid: { left: 30, right: 40, top: 30, bottom: 30 },
      dataZoom: buildDataZoom(labels.length),
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: "#90a39a", formatter: (value: string) => formatTimeLabel(value) },
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

  const pnlOption = useMemo(() => {
    const labels = pnlSeries.map((p) => p.t);
    return {
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#c7d6ce" } },
      grid: { left: 30, right: 40, top: 30, bottom: 30 },
      dataZoom: buildDataZoom(labels.length),
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: "#90a39a", formatter: (value: string) => formatTimeLabel(value) },
        boundaryGap: false,
      },
      yAxis: [
        {
          type: "value",
          axisLabel: {
            color: "#90a39a",
            formatter: (val: number) => `${(val * 100).toFixed(2)}%`,
          },
          splitLine: { lineStyle: { color: "#1e2722" } },
        },
        {
          type: "value",
          axisLabel: { color: "#90a39a" },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "平均开仓价差",
          type: "line",
          smooth: true,
          data: pnlSeries.map((p) => p.entry),
          lineStyle: { color: "#6fe3a1" },
        },
        {
          name: "当前平仓价差",
          type: "line",
          smooth: true,
          data: pnlSeries.map((p) => p.close),
          lineStyle: { color: "#5bb2ff" },
        },
        {
          name: "理想收益率",
          type: "line",
          smooth: true,
          data: pnlSeries.map((p) => p.ideal),
          lineStyle: { color: "#ffb86b" },
        },
        {
          name: "实际收益率",
          type: "line",
          smooth: true,
          data: pnlSeries.map((p) => p.actual),
          lineStyle: { color: "#c77dff" },
        },
        {
          name: "总资金(USDT)",
          type: "line",
          smooth: true,
          yAxisIndex: 1,
          data: positionSeries.map((p) => (p.extTotal ?? 0) + (p.ligTotal ?? 0)),
          lineStyle: { color: "#7bdff2" },
        },
      ],
    };
  }, [pnlSeries, positionSeries, zoom]);

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
            <DateTimePicker value={startAt} onChange={setStartAt} placeholder="开始时间" />
            <DateTimePicker value={endAt} onChange={setEndAt} placeholder="结束时间" />
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

      <div className="grid" style={{ marginTop: 16 }}>
        <div className="panel">
          <h3>价差 + 布林带</h3>
          <Chart option={spreadOption} onEvents={{ datazoom: onZoom }} />
        </div>
      </div>

      <div className="grid" style={{ marginTop: 16 }}>
        <div className="panel">
          <h3>开仓/平仓价差 + 收益率 + 总资金</h3>
          <Chart option={pnlOption} onEvents={{ datazoom: onZoom }} />
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
