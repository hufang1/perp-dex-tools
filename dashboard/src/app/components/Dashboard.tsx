"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import Chart from "./Chart";
import type { MetricsResponse, SpreadPoint, PositionPoint, LogEntry } from "../lib/types";

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
  const [logRange, setLogRange] = useState("5m");
  const [logLevel, setLogLevel] = useState("ALL");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logCursor, setLogCursor] = useState<string | null>(null);
  const [logLoading, setLogLoading] = useState(false);
  const [logAuto, setLogAuto] = useState(true);

  const logRangeToMs = (key: string) => {
    if (key === "5m") return 5 * 60 * 1000;
    if (key === "10m") return 10 * 60 * 1000;
    if (key === "15m") return 15 * 60 * 1000;
    if (key === "60m") return 60 * 60 * 1000;
    return 10 * 60 * 1000;
  };
  const rangeToMs = (key: string) => {
    if (key === "5m") return 5 * 60 * 1000;
    if (key === "15m") return 15 * 60 * 1000;
    if (key === "60m") return 60 * 60 * 1000;
    if (key === "4h") return 4 * 60 * 60 * 1000;
    if (key === "8h") return 8 * 60 * 60 * 1000;
    if (key === "1d") return 24 * 60 * 60 * 1000;
    if (key === "7d") return 7 * 24 * 60 * 60 * 1000;
    return 60 * 60 * 1000;
  };

  useEffect(() => {
    let aborted = false;
    const params = new URLSearchParams({ range, symbol });
    fetch(`/api/metrics?${params.toString()}`)
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
        const payload = JSON.parse(event.data) as {
          spread?: SpreadPoint;
          position?: PositionPoint;
          pnl?: { t: string; entry: number; close: number; ideal: number; actual: number; cumulative: number };
        };
        setData((prev) => {
          if (!prev) return prev;
          const windowStart = Date.now() - rangeToMs(range);
          const withinWindow = (t: string) => new Date(t).getTime() >= windowStart;
          const spreads = (payload.spread ? [...prev.spreads, payload.spread] : prev.spreads).filter((p) =>
            withinWindow(p.t)
          );
          const positions = (payload.position ? [...prev.positions, payload.position] : prev.positions).filter((p) =>
            withinWindow(p.t)
          );
          const pnls = (payload.pnl ? [...(prev.pnls ?? []), payload.pnl] : prev.pnls)?.filter((p) =>
            withinWindow(p.t)
          );
          return { ...prev, spreads, positions, pnls, latest: payload };
        });
      } catch {
        // ignore malformed
      }
    };
    return () => es.close();
  }, [symbol, range]);

  useEffect(() => {
    setZoom({});
  }, [range, symbol]);

  const fetchLogWindow = () => {
    const to = new Date();
    const from = new Date(to.getTime() - logRangeToMs(logRange));
    const params = new URLSearchParams({
      from: from.toISOString(),
      to: to.toISOString(),
      limit: "400",
    });
    if (logLevel !== "ALL") {
      params.set("levels", logLevel);
    }
    setLogLoading(true);
    fetch(`/api/logs?${params.toString()}`)
      .then((res) => res.json())
      .then((json: { items: LogEntry[]; nextCursor?: string | null }) => {
        setLogs(json.items ?? []);
        setLogCursor(json.nextCursor ?? null);
      })
      .catch(() => undefined)
      .finally(() => setLogLoading(false));
  };

  const fetchLogHistory = () => {
    if (!logCursor) return;
    const params = new URLSearchParams({
      before: logCursor,
      limit: "400",
    });
    if (logLevel !== "ALL") {
      params.set("levels", logLevel);
    }
    setLogLoading(true);
    fetch(`/api/logs?${params.toString()}`)
      .then((res) => res.json())
      .then((json: { items: LogEntry[]; nextCursor?: string | null }) => {
        const items = json.items ?? [];
        setLogs((prev) => [...prev, ...items]);
        setLogCursor(json.nextCursor ?? null);
      })
      .catch(() => undefined)
      .finally(() => setLogLoading(false));
  };

  useEffect(() => {
    fetchLogWindow();
  }, [logRange, logLevel]);

  useEffect(() => {
    if (!logAuto) return;
    const timer = setInterval(fetchLogWindow, 3000);
    return () => clearInterval(timer);
  }, [logRange, logAuto, logLevel]);

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
        formatter: (params: Array<{ seriesName: string; value: number; axisValue?: string }>) => {
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
        {
          name: "挂单开仓进场价差",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.openMaker ?? 0),
          lineStyle: { color: "#ffd479", type: "dashed" },
        },
        {
          name: "挂单开仓离场价差",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.openMakerExit ?? 0),
          lineStyle: { color: "#f9c74f", type: "dotted" },
        },
        {
          name: "市价开仓价差",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.openTaker ?? 0),
          lineStyle: { color: "#ff8aa0", type: "dashed" },
        },
        {
          name: "市价平仓价差",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.closeMarket ?? 0),
          lineStyle: { color: "#7bdff2", type: "dashed" },
        },
        {
          name: "挂单平仓进场价差",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.closeLimit ?? 0),
          lineStyle: { color: "#b8f2e6", type: "dashed" },
        },
        {
          name: "挂单平仓离场价差",
          type: "line",
          smooth: true,
          data: spreadSeries.map((p) => p.closeLimitExit ?? 0),
          lineStyle: { color: "#a0e7e5", type: "dotted" },
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

  const volumeOption = useMemo(() => {
    const labels = positionSeries.map((p) => p.t);
    const totalFunds = positionSeries.map((p) => (p.extTotal ?? 0) + (p.ligTotal ?? 0));
    return {
      tooltip: {
        trigger: "axis",
        formatter: (params: Array<{ seriesName: string; value: number; axisValue?: string | number }>) => {
          if (!Array.isArray(params) || params.length === 0) return "";
          const header = params[0]?.axisValue ?? "";
          const lines = params.map((p) => {
            if (String(p.seriesName).includes("(USDT)")) {
              return `${p.seriesName}: ${Number(p.value).toFixed(2)}`;
            }
            return `${p.seriesName}: ${Number(p.value).toFixed(4)}`;
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
        axisLabel: { color: "#90a39a" },
        splitLine: { lineStyle: { color: "#1e2722" } },
      },
      series: [
        {
          name: "总金额(USDT)",
          type: "line",
          smooth: true,
          data: totalFunds,
          lineStyle: { color: "#6fe3a1" },
        },
        {
          name: "Ext交易量(USDT)",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.extVolume ?? 0),
          lineStyle: { color: "#5bb2ff" },
        },
        {
          name: "Lig交易量(USDT)",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.ligVolume ?? 0),
          lineStyle: { color: "#ffb86b" },
        },
        {
          name: "交易量总和(USDT)",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.totalVolume ?? 0),
          lineStyle: { color: "#c77dff" },
        },
        {
          name: "Ext市价开仓量(USDT)",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.extOpenTakerVolume ?? 0),
          lineStyle: { color: "#7bdff2" },
        },
        {
          name: "Ext挂单开仓量(USDT)",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.extOpenMakerVolume ?? 0),
          lineStyle: { color: "#b8f2e6" },
        },
        {
          name: "Lig市价开仓量(USDT)",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.ligOpenTakerVolume ?? 0),
          lineStyle: { color: "#ffc9de" },
        },
        {
          name: "Lig挂单开仓量(USDT)",
          type: "line",
          smooth: true,
          data: positionSeries.map((p) => p.ligOpenMakerVolume ?? 0),
          lineStyle: { color: "#ffe5d9" },
        },
      ],
    };
  }, [positionSeries, zoom]);

  const pnlOption = useMemo(() => {
    const labels = pnlSeries.map((p) => p.t);
    const totalFundsSeries = positionSeries.map((p) => (p.extTotal ?? 0) + (p.ligTotal ?? 0));
    const tradeFundsDeltaSeries = pnlSeries.map((p) => p.fundsDelta ?? 0);
    const tradeFundsCumSeries = pnlSeries.map((p) => p.fundsCum ?? 0);
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
          data: totalFundsSeries,
          lineStyle: { color: "#7bdff2" },
        },
        {
          name: "单笔实际收益(USDT)",
          type: "line",
          smooth: true,
          yAxisIndex: 1,
          data: tradeFundsDeltaSeries,
          lineStyle: { color: "#5bb2ff" },
        },
        {
          name: "累计实际收益(USDT)",
          type: "line",
          smooth: true,
          yAxisIndex: 1,
          data: tradeFundsCumSeries,
          lineStyle: { color: "#ffb86b" },
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
        <div className="panel">
          <h3>总仓位 + 交易量</h3>
          <Chart option={volumeOption} onEvents={{ datazoom: onZoom }} />
        </div>
      </div>

      <div className="grid" style={{ marginTop: 16 }}>
        <div className="panel kpi">
          <div className="label">Symbol</div>
          <div className="value">{symbol}</div>
        </div>
      </div>

      <div className="grid" style={{ marginTop: 16 }}>
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>实时日志</h3>
              <p className="muted">默认展示最近时间窗，点击查看历史加载更早记录</p>
            </div>
            <div className="controls">
              {[
                { key: "5m", label: "5分钟" },
                { key: "10m", label: "10分钟" },
                { key: "15m", label: "15分钟" },
                { key: "60m", label: "1小时" },
              ].map((r) => (
                <button
                  key={r.key}
                  className={logRange === r.key ? "active" : ""}
                  onClick={() => setLogRange(r.key)}
                >
                  {r.label}
                </button>
              ))}
              <button onClick={() => setLogAuto((prev) => !prev)} className={logAuto ? "active" : ""}>
                {logAuto ? "自动刷新" : "已暂停"}
              </button>
              <button onClick={fetchLogHistory} disabled={!logCursor || logLoading}>
                查看历史
              </button>
            </div>
          </div>
          <LogList items={logs} loading={logLoading} />
        </div>
      </div>
    </main>
  );
}

