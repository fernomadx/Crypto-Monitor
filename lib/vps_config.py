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


def _slot_for_host(host: str) -> str:
    h = (host or "").strip().lower()
    extra = (os.environ.get("VPS_ATLAS_HOST") or "").strip().lower()
    aliases = {"atlas", "77", "77.42.126.222"}
    if extra:
        aliases.add(extra)
    return "atlas" if h in aliases else "btccursor"


def record_sync(*, ok: bool, summary: str, host: str = "") -> None:
    """Grava o resultado por VPS. ATLAS não sobrescreve o slot BTCCURSOR."""
    data = load()
    now = _now()
    slot = _slot_for_host(host)
    data["last_sync_at"] = now
    data["last_sync_ok"] = ok
    data["last_sync_summary"] = summary[:2000]
    data["last_sync_host"] = host
    data[f"last_sync_{slot}_at"] = now
    data[f"last_sync_{slot}_ok"] = ok
    data[f"last_sync_{slot}_summary"] = summary[:2000]
    data[f"last_sync_{slot}_host"] = host or data.get(f"last_sync_{slot}_host", "")
    save(data)


def _slot_block(data: dict, slot: str, title: str, fallback_host: str) -> list[str]:
    lines = [f"<b>{title}</b>"]
    shown = (data.get(f"last_sync_{slot}_host") or fallback_host or "").strip()
    if shown:
        lines.append(f"Host: <code>{shown}</code>")
    else:
        lines.append("Host: <i>não configurado</i>")
    at = data.get(f"last_sync_{slot}_at")
    ok = data.get(f"last_sync_{slot}_ok")
    summary = data.get(f"last_sync_{slot}_summary") or ""
    if not at and data.get("last_sync_at"):
        old_host = data.get("last_sync_host") or data.get("host") or ""
        if _slot_for_host(old_host) == slot:
            at = data.get("last_sync_at")
            ok = data.get("last_sync_ok")
            summary = data.get("last_sync_summary") or ""
    if at:
        icon = "✅" if ok else "❌"
        lines.append(f"Último sync: {icon} {at}")
        if summary:
            lines.append(f"<code>{summary[:400]}</code>")
    else:
        lines.append("Último sync: <i>ainda não</i>")
    return lines


def status_text() -> str:
    data = load()
    btc_host = get_host() or "204.168.179.200"
    atlas_host = os.environ.get("VPS_ATLAS_HOST", "").strip() or "77.42.126.222"
    lines = [
        "<b>🖥 VPS Hetzner</b>",
        "Kronos: <i>desligado aqui</i> (ativo no Railway)",
        "",
        *_slot_block(data, "btccursor", "BTCCURSOR", btc_host),
        "",
        *_slot_block(data, "atlas", "ATLAS", atlas_host),
        "",
    ]
    ssh = "✅" if os.environ.get("VPS_SSH_PRIVATE_KEY") else "⚠️ ausente"
    lines.append(f"Chave SSH Railway: {ssh}")
    return "\n".join(lines)
