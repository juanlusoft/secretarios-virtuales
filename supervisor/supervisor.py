import asyncio
import json
import logging
import os
import sys
import time
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class Supervisor:
    def __init__(
        self,
        dsn: str,
        redis_url: str,
        alert_bot_token: str | None = None,
        alert_chat_id: str | None = None,
    ) -> None:
        self._dsn = dsn
        self._redis_url = redis_url
        self._alert_bot_token = alert_bot_token
        self._alert_chat_id = alert_chat_id
        self._processes: dict[UUID, asyncio.subprocess.Process] = {}
        self._orchestrator_proc: asyncio.subprocess.Process | None = None
        self._orchestrator_start_time: float = 0.0
        self._orchestrator_backoff: float = 5.0

    async def _send_alert(self, text: str) -> None:
        if not self._alert_bot_token or not self._alert_chat_id:
            return
        try:
            import httpx
            url = f"https://api.telegram.org/bot{self._alert_bot_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json={"chat_id": self._alert_chat_id, "text": text})
        except Exception:
            logger.warning("Failed to send Telegram alert", exc_info=True)

    async def _spawn(self, employee_id: UUID) -> None:
        if employee_id in self._processes:
            proc = self._processes[employee_id]
            if proc.returncode is None:
                logger.info("Secretary %s already running", employee_id)
                return

        logger.info("Spawning secretary %s", employee_id)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "secretary", str(employee_id),
            cwd=os.getcwd(),
        )
        self._processes[employee_id] = proc

    async def _terminate(self, employee_id: UUID) -> None:
        proc = self._processes.pop(employee_id, None)
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10.0)
            except TimeoutError:
                proc.kill()
        logger.info("Secretary %s terminated", employee_id)

    async def _spawn_orchestrator(self) -> None:
        """Spawn the orchestrator process and record the start time."""
        logger.info("Spawning orchestrator")
        self._orchestrator_proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "orchestrator",
            cwd=os.getcwd(),
        )
        self._orchestrator_start_time = time.monotonic()
        logger.info("Orchestrator spawned (pid %s)", self._orchestrator_proc.pid)

    async def _monitor_processes(self) -> None:
        while True:
            await asyncio.sleep(30)

            # ── Monitor secretary processes ──────────────────────────────────
            conn = await asyncpg.connect(self._dsn)
            active_ids = {
                row["id"]
                for row in await conn.fetch(
                    "SELECT id FROM employees WHERE is_active = true AND is_orchestrator = false"
                )
            }
            await conn.close()

            for employee_id in list(self._processes.keys()):
                proc = self._processes[employee_id]
                if proc.returncode is not None and employee_id in active_ids:
                    logger.warning(
                        "Secretary %s crashed (code %s), restarting",
                        employee_id,
                        proc.returncode,
                    )
                    await self._send_alert(
                        f"⚠️ Secretario {employee_id} crasheó (código {proc.returncode}). Reiniciando..."
                    )
                    await self._spawn(employee_id)

            # ── Monitor orchestrator process ─────────────────────────────────
            if (
                self._orchestrator_proc is not None
                and self._orchestrator_proc.returncode is not None
            ):
                uptime = time.monotonic() - self._orchestrator_start_time
                exit_code = self._orchestrator_proc.returncode
                logger.error(
                    "Orchestrator exited (code %s, uptime %.1fs). Restarting in %.0fs...",
                    exit_code, uptime, self._orchestrator_backoff,
                )
                await self._send_alert(
                    f"🚨 Orquestador crasheó (código {exit_code}, uptime {uptime:.0f}s). Reiniciando en {self._orchestrator_backoff:.0f}s..."
                )

                # Reset backoff if the process ran successfully for > 30 s
                if uptime > 30:
                    self._orchestrator_backoff = 5.0
                    logger.info("Orchestrator uptime > 30s — backoff reset to 5s")

                await asyncio.sleep(self._orchestrator_backoff)

                # Exponential backoff capped at 60 s
                self._orchestrator_backoff = min(self._orchestrator_backoff * 2, 60.0)

                await self._spawn_orchestrator()

    async def _listen_lifecycle(self) -> None:
        retry_delay = 1.0
        while True:
            try:
                r = aioredis.from_url(self._redis_url)  # type: ignore[no-untyped-call]
                pubsub = r.pubsub()
                await pubsub.subscribe("secretary.lifecycle")
                logger.info("Lifecycle listener subscribed to secretary.lifecycle")
                retry_delay = 1.0

                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    data = json.loads(message["data"])
                    employee_id = UUID(data["employee_id"])
                    if data["event"] == "created":
                        await self._spawn(employee_id)
                    elif data["event"] == "destroyed":
                        await self._terminate(employee_id)
                    elif data["event"] == "tools_updated":
                        await asyncio.sleep(2)
                        await self._terminate(employee_id)
                        await self._spawn(employee_id)
                        logger.info("Secretary %s restarted after tools_updated", employee_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Lifecycle listener error; retrying in %.1fs",
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60.0)

    async def run(self) -> None:
        logger.info("Supervisor starting")

        # Spawn all active secretaries on startup
        conn = await asyncpg.connect(self._dsn)
        rows = await conn.fetch(
            "SELECT id FROM employees WHERE is_active = true AND is_orchestrator = false"
        )
        await conn.close()

        for row in rows:
            await self._spawn(row["id"])

        # Also spawn orchestrator
        await self._spawn_orchestrator()

        await asyncio.gather(
            self._monitor_processes(),
            self._listen_lifecycle(),
        )