function LogList({ items, loading }: { items: LogEntry[]; loading: boolean }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const rowHeight = 22;
  const height = 320;
  const total = items.length;

  const onScroll = () => {
    if (!containerRef.current) return;
    setScrollTop(containerRef.current.scrollTop);
  };

  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 4);
  const visibleCount = Math.ceil(height / rowHeight) + 8;
  const end = Math.min(total, start + visibleCount);
  const offsetTop = start * rowHeight;
  const offsetBottom = (total - end) * rowHeight;

  return (
    <div className="log-panel">
      <div
        className="log-list"
        ref={containerRef}
        style={{ height }}
        onScroll={onScroll}
      >
        <div style={{ paddingTop: offsetTop, paddingBottom: offsetBottom }}>
          {items.slice(start, end).map((item, idx) => (
            <div key={`${item.ts}-${idx}`} className={`log-row level-${item.level.toLowerCase()}`}>
              <span className="log-time">{formatTimeLabel(item.ts)}</span>
              <span className="log-level">{item.level}</span>
              <span className="log-logger">{item.logger}</span>
              <span className="log-msg">{item.message}</span>
            </div>
          ))}
        </div>
      </div>
      {loading && <div className="log-status muted">加载中...</div>}
      {!loading && total === 0 && <div className="log-status muted">暂无日志</div>}
    </div>
  );
}
              {[
                { key: "ALL", label: "全部" },
                { key: "ERROR", label: "错误" },
                { key: "WARNING", label: "告警" },
                { key: "INFO", label: "信息" },
                { key: "DEBUG", label: "调试" },
              ].map((r) => (
                <button
                  key={r.key}
                  className={logLevel === r.key ? "active" : ""}
                  onClick={() => setLogLevel(r.key)}
                >
                  {r.label}
                </button>
              ))}
