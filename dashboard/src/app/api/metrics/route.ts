import { NextRequest, NextResponse } from "next/server";
import { prisma } from "../../lib/db";

function rangeToDate(range: string): Date {
  const now = Date.now();
  if (range === "5m") return new Date(now - 5 * 60 * 1000);
  if (range === "15m") return new Date(now - 15 * 60 * 1000);
  if (range === "7d") return new Date(now - 7 * 24 * 60 * 60 * 1000);
  if (range === "1d") return new Date(now - 24 * 60 * 60 * 1000);
  if (range === "4h") return new Date(now - 4 * 60 * 60 * 1000);
  if (range === "8h") return new Date(now - 8 * 60 * 60 * 1000);
  return new Date(now - 60 * 60 * 1000);
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const range = searchParams.get("range") ?? "60m";
  const symbol = searchParams.get("symbol") ?? "ETH";
  const startParam = searchParams.get("start");
  const endParam = searchParams.get("end");
  const start = startParam ? new Date(startParam) : rangeToDate(range);
  const end = endParam ? new Date(endParam) : new Date();

  const [spreads, positions, pnls] = await Promise.all([
    prisma.spreadSample.findMany({
      where: { symbol, createdAt: { gte: start, lte: end } },
      orderBy: { createdAt: "asc" },
      take: 5000,
    }),
    prisma.positionSnapshot.findMany({
      where: { symbol, createdAt: { gte: start, lte: end } },
      orderBy: { createdAt: "asc" },
      take: 5000,
    }),
    prisma.pnlSnapshot.findMany({
      where: { symbol, createdAt: { gte: start, lte: end } },
      orderBy: { createdAt: "asc" },
      take: 5000,
    }),
  ]);

  const response = {
    symbol,
    range,
    spreads: spreads.map((s) => ({
      t: s.createdAt.toISOString(),
      open: Number(s.openSpread),
      close: Number(s.closeSpread),
      mid: Number(s.midline),
      upper: Number(s.upper),
      lower: Number(s.lower),
    })),
    positions: positions.map((p, idx) => ({
      t: p.createdAt.toISOString(),
      ext: Number(p.extQty),
      lig: Number(p.ligQty),
      extAvail: Number(p.extAvailUsd),
      ligAvail: Number(p.ligAvailUsd),
      extTotal: Number(p.extTotalUsd),
      ligTotal: Number(p.ligTotalUsd),
      profitRate: pnls[idx] ? Number(pnls[idx].profit) : 0,
    })),
    pnls: pnls.map((p) => ({
      t: p.createdAt.toISOString(),
      entry: Number(p.entrySpread),
      close: Number(p.closeSpread),
      ideal: Number(p.idealRate),
      actual: Number(p.actualRate),
      cumulative: Number(p.cumulative),
    })),
  };

  return NextResponse.json(response);
}
