"use client";

import dynamic from "next/dynamic";
import React from "react";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export default function Chart({ option, height = 320 }: { option: object; height?: number }) {
  return <ReactECharts option={option} style={{ height }} />;
}
