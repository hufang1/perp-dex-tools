import { NextRequest, NextResponse } from "next/server";
import { prisma } from "../../lib/db";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body || !body.symbol) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }

  const symbol = String(body.symbol);
  const tasks: Promise<unknown>[] = [];

  if (body.spread) {
    const s = body.spread;
    tasks.push(
      prisma.spreadSample.create({
        data: {
          symbol,
          openSpread: s.open,
          closeSpread: s.close,
          midline: s.mid,
          upper: s.upper,
          lower: s.lower,
          extBid: s.extBid,
          extAsk: s.extAsk,
          ligBid: s.ligBid,
          ligAsk: s.ligAsk,
        },
      })
    );
  }

  if (body.position) {
    const p = body.position;
    tasks.push(
      prisma.positionSnapshot.create({
        data: {
          symbol,
          extQty: p.extQty,
          ligQty: p.ligQty,
          extAvailUsd: p.extAvailUsd,
          ligAvailUsd: p.ligAvailUsd,
          extTotalUsd: p.extTotalUsd ?? 0,
          ligTotalUsd: p.ligTotalUsd ?? 0,
          extVolume: p.extVolume ?? 0,
          ligVolume: p.ligVolume ?? 0,
          totalVolume: p.totalVolume ?? 0,
        },
      })
    );
  }

  if (body.event) {
    const e = body.event;
    tasks.push(
      prisma.botEvent.create({
        data: {
          symbol,
          level: e.level ?? "info",
          eventType: e.type ?? "event",
          message: e.message ?? "",
          state: e.state ?? null,
        },
      })
    );
  }

  if (body.pnl) {
    const p = body.pnl;
    tasks.push(
      prisma.pnlSnapshot.create({
        data: {
          symbol,
          profit: p.profit,
          cumulative: p.cumulative,
          entrySpread: p.entry_spread ?? 0,
          closeSpread: p.close_spread ?? 0,
          idealRate: p.ideal_rate ?? 0,
          actualRate: p.actual_rate ?? 0,
        },
      })
    );
  }

  await Promise.all(tasks);

  return NextResponse.json({ ok: true });
}
