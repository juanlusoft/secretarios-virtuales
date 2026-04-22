import asyncio
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_PROJECT_DIR = Path(__file__).resolve().parents[2]


async def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
    return proc.returncode, stdout.decode(errors="replace")


@router.post("/update", response_class=HTMLResponse)
async def ota_update():
    lines: list[str] = []
    ok = True

    steps = [
        ("git pull", ["git", "-c", "safe.directory=*", "pull"]),
        ("pip install", [str(_PROJECT_DIR / ".venv" / "bin" / "pip"), "install", "-e", ".", "-q"]),
        ("migraciones", [str(_PROJECT_DIR / ".venv" / "bin" / "python"), "-m", "shared.db.migrate"]),
        ("reiniciar servicios", ["sudo", "systemctl", "restart",
                                 "secretary@*", "orchestrator", "supervisor", "web-admin"]),
    ]

    for label, cmd in steps:
        try:
            rc, out = await _run(cmd, _PROJECT_DIR)
            status = "✓" if rc == 0 else "✗"
            step_cls = "ota-ok" if rc == 0 else "ota-err"
            if rc != 0:
                ok = False
            lines.append(f'<div class="ota-step {step_cls}">'
                         f'<b>{status} {label}</b>'
                         + (f'<pre>{out.strip()}</pre>' if out.strip() else '')
                         + '</div>')
            if rc != 0:
                break
        except asyncio.TimeoutError:
            lines.append(f'<div class="ota-err"><b>✗ {label}</b><pre>Timeout</pre></div>')
            ok = False
            break
        except Exception as exc:
            lines.append(f'<div class="ota-err"><b>✗ {label}</b><pre>{exc}</pre></div>')
            ok = False
            break

    summary_cls = "ota-ok" if ok else "ota-err"
    summary_txt = "✓ Actualización completada" if ok else "✗ Actualización fallida"
    result = "".join(lines) + f'<div class="{summary_cls}" style="margin-top:8px;font-weight:700">{summary_txt}</div>'
    return HTMLResponse(result)
