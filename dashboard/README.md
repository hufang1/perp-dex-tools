# HufangPerp Dashboard (Next.js)

## Tech stack
- Next.js (App Router)
- Prisma + SQLite
- ECharts (front-end charts)
- SSE for realtime streaming

## Setup
1) Install deps
```
cd dashboard
npm install
```

2) Configure DB
```
cp .env.example .env
npx prisma generate
npx prisma migrate dev --name init
```

3) Start
```
npm run dev
```

## Data ingestion
POST JSON to `/api/ingest`:
```
{
  "symbol": "ETH",
  "spread": {
    "open": 0.0012,
    "close": 0.0009,
    "mid": 0.0010,
    "upper": 0.0016,
    "lower": 0.0005,
    "extBid": 2950.1,
    "extAsk": 2950.5,
    "ligBid": 2954.1,
    "ligAsk": 2954.6
  },
  "position": {
    "extQty": 0.1,
    "ligQty": -0.1,
    "extAvailUsd": 500.0,
    "ligAvailUsd": 420.0
  },
  "event": {
    "level": "info",
    "type": "state",
    "message": "HOLDING",
    "state": "HOLDING"
  },
  "pnl": {
    "profit": 3.2,
    "cumulative": 18.5
  }
}
```

## Metrics API
`/api/metrics?symbol=ETH&range=60m|1d|7d`

## SSE
`/api/stream?symbol=ETH`
