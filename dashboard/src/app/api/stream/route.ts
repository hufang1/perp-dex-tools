import { prisma } from "../../lib/db";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = searchParams.get("symbol") ?? "ETH";
  const encoder = new TextEncoder();

  let lastSpreadId = 0;
  let lastPositionId = 0;
  let closed = false;

  const stream = new ReadableStream({
    async start(controller) {
      const push = (data: unknown) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));
        } catch {
          closed = true;
        }
      };

      const tick = async () => {
        try {
          const [spread, position, pnl] = await Promise.all([
            prisma.spreadSample.findFirst({
              where: { symbol, id: { gt: lastSpreadId } },
              orderBy: { id: "desc" },
            }),
            prisma.positionSnapshot.findFirst({
              where: { symbol, id: { gt: lastPositionId } },
              orderBy: { id: "desc" },
            }),
            prisma.pnlSnapshot.findFirst({
              where: { symbol },
              orderBy: { id: "desc" },
            }),
          ]);

          const payload: { spread?: object; position?: object; pnl?: object } = {};
          if (spread) {
            lastSpreadId = spread.id;
            payload.spread = {
              t: spread.createdAt.toISOString(),
              open: Number(spread.openSpread),
              close: Number(spread.closeSpread),
              mid: Number(spread.midline),
              upper: Number(spread.upper),
              lower: Number(spread.lower),
              openMaker: Number(spread.openMakerThreshold ?? 0),
              openTaker: Number(spread.openTakerThreshold ?? 0),
              closeMarket: Number(spread.closeMarketThreshold ?? 0),
              closeLimit: Number(spread.closeLimitThreshold ?? 0),
            };
          }
          if (position) {
            lastPositionId = position.id;
            payload.position = {
              t: position.createdAt.toISOString(),
              ext: Number(position.extQty),
              lig: Number(position.ligQty),
              extAvail: Number(position.extAvailUsd),
              ligAvail: Number(position.ligAvailUsd),
              extTotal: Number(position.extTotalUsd),
              ligTotal: Number(position.ligTotalUsd),
              extVolume: Number(position.extVolume ?? 0),
              ligVolume: Number(position.ligVolume ?? 0),
              totalVolume: Number(position.totalVolume ?? 0),
              extOpenTakerVolume: Number(position.extOpenTakerVolume ?? 0),
              extOpenMakerVolume: Number(position.extOpenMakerVolume ?? 0),
              ligOpenTakerVolume: Number(position.ligOpenTakerVolume ?? 0),
              ligOpenMakerVolume: Number(position.ligOpenMakerVolume ?? 0),
              profitRate: pnl ? Number(pnl.profit) : 0,
            };
          }
          if (pnl) {
            payload.pnl = {
              t: pnl.createdAt.toISOString(),
              entry: Number(pnl.entrySpread),
              close: Number(pnl.closeSpread),
              ideal: Number(pnl.idealRate),
              actual: Number(pnl.actualRate),
              fundsDelta: Number(pnl.fundsDelta ?? 0),
              fundsCum: Number(pnl.fundsCum ?? 0),
              cumulative: Number(pnl.cumulative),
            };
          }
          if (payload.spread || payload.position) {
            push(payload);
          }
        } catch {
          push({});
        }
      };

      const timer = setInterval(tick, 1000);

      // initial ping
      push({});

      request.signal.addEventListener("abort", () => {
        closed = true;
        clearInterval(timer);
      });
    },
    cancel() {
      closed = true;
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
