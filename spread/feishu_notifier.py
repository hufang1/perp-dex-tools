import asyncio
import logging
from typing import List, Optional, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """异步飞书通知器（队列 + 后台发送，不阻塞主流程）"""

    def __init__(self, webhook_url: Optional[str], queue_size: int = 200):
        self.webhook_url = webhook_url
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False

    async def start(self) -> None:
        if not self.webhook_url:
            logger.info("未配置飞书Webhook，消息推送已禁用")
            return
        if self._running:
            return
        self._running = True
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        self._task = asyncio.create_task(self._worker())
        logger.info("飞书通知器已启动")

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
        logger.info("飞书通知器已停止")

    def enqueue(self, title: str, lines: List[str]) -> None:
        if not self._running:
            return
        payload = self._build_post_payload(title, lines)
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("飞书通知队列已满，丢弃消息")

    async def _worker(self) -> None:
        while True:
            payload = await self.queue.get()
            if payload is None:
                self.queue.task_done()
                break
            try:
                await self._send(payload)
            except Exception as e:
                logger.warning(f"飞书消息发送失败: {e}")
            finally:
                self.queue.task_done()

    async def _send(self, payload: Dict[str, Any]) -> None:
        if not self._session:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        async with self._session.post(self.webhook_url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.warning(f"飞书推送失败 status={resp.status} body={text}")

    def _build_post_payload(self, title: str, lines: List[str]) -> Dict[str, Any]:
        content = []
        for line in lines:
            content.append([{"tag": "text", "text": line}])
        return {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh-CN": {
                        "title": title,
                        "content": content,
                    }
                }
            },
        }
