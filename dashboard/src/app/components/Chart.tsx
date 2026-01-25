"use client";

import dynamic from "next/dynamic";
import React from "react";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export default function Chart({
  option,
  height = 320,
  onEvents,
}: {
  option: object;
  height?: number;
  onEvents?: Record<string, (params: unknown, chart: unknown) => void>;
}) {
  return (
    <ReactECharts
      option={option}
      style={{ height }}
      opts={{ renderer: "canvas" }}
      notMerge={false}
      lazyUpdate={true}
      onEvents={onEvents ?? {}}
      // Enable data zoom by mouse wheel inside chart
      // ECharts listens to dataZoom inside option; we keep this here for future hooks
    />
  );
}
