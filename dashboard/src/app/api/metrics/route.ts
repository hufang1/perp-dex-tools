import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/app/lib/db";

function rangeToDate(range: string): Date {
  const now = Date.now();
  if (range === "7d") return new Date(now - 7 * 24 * 60 * 60 * 1000);
  if (range === "1d") return new Date(now - 24 * 60 * 60 * 1000);
  return new Date(now - 60 * 60 * 1000);
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const range = searchParams.get("range") ?? "60m";
  const symbol = searchParams.get("symbol") ?? "ETH";
  const since = rangeToDate(range);

  const [spreads, positions] = await Promise.all([
    prisma.spreadSample.findMany({
      where: { symbol, createdAt: { gte: since } },
      orderBy: { createdAt: "asc" },
      take: 5000,
    }),
    prisma.positionSnapshot.findMany({
      where: { symbol, createdAt: { gte: since } },
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
    positions: positions.map((p) => ({
      t: p.createdAt.toISOString(),
      ext: Number(p.extQty),
      lig: Number(p.ligQty),
      extAvail: Number(p.extAvailUsd),
      ligAvail: Number(p.ligAvailUsd),
    })),
  };

  return NextResponse.json(response);
}
