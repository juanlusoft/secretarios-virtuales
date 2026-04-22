from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from shared.tools.ssh_store import SSHStore

if TYPE_CHECKING:
    from shared.calendar.client import CalendarClient
    from shared.email.client import EmailClient
    from shared.facts.client import FactsClient
    from shared.tasks.client import TasksClient
    from shared.search.duckduckgo import DuckDuckGoClient
    from shared.location.nominatim import NominatimClient
    from shared.youtube.transcriber import YouTubeTranscriber

_MAX_OUTPUT = 4000
_MAX_FILE = 8000


class ToolExecutor:
    def __init__(
        self,
        ssh_store: SSHStore | None = None,
        calendar_client: CalendarClient | None = None,
        email_client: EmailClient | None = None,
        facts_client: FactsClient | None = None,
        tasks_client: TasksClient | None = None,
        search_client: DuckDuckGoClient | None = None,
        location_client: NominatimClient | None = None,
        youtube_client: YouTubeTranscriber | None = None,
        last_location: dict | None = None,
    ) -> None:
        self._ssh = ssh_store
        self._calendar = calendar_client
        self._email = email_client
        self._facts = facts_client
        self._tasks = tasks_client
        self._search = search_client
        self._location = location_client
        self._youtube = youtube_client
        self._last_location: dict | None = last_location

    def update_location(self, lat: float, lon: float) -> None:
        self._last_location = {"lat": lat, "lon": lon}

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
            if name == "calendar_list":
                return await self._calendar_list(args)
            if name == "calendar_create":
                return await self._calendar_create(args)
            if name == "calendar_modify":
                return await self._calendar_modify(args)
            if name == "calendar_cancel":
                return await self._calendar_cancel(args)
            if name == "email_send":
                return await self._email_send(args)
            if name == "email_read":
                return await self._email_read(args)
            if name == "fact_save":
                return await self._fact_save(args)
            if name == "fact_list":
                return await self._fact_list(args)
            if name == "task_create":
                return await self._task_create(args)
            if name == "task_list":
                return await self._task_list()
            if name == "task_done":
                return await self._task_done(args)
            if name == "task_update":
                return await self._task_update(args)
            if name == "web_search":
                return await self._web_search(args)
            if name == "youtube_transcribe":
                return await self._youtube_transcribe(args)
            if name == "nearby_search":
                return await self._nearby_search(args)
            return f"Herramienta desconocida: {name}"
        except KeyError as e:
            return f"Error: falta el parámetro {e}"
        except Exception as e:
            return f"Error ejecutando {name}: {e}"

    async def _bash(self, command: str) -> str:
        if self._ssh is None:
            return "Herramienta bash no disponible."
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
        if self._ssh is None:
            return "Herramienta SSH no disponible."
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
        if self._ssh is None:
            return "Herramienta SSH no disponible."
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
        if self._ssh is None:
            return "Herramienta SSH no disponible."
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
                lines.append(f"📄 {e.name} ({e.stat().st_size} bytes)")
        return "\n".join(lines) if lines else "(directorio vacío)"

    async def _calendar_list(self, args: dict) -> str:
        if self._calendar is None:
            return "Calendario no configurado. Usa /config_calendar para configurarlo."
        days_ahead = int(args.get("days_ahead", 7))
        events = await self._calendar.list_events(days_ahead=days_ahead)
        if not events:
            return f"No hay eventos en los próximos {days_ahead} días."
        lines = []
        for e in events:
            local_start = e.start.strftime("%d/%m/%Y %H:%M")
            line = f"• [{e.id}] *{e.title}* — {local_start}"
            if e.location:
                line += f" 📍 {e.location}"
            lines.append(line)
        return "\n".join(lines)

    async def _calendar_create(self, args: dict) -> str:
        if self._calendar is None:
            return "Calendario no configurado. Usa /config_calendar para configurarlo."
        start = datetime.fromisoformat(args["start_iso"])
        end = datetime.fromisoformat(args["end_iso"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        event = await self._calendar.create_event(
            title=args["title"],
            start=start,
            end=end,
            description=args.get("description", ""),
            location=args.get("location", ""),
        )
        return f"✅ Evento creado: *{event.title}* el {event.start.strftime('%d/%m/%Y %H:%M')} (ID: {event.id})"

    async def _calendar_modify(self, args: dict) -> str:
        if self._calendar is None:
            return "Calendario no configurado. Usa /config_calendar para configurarlo."
        event_id = args["event_id"]
        fields = {k: v for k, v in args.items() if k != "event_id"}
        event = await self._calendar.modify_event(event_id, **fields)
        return f"✅ Evento actualizado: *{event.title}* el {event.start.strftime('%d/%m/%Y %H:%M')}"

    async def _calendar_cancel(self, args: dict) -> str:
        if self._calendar is None:
            return "Calendario no configurado. Usa /config_calendar para configurarlo."
        event_id = args["event_id"]
        await self._calendar.cancel_event(event_id)
        return f"✅ Evento {event_id} cancelado."

    async def _email_send(self, args: dict) -> str:
        if self._email is None:
            return "Email no configurado. Usa /config_email para activarlo."
        await self._email.send(to=args["to"], subject=args["subject"], body=args["body"])
        return f"✅ Email enviado a {args['to']}."

    async def _email_read(self, args: dict) -> str:
        if self._email is None:
            return "Email no configurado. Usa /config_email para activarlo."
        limit = int(args.get("limit", 5))
        messages = await self._email.fetch_inbox(limit=limit)
        if not messages:
            return "No hay emails nuevos."
        lines = []
        for m in messages:
            reply_addr = _extract_email_address(m.sender)
            lines.append(
                f"📧 De: {m.sender}\n"
                f"➤ DIRECCIÓN DE RESPUESTA: {reply_addr}\n"
                f"Asunto: {m.subject}\n"
                f"Fecha: {m.date}\n\n"
                f"{m.body[:500]}"
            )
        return "\n\n---\n\n".join(lines)

    async def _fact_save(self, args: dict) -> str:
        if self._facts is None:
            return "Servicio de datos no disponible."
        key = args["key"]
        value = args["value"]
        category = args.get("category", "general")
        await self._facts.save(key=key, value=value, category=category)
        return f"✅ Guardado: {key} = {value} (categoría: {category})"

    async def _fact_list(self, args: dict) -> str:
        if self._facts is None:
            return "Servicio de datos no disponible."
        category = args.get("category")
        facts = await self._facts.list_all(category=category)
        if not facts:
            return "No hay datos personales guardados."
        lines = ["📋 Datos personales guardados:"]
        current_cat = None
        for f in facts:
            if f.category != current_cat:
                current_cat = f.category
                lines.append(f"\n**{current_cat}:**")
            lines.append(f"  • {f.key}: {f.value}")
        return "\n".join(lines)

    async def _task_create(self, args: dict) -> str:
        if self._tasks is None:
            return "Servicio de tareas no disponible."
        title = args["title"]
        description = args.get("description")
        task_id = await self._tasks.create(title=title, description=description)
        return f"✅ Tarea creada: {title} (ID: {task_id})"

    async def _task_list(self) -> str:
        if self._tasks is None:
            return "Servicio de tareas no disponible."
        tasks = await self._tasks.list_all()
        if not tasks:
            return "No hay tareas."
        pending = [t for t in tasks if t.status == "pending"]
        done = [t for t in tasks if t.status == "done"]
        lines = []
        if pending:
            lines.append("📋 **Tareas pendientes:**")
            for t in pending:
                desc = f" — {t.description}" if t.description else ""
                lines.append(f"  • [{t.id}] {t.title}{desc}")
        if done:
            lines.append("\n✅ **Completadas:**")
            for t in done[-5:]:
                lines.append(f"  ~~{t.title}~~")
        return "\n".join(lines) if lines else "No hay tareas."

    async def _task_done(self, args: dict) -> str:
        if self._tasks is None:
            return "Servicio de tareas no disponible."
        task_id = args["task_id"]
        ok = await self._tasks.mark_done(task_id=task_id)
        return f"✅ Tarea {task_id} marcada como completada." if ok else f"No encontré la tarea {task_id}."

    async def _task_update(self, args: dict) -> str:
        if self._tasks is None:
            return "Servicio de tareas no disponible."
        task_id = args["task_id"]
        title = args.get("title")
        description = args.get("description")
        ok = await self._tasks.update(task_id=task_id, title=title, description=description)
        return f"✅ Tarea {task_id} actualizada." if ok else f"No encontré la tarea {task_id}."

    async def _web_search(self, args: dict) -> str:
        if self._search is None:
            return "Búsqueda web no disponible."
        query = args["query"]
        max_results = min(int(args.get("max_results", 5)), 10)
        return await self._search.search(query=query, max_results=max_results)

    async def _youtube_transcribe(self, args: dict) -> str:
        if self._youtube is None:
            return "Transcripción de YouTube no disponible."
        url = args["url"]
        save_path = args.get("save_path", f"transcripciones/video_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md")
        text = await self._youtube.transcribe(url=url)
        full_path = Path("./data/vault") / save_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(f"# Transcripción\n\nFuente: {url}\nFecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n\n{text}")
        preview = text[:500] + "..." if len(text) > 500 else text
        return f"✅ Transcripción guardada en {save_path} ({len(text)} chars)\n\nExtracto:\n{preview}"

    async def _nearby_search(self, args: dict) -> str:
        if self._location is None:
            return "Búsqueda de ubicación no disponible."
        if self._last_location is None:
            return "No tengo tu ubicación. Envíame tu ubicación por Telegram primero (botón 📎 → Ubicación)."
        query = args["query"]
        radius_m = int(args.get("radius_m", 1000))
        lat = self._last_location["lat"]
        lon = self._last_location["lon"]
        return await self._location.nearby(lat=lat, lon=lon, query=query, radius_m=radius_m)


def _extract_email_address(sender: str) -> str:
    import re
    match = re.search(r"<([^>]+)>", sender)
    if match:
        return match.group(1)
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", sender)
    if match:
        return match.group(0)
    return sender.strip()
