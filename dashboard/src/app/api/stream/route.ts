import { prisma } from "@/app/lib/db";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = searchParams.get("symbol") ?? "ETH";
  const encoder = new TextEncoder();

  let lastSpreadId = 0;
  let lastPositionId = 0;

  const stream = new ReadableStream({
    async start(controller) {
      const push = (data: unknown) => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));
      };

      const tick = async () => {
        try {
          const [spread, position] = await Promise.all([
            prisma.spreadSample.findFirst({
              where: { symbol, id: { gt: lastSpreadId } },
              orderBy: { id: "desc" },
            }),
            prisma.positionSnapshot.findFirst({
              where: { symbol, id: { gt: lastPositionId } },
              orderBy: { id: "desc" },
            }),
          ]);

          const payload: { spread?: object; position?: object } = {};
          if (spread) {
            lastSpreadId = spread.id;
            payload.spread = {
              t: spread.createdAt.toISOString(),
              open: Number(spread.openSpread),
              close: Number(spread.closeSpread),
              mid: Number(spread.midline),
              upper: Number(spread.upper),
              lower: Number(spread.lower),
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

      controller.signal?.addEventListener("abort", () => {
        clearInterval(timer);
      });
    },
    cancel() {
      // no-op
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
