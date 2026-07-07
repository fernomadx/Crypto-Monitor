"""Configuração da VPS Hetzner (persistida em /data)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("VPS_CONFIG_PATH", "/data/vps_config.json"))
IP_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def get_host() -> str:
    env = os.environ.get("VPS_HOST", "").strip()
    if env:
        return env
    return (load().get("host") or "").strip()


def set_host(host: str) -> None:
    if not IP_RE.match(host.strip()):
        raise ValueError(f"IPv4 inválido: {host}")
    data = load()
    data["host"] = host.strip()
    data["updated_at"] = _now()
    save(data)


def record_sync(*, ok: bool, summary: str) -> None:
    data = load()
    data["last_sync_at"] = _now()
    data["last_sync_ok"] = ok
    data["last_sync_summary"] = summary[:2000]
    save(data)


def status_text() -> str:
    data = load()
    host = get_host()
    lines = ["<b>🖥 VPS Hetzner (BTCCURSOR)</b>", "Kronos: <i>desligado aqui</i> (ativo no Railway)"]
    if host:
        lines.append(f"Host: <code>{host}</code>")
    else:
        lines.append("Host: <i>não configurado</i>")
        lines.append("Use: <code>/vps 95.xxx.xxx.xxx</code>")
    if data.get("updated_at"):
        lines.append(f"Configurado: {data['updated_at']}")
    if data.get("last_sync_at"):
        icon = "✅" if data.get("last_sync_ok") else "❌"
        lines.append(f"Último sync: {icon} {data['last_sync_at']}")
        if data.get("last_sync_summary"):
            lines.append(f"<code>{data['last_sync_summary'][:500]}</code>")
    ssh = "✅" if os.environ.get("VPS_SSH_PRIVATE_KEY") else "⚠️ ausente"
    lines.append(f"Chave SSH Railway: {ssh}")
    return "\n".join(lines)
