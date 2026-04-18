import asyncio
import json
import logging
import os
import subprocess
import sys
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class Supervisor:
    def __init__(self, dsn: str, redis_url: str) -> None:
        self._dsn = dsn
        self._redis_url = redis_url
        self._processes: dict[UUID, asyncio.subprocess.Process] = {}

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
            except asyncio.TimeoutError:
                proc.kill()
        logger.info("Secretary %s terminated", employee_id)

    async def _monitor_processes(self) -> None:
        while True:
            await asyncio.sleep(30)
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
                    logger.warning("Secretary %s crashed (code %s), restarting", employee_id, proc.returncode)
                    await self._spawn(employee_id)

    async def _listen_lifecycle(self) -> None:
        r = await aioredis.from_url(self._redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe("secretary.lifecycle")
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            employee_id = UUID(data["employee_id"])
            if data["event"] == "created":
                await self._spawn(employee_id)
            elif data["event"] == "destroyed":
                await self._terminate(employee_id)

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
        orchestrator_proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "orchestrator",
            cwd=os.getcwd(),
        )
        logger.info("Orchestrator spawned (pid %s)", orchestrator_proc.pid)

        await asyncio.gather(
            self._monitor_processes(),
            self._listen_lifecycle(),
        )
