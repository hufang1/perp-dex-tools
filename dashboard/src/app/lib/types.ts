export type SpreadPoint = {
  t: string;
  open: number;
  close: number;
  mid: number;
  upper: number;
  lower: number;
};

export type PositionPoint = {
  t: string;
  ext: number;
  lig: number;
  extAvail: number;
  ligAvail: number;
};

export type MetricsResponse = {
  symbol: string;
  range: string;
  spreads: SpreadPoint[];
  positions: PositionPoint[];
  latest?: {
    spread?: SpreadPoint;
    position?: PositionPoint;
  };
};
