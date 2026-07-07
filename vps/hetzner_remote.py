#!/usr/bin/env python3
"""SSH na Hetzner a partir do Railway — bootstrap + teste."""

from __future__ import annotations

import logging
import os
import re
import sys
from io import StringIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger(__name__)

REMOTE_BOOTSTRAP = """
set -e
export REPO_DIR=/opt/crypto-monitor
if [ -d "$REPO_DIR/.git" ]; then
  cd "$REPO_DIR" && git pull origin main
  chmod +x vps/hetzner_disable_kronos.sh vps/hetzner_test.sh
  bash vps/hetzner_disable_kronos.sh
  bash vps/hetzner_test.sh
else
  curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/vps/hetzner_disable_kronos.sh | bash
fi
"""


def _load_private_key():
    import paramiko

    raw = os.environ.get("VPS_SSH_PRIVATE_KEY", "").strip()
    key_path = os.environ.get("VPS_SSH_KEY_PATH", "/data/vps_ssh_key")
    if raw:
        return paramiko.Ed25519Key.from_private_key(StringIO(raw))
    if Path(key_path).is_file():
        return paramiko.Ed25519Key.from_private_key_file(key_path)
    raise RuntimeError(
        "VPS_SSH_PRIVATE_KEY não configurada no Railway. "
        "Adicione a chave privada (par de scripts/vps_deploy_key.pub)."
    )


def ssh_run(host: str, script: str, *, timeout: int = 600) -> tuple[int, str, str]:
    import paramiko

    user = os.environ.get("VPS_USER", "root").strip() or "root"
    port = int(os.environ.get("VPS_PORT", "22"))
    pkey = _load_private_key()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            port=port,
            username=user,
            pkey=pkey,
            timeout=30,
            banner_timeout=30,
            auth_timeout=30,
        )
        stdin, stdout, stderr = client.exec_command(script, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err
    finally:
        client.close()


def sync_and_test(host: str | None = None) -> str:
    from lib.vps_config import get_host, record_sync

    target = (host or get_host()).strip()
    if not target:
        return (
            "⚠️ VPS sem IP.\n"
            "Envie: <code>/vps 95.xxx.xxx.xxx</code>\n"
            "Ou configure <code>VPS_HOST</code> no Railway."
        )

    if not re.match(r"^(?:\d{1,3}\.){3}\d{1,3}$", target):
        return f"⚠️ IPv4 inválido: {target}"

    try:
        code, out, err = ssh_run(target, REMOTE_BOOTSTRAP)
        combined = (out + "\n" + err).strip()
        tail = "\n".join(combined.splitlines()[-25:]) if combined else "(sem output)"
        ok = code == 0
        record_sync(ok=ok, summary=tail)
        if ok:
            return (
                f"<b>✅ Hetzner OK</b> — <code>{target}</code>\n\n"
                f"<pre>{tail[-3500:]}</pre>"
            )
        return (
            f"<b>❌ Hetzner falhou</b> (exit {code}) — <code>{target}</code>\n\n"
            f"<pre>{tail[-3500:]}</pre>\n\n"
            "<i>Se auth failed: na Console Hetzner cole:</i>\n"
            "<code>mkdir -p ~/.ssh && curl -fsSL "
            "https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/vps_deploy_key.pub "
            ">> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys</code>"
        )
    except Exception as exc:
        logger.exception("hetzner sync: %s", exc)
        record_sync(ok=False, summary=str(exc))
        msg = str(exc)
        extra = ""
        if "Authentication failed" in msg or "auth" in msg.lower():
            extra = (
                "\n\n<i>Adicione a chave pública na Hetzner (Console):</i>\n"
                "<code>curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/vps_deploy_key.pub "
                "| tee -a ~/.ssh/authorized_keys</code>"
            )
        return f"❌ SSH falhou: {msg}{extra}"


def format_for_telegram(text: str) -> str:
    return text.replace("<pre>", "").replace("</pre>", "\n") if len(text) > 4000 else text


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    host = sys.argv[1] if len(sys.argv) > 1 else None
    print(sync_and_test(host).replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<pre>", "").replace("</pre>", "").replace("<i>", "").replace("</i>", ""))
