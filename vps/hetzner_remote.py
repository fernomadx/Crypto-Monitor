#!/usr/bin/env python3
"""SSH na Hetzner a partir do Railway — heal BTCCURSOR (204) + ATLAS (77)."""

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

DEFAULT_BTCCURSOR_HOST = "204.168.179.200"
DEFAULT_ATLAS_HOST = "77.42.126.222"
AUTH_HINT = (
    "<i>SSH recusado. Na Console Hetzner cole:</i>\n"
    "<code>mkdir -p ~/.ssh && curl -fsSL "
    "https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/vps_deploy_key.pub "
    ">> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys</code>"
)

# Heal completo no 204: sync main, Kronos off, COMBO5 on, CCXT morto, nginx se 502.
REMOTE_BOOTSTRAP = r"""
set -e
export REPO_DIR=/opt/crypto-monitor
if [ -d \"$REPO_DIR/.git\" ]; then
  cd \"$REPO_DIR\" && git fetch origin && git reset --hard origin/main
  chmod +x vps/hetzner_disable_kronos.sh vps/hetzner_test.sh \\
    scripts/hetzner-kill-legacy-mexc.sh scripts/hetzner-heal-bots.sh \\
    scripts/hetzner-heal-204.sh 2>/dev/null || true
  bash vps/hetzner_disable_kronos.sh
  if [ -f scripts/hetzner-heal-bots.sh ]; then
    bash scripts/hetzner-heal-bots.sh
  elif [ -f scripts/hetzner-kill-legacy-mexc.sh ]; then
    bash scripts/hetzner-kill-legacy-mexc.sh
  fi
  if [ -f scripts/hetzner-heal-204.sh ]; then
    bash scripts/hetzner-heal-204.sh || true
  fi
  bash vps/hetzner_test.sh
else
  curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-heal-bots.sh | bash
  curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/main/scripts/hetzner-heal-204.sh | bash || true
fi
"""


def default_btccursor_host() -> str:
    from lib.vps_config import get_host

    return (
        os.environ.get("VPS_HOST", "").strip()
        or get_host()
        or DEFAULT_BTCCURSOR_HOST
    )


def default_atlas_host() -> str:
    return os.environ.get("VPS_ATLAS_HOST", "").strip() or DEFAULT_ATLAS_HOST


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
        _stdin, stdout, stderr = client.exec_command(script, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err
    finally:
        client.close()


def _tail(text: str, n: int = 80) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "(sem output)"
    return "\n".join(lines[-n:])


def _looks_like_auth_failure(msg: str) -> bool:
    low = msg.lower()
    return "authentication failed" in low or "auth fail" in low or "permission denied" in low


def _format_host_result(kind: str, host: str, code: int, out: str, err: str) -> str:
    combined = (out + "\n" + err).strip()
    tail = _tail(combined)
    if code == 0:
        return (
            f"<b>✅ {kind} OK</b> — <code>{host}</code>\n\n"
            f"<pre>{tail[-3500:]}</pre>"
        )
    extra = ""
    if _looks_like_auth_failure(combined):
        extra = f"\n\n{AUTH_HINT}"
    else:
        extra = "\n\n<i>SSH autenticou; o exit veio do heal/teste no host.</i>"
    return (
        f"<b>❌ {kind} falhou</b> (exit {code}) — <code>{host}</code>\n\n"
        f"<pre>{tail[-3500:]}</pre>{extra}"
    )


def sync_and_test(host: str | None = None) -> str:
    from lib.vps_config import record_sync

    target = (host or default_btccursor_host()).strip()
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
        record_sync(ok=code == 0, summary=_tail(combined))
        return _format_host_result("BTCCURSOR", target, code, out, err)
    except Exception as exc:
        logger.exception("hetzner sync: %s", exc)
        record_sync(ok=False, summary=str(exc))
        extra = f"\n\n{AUTH_HINT}" if _looks_like_auth_failure(str(exc)) else ""
        return f"❌ SSH falhou ({target}): {exc}{extra}"


def heal_atlas(host: str | None = None) -> str:
    from lib.vps_config import record_sync

    target = (host or default_atlas_host()).strip()
    if not re.match(r"^(?:\d{1,3}\.){3}\d{1,3}$", target):
        return f"⚠️ ATLAS IPv4 inválido: {target}"

    script_path = REPO_ROOT / "scripts" / "hetzner-heal-atlas.sh"
    if script_path.is_file():
        script = script_path.read_text(encoding="utf-8")
    else:
        script = (
            "curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/"
            "main/scripts/hetzner-heal-atlas.sh | bash"
        )

    try:
        code, out, err = ssh_run(target, script)
        combined = (out + "\n" + err).strip()
        record_sync(ok=code == 0, summary=f"ATLAS {target}: {_tail(combined)}")
        return _format_host_result("ATLAS", target, code, out, err)
    except Exception as exc:
        logger.exception("atlas heal: %s", exc)
        record_sync(ok=False, summary=f"ATLAS {target}: {exc}")
        extra = f"\n\n{AUTH_HINT}" if _looks_like_auth_failure(str(exc)) else ""
        return f"❌ SSH ATLAS falhou ({target}): {exc}{extra}"


def heal_all() -> str:
    """BTCCURSOR 204 + ATLAS 77. Falha de um não aborta o outro."""
    parts = [sync_and_test(default_btccursor_host()), heal_atlas(default_atlas_host())]
    return "\n\n———\n\n".join(parts)


def format_for_telegram(text: str) -> str:
    return text.replace("<pre>", "").replace("</pre>", "\n") if len(text) > 4000 else text


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg in {"all", "heal"}:
        raw = heal_all()
    elif arg in {"atlas", DEFAULT_ATLAS_HOST}:
        raw = heal_atlas(DEFAULT_ATLAS_HOST if arg == "atlas" else arg)
    else:
        raw = sync_and_test(arg)
    print(
        raw.replace("<b>", "")
        .replace("</b>", "")
        .replace("<code>", "")
        .replace("</code>", "")
        .replace("<pre>", "")
        .replace("</pre>", "")
        .replace("<i>", "")
        .replace("</i>", "")
    )
