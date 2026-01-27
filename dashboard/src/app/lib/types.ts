export type SpreadPoint = {
  t: string;
  open: number;
  close: number;
  mid: number;
  upper: number;
  lower: number;
  openMaker?: number;
  openTaker?: number;
  openMakerExit?: number;
  closeMarket?: number;
  closeLimit?: number;
  closeLimitExit?: number;
};

export type PositionPoint = {
  t: string;
  ext: number;
  lig: number;
  extAvail: number;
  ligAvail: number;
  extTotal?: number;
  ligTotal?: number;
  extVolume?: number;
  ligVolume?: number;
  totalVolume?: number;
  extOpenTakerVolume?: number;
  extOpenMakerVolume?: number;
  ligOpenTakerVolume?: number;
  ligOpenMakerVolume?: number;
  profitRate?: number;
};

export type MetricsResponse = {
  symbol: string;
  range: string;
  spreads: SpreadPoint[];
  positions: PositionPoint[];
  pnls?: {
    t: string;
    entry: number;
    close: number;
    ideal: number;
    actual: number;
    fundsDelta?: number;
    fundsCum?: number;
    cumulative: number;
  }[];
  latest?: {
    spread?: SpreadPoint;
    position?: PositionPoint;
  };
};
