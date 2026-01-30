import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

export const runtime = "nodejs";

async function firstExistingPath(candidates: string[]): Promise<string | null> {
  for (const candidate of candidates) {
    try {
      const stat = await fs.stat(candidate);
      if (stat.isFile()) return candidate;
    } catch {
      // ignore
    }
  }
  return null;
}

type LogEntry = {
  ts: string;
  level: string;
  logger: string;
  message: string;
  raw: string;
};

function parseTimestamp(value?: string | null): Date | null {
  if (!value) return null;
  if (/^\d+$/.test(value)) {
    const ms = Number(value);
    if (!Number.isNaN(ms)) return new Date(ms);
  }
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d;
}

function parseLogLine(line: string): LogEntry | null {
  const match = line.match(
    /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - (.+?) - ([A-Z]+) - (.*)$/
  );
  if (!match) return null;
  const [, tsRaw, logger, level, message] = match;
  const ts = new Date(tsRaw.replace(" ", "T"));
  if (Number.isNaN(ts.getTime())) return null;
  return {
    ts: ts.toISOString(),
    level,
    logger,
    message,
    raw: line,
  };
}

async function listLogFiles(basePath: string): Promise<string[]> {
  const dir = path.dirname(basePath);
  const base = path.basename(basePath);
  const files = await fs.readdir(dir);
  const candidates = files
    .filter((name) => name === base || name.startsWith(`${base}.`))
    .map((name) => path.join(dir, name));

  const stats = await Promise.all(
    candidates.map(async (file) => ({ file, stat: await fs.stat(file) }))
  );
  return stats
    .sort((a, b) => b.stat.mtimeMs - a.stat.mtimeMs)
    .map((item) => item.file);
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const limit = Math.min(Number(searchParams.get("limit") ?? 300), 2000);
  const before = parseTimestamp(searchParams.get("before"));
  const fromParam = parseTimestamp(searchParams.get("from"));
  const toParam = parseTimestamp(searchParams.get("to"));
  const levelsParam = searchParams.get("levels");
  const levelSet = new Set(
    (levelsParam ? levelsParam.split(",") : [])
      .map((v) => v.trim().toUpperCase())
      .filter(Boolean)
  );

  const now = new Date();
  const to = before ?? toParam ?? now;
  const from = fromParam ?? new Date(to.getTime() - 10 * 60 * 1000);

  const cwd = process.cwd();
  const basePath = await firstExistingPath([
    process.env.DASHBOARD_LOG_PATH ?? "",
    process.env.LOG_FILE ?? "",
    path.resolve(cwd, "logs", "spread_arb.log"),
    path.resolve(cwd, "..", "logs", "spread_arb.log"),
    path.resolve(cwd, "..", "..", "logs", "spread_arb.log"),
  ]);

  let files: string[] = [];
  try {
    if (!basePath) {
      throw new Error("no log file found");
    }
    files = await listLogFiles(basePath);
  } catch (err) {
    return NextResponse.json(
      { error: "log files not found", detail: String(err) },
      { status: 404 }
    );
  }

  const items: LogEntry[] = [];
  for (const file of files) {
    const content = await fs.readFile(file, "utf-8");
    const lines = content.split(/\r?\n/).filter(Boolean);
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      const parsed = parseLogLine(lines[i]);
      if (!parsed) continue;
      const ts = new Date(parsed.ts);
      if (ts > to) continue;
      if (before && ts >= to) continue;
      if (ts < from) {
        break;
      }
      if (levelSet.size && !levelSet.has(parsed.level.toUpperCase())) {
        continue;
      }
      items.push(parsed);
      if (items.length >= limit) {
        break;
      }
    }
    if (items.length >= limit) {
      break;
    }
  }

  const nextCursor = items.length ? items[items.length - 1].ts : null;
  return NextResponse.json({
    from: from.toISOString(),
    to: to.toISOString(),
    count: items.length,
    nextCursor,
    items,
  });
}
