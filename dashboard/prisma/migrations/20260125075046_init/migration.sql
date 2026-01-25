-- CreateTable
CREATE TABLE "SpreadSample" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "symbol" TEXT NOT NULL,
    "openSpread" DECIMAL NOT NULL,
    "closeSpread" DECIMAL NOT NULL,
    "midline" DECIMAL NOT NULL,
    "upper" DECIMAL NOT NULL,
    "lower" DECIMAL NOT NULL,
    "extBid" DECIMAL NOT NULL,
    "extAsk" DECIMAL NOT NULL,
    "ligBid" DECIMAL NOT NULL,
    "ligAsk" DECIMAL NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "PositionSnapshot" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "symbol" TEXT NOT NULL,
    "extQty" DECIMAL NOT NULL,
    "ligQty" DECIMAL NOT NULL,
    "extAvailUsd" DECIMAL NOT NULL,
    "ligAvailUsd" DECIMAL NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "BotEvent" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "symbol" TEXT NOT NULL,
    "level" TEXT NOT NULL,
    "eventType" TEXT NOT NULL,
    "message" TEXT NOT NULL,
    "state" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "PnlSnapshot" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "symbol" TEXT NOT NULL,
    "profit" DECIMAL NOT NULL,
    "cumulative" DECIMAL NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateIndex
CREATE INDEX "SpreadSample_symbol_createdAt_idx" ON "SpreadSample"("symbol", "createdAt");

-- CreateIndex
CREATE INDEX "PositionSnapshot_symbol_createdAt_idx" ON "PositionSnapshot"("symbol", "createdAt");

-- CreateIndex
CREATE INDEX "BotEvent_symbol_createdAt_idx" ON "BotEvent"("symbol", "createdAt");

-- CreateIndex
CREATE INDEX "PnlSnapshot_symbol_createdAt_idx" ON "PnlSnapshot"("symbol", "createdAt");
