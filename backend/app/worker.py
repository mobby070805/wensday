"""Standalone background worker: `python -m app.worker`.

Runs the reminder and scheduled-workflow loops without serving HTTP. In Kubernetes the API
Deployment sets WENSDAY_REMINDER_WORKER=false and a separate `worker` Deployment runs this.
Firing is claim-based (see services.reminders.claim), so running more than one worker is safe.
Events reach the API replicas' websockets through Redis pub/sub (set WENSDAY_REDIS_URL).
"""
from __future__ import annotations

import asyncio
import logging
import signal

from .config import get_settings
from .main import create_app


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings().model_copy(update={"reminder_worker": True})
    app = create_app(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    async with app.router.lifespan_context(app):
        logging.getLogger("wensday.worker").info("worker started")
        await stop.wait()


if __name__ == "__main__":
    asyncio.run(run())
