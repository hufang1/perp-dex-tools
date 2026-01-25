import asyncio
import logging
from typing import Optional, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)


class DashboardIngestor:
    """异步Dashboard数据写入器（队列 + 后台发送，不阻塞主流程）"""

    def __init__(self, ingest_url: Optional[str], queue_size: int = 500):
        self.ingest_url = ingest_url
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False

    @property
    def enabled(self) -> bool:
        return bool(self.ingest_url)

    async def start(self) -> None:
        if not self.ingest_url:
            logger.info("未配置Dashboard Ingest URL，数据写入已禁用")
            return
        if self._running:
            return
        self._running = True
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3))
        self._task = asyncio.create_task(self._worker())
        logger.info("Dashboard数据写入器已启动")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            try:
                await self.queue.put(None)
                await self._task
            except Exception:
                pass
            self._task = None
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("Dashboard数据写入器已停止")

    def enqueue(self, payload: Dict[str, Any]) -> None:
        if not self._running:
            return
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("Dashboard数据队列已满，丢弃数据")

    async def _worker(self) -> None:
        while True:
            payload = await self.queue.get()
            if payload is None:
                self.queue.task_done()
                break
            try:
                await self._send(payload)
            except Exception as e:
                logger.warning(f"Dashboard写入失败: {e}")
            finally:
                self.queue.task_done()

    async def _send(self, payload: Dict[str, Any]) -> None:
        if not self._session:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3))
        async with self._session.post(self.ingest_url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.warning(f"Dashboard写入失败 status={resp.status} body={text}")
