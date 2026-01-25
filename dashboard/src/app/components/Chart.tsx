"use client";

import dynamic from "next/dynamic";
import React from "react";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export default function Chart({ option, height = 320 }: { option: object; height?: number }) {
  return (
    <ReactECharts
      option={option}
      style={{ height }}
      opts={{ renderer: "canvas" }}
      notMerge={true}
      lazyUpdate={true}
      onEvents={{}}
      // Enable data zoom by mouse wheel inside chart
      // ECharts listens to dataZoom inside option; we keep this here for future hooks
    />
  );
}
