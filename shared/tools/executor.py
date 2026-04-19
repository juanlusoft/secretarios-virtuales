from __future__ import annotations

import asyncio
from pathlib import Path

from shared.tools.ssh_store import SSHStore

_MAX_OUTPUT = 4000
_MAX_FILE = 8000


class ToolExecutor:
    def __init__(self, ssh_store: SSHStore) -> None:
        self._ssh = ssh_store

    async def run(self, name: str, args: dict) -> str:
        try:
            if name == "bash":
                return await self._bash(args["command"])
            if name == "ssh_exec":
                return await self._ssh_exec(args["name"], args["command"])
            if name == "ssh_save":
                return await self._ssh_save(args)
            if name == "ssh_list":
                return await self._ssh_list()
            if name == "read_file":
                return self._read_file(args["path"])
            if name == "write_file":
                return self._write_file(args["path"], args["content"])
            if name == "list_dir":
                return self._list_dir(args["path"])
            return f"Herramienta desconocida: {name}"
        except KeyError as e:
            return f"Error: falta el parámetro {e}"
        except Exception as e:
            return f"Error ejecutando {name}: {e}"

    async def _bash(self, command: str) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        except asyncio.TimeoutError:
            return "Error: timeout (60s) alcanzado"
        out = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()
        if len(out) > _MAX_OUTPUT:
            out = out[:_MAX_OUTPUT] + f"\n... [truncado a {_MAX_OUTPUT} chars]"
        return out or "(sin salida)"

    async def _ssh_exec(self, name: str, command: str) -> str:
        import asyncssh
        data = await self._ssh.load(name)
        connect_kwargs: dict = {
            "host": data["host"],
            "port": data.get("port", 22),
            "username": data["user"],
            "known_hosts": None,
        }
        if "ssh_key" in data:
            connect_kwargs["client_keys"] = [asyncssh.import_private_key(data["ssh_key"])]
        else:
            connect_kwargs["password"] = data.get("password", "")

        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await conn.run(command, check=False)
        out = ((result.stdout or "") + (result.stderr or "")).strip()
        if len(out) > _MAX_OUTPUT:
            out = out[:_MAX_OUTPUT] + "\n... [truncado]"
        return out or "(sin salida)"

    async def _ssh_save(self, args: dict) -> str:
        await self._ssh.save(
            name=args["name"],
            host=args["host"],
            user=args["user"],
            password=args.get("password"),
            ssh_key=args.get("ssh_key"),
            port=int(args.get("port", 22)),
        )
        return f"✅ Conexión '{args['name']}' ({args['host']}) guardada."

    async def _ssh_list(self) -> str:
        connections = await self._ssh.list_all()
        if not connections:
            return "No hay conexiones SSH guardadas."
        lines = [f"• {c['name']}: {c['user']}@{c['host']}:{c['port']}" for c in connections]
        return "Conexiones SSH guardadas:\n" + "\n".join(lines)

    def _read_file(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: el fichero '{path}' no existe."
        if not p.is_file():
            return f"Error: '{path}' no es un fichero."
        content = p.read_text(errors="replace")
        if len(content) > _MAX_FILE:
            content = content[:_MAX_FILE] + f"\n... [truncado a {_MAX_FILE} chars]"
        return content

    def _write_file(self, path: str, content: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"✅ Fichero '{path}' escrito ({len(content)} chars)."

    def _list_dir(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: '{path}' no existe."
        if not p.is_dir():
            return f"Error: '{path}' no es un directorio."
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = []
        for e in entries:
            if e.is_dir():
                lines.append(f"📁 {e.name}/")
            else:
                size = e.stat().st_size
                lines.append(f"📄 {e.name} ({size} bytes)")
        return "\n".join(lines) if lines else "(directorio vacío)"
