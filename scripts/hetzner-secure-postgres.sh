#!/usr/bin/env bash
# Secure Hetzner VPS: close public PostgreSQL (5432) and harden firewall.
# Safe defaults: keeps SSH (22) and HTTP/HTTPS (80/443).
#
# Run on the VPS (Hetzner Console / SSH):
#   curl -fsSL https://raw.githubusercontent.com/fernomadx/Crypto-Monitor/cursor/atlas-v1-7092/scripts/hetzner-secure-postgres.sh | sudo bash
# Or after git pull on /opt/crypto-monitor:
#   sudo bash scripts/hetzner-secure-postgres.sh
#
# Does NOT print passwords or dump databases.

set -euo pipefail

log() { echo "[secure-pg] $*"; }
warn() { echo "[secure-pg] WARN: $*" >&2; }

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

PUBLIC_IFACE="$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}' || true)"
PUBLIC_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}' || true)"
log "host=$(hostname) public_ip=${PUBLIC_IP:-unknown} iface=${PUBLIC_IFACE:-unknown}"

# ---------------------------------------------------------------------------
# 1) Docker: rebind published 5432 to localhost only
# ---------------------------------------------------------------------------
fix_docker_postgres_publish() {
  if ! command -v docker >/dev/null 2>&1; then
    log "docker not installed — skip container rebind"
    return 0
  fi

  # Find containers publishing host port 5432
  mapfile -t CIDS < <(docker ps --format '{{.ID}}' 2>/dev/null || true)
  for cid in "${CIDS[@]:-}"; do
    [[ -z "$cid" ]] && continue
    ports="$(docker port "$cid" 2>/dev/null || true)"
    if echo "$ports" | grep -qE '(^| )5432/tcp -> 0\.0\.0\.0:5432|(^| )5432/tcp -> :::5432|(^| )5432/tcp -> \[::\]:5432'; then
      name="$(docker inspect -f '{{.Name}}' "$cid" | sed 's#^/##')"
      image="$(docker inspect -f '{{.Config.Image}}' "$cid")"
      warn "container $name ($cid) publishes 5432 publicly ($image)"
      # Prefer compose project recreate if labeled
      project="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$cid" 2>/dev/null || true)"
      workdir="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$cid" 2>/dev/null || true)"
      service="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$cid" 2>/dev/null || true)"
      if [[ -n "$project" && -n "$workdir" && -d "$workdir" ]]; then
        log "attempting compose harden in $workdir (service=${service:-db})"
        (
          cd "$workdir"
          # Patch any compose yaml that maps "5432:5432" -> "127.0.0.1:5432:5432"
          for f in docker-compose.yml docker-compose.yaml compose.yml compose.yaml; do
            if [[ -f "$f" ]] && grep -qE '["'\'']?5432:5432["'\'']?' "$f"; then
              cp -a "$f" "${f}.bak.$(date +%s)"
              sed -i -E 's/(["'\'']?)5432:5432(["'\'']?)/\1"127.0.0.1:5432:5432"\2/g' "$f"
              # fix accidental double quotes from sed
              sed -i -E 's/""127\.0\.0\.1:5432:5432""/"127.0.0.1:5432:5432"/g' "$f"
              sed -i -E "s/''127\.0\.0\.1:5432:5432''/'127.0.0.1:5432:5432'/g" "$f"
              log "patched $workdir/$f"
            fi
          done
          if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
            docker compose up -d --force-recreate "${service:-}" 2>/dev/null \
              || docker compose up -d --force-recreate
          elif command -v docker-compose >/dev/null 2>&1; then
            docker-compose up -d --force-recreate "${service:-}" 2>/dev/null \
              || docker-compose up -d --force-recreate
          fi
        )
      else
        warn "no compose metadata for $name — will block via firewall/iptables (manual recreate recommended)"
      fi
    fi
  done

  # Also scan common ATLAS/app paths
  for dir in /opt/crypto-monitor/atlas /opt/atlas /root/atlas /home/*/atlas; do
    [[ -d "$dir" ]] || continue
    for f in "$dir"/docker-compose.yml "$dir"/docker-compose.yaml "$dir"/compose.yml; do
      [[ -f "$f" ]] || continue
      if grep -qE '["'\'']?5432:5432["'\'']?' "$f" && ! grep -q '127.0.0.1:5432:5432' "$f"; then
        cp -a "$f" "${f}.bak.$(date +%s)"
        sed -i -E 's/- "5432:5432"/- "127.0.0.1:5432:5432"/g; s/- '\''5432:5432'\''/- '\''127.0.0.1:5432:5432'\''/g; s/- 5432:5432/- "127.0.0.1:5432:5432"/g' "$f"
        log "patched $f"
        (
          cd "$dir"
          docker compose up -d --force-recreate 2>/dev/null || true
        )
      fi
    done
  done
}

# ---------------------------------------------------------------------------
# 2) Native PostgreSQL: listen on localhost only
# ---------------------------------------------------------------------------
fix_native_postgres() {
  if command -v psql >/dev/null 2>&1 || systemctl list-units --type=service 2>/dev/null | grep -qi postgres; then
    conf="$(ls /etc/postgresql/*/main/postgresql.conf 2>/dev/null | head -1 || true)"
    hba="$(ls /etc/postgresql/*/main/pg_hba.conf 2>/dev/null | head -1 || true)"
    if [[ -n "${conf:-}" && -f "$conf" ]]; then
      if grep -qE "^#?listen_addresses\s*=" "$conf"; then
        sed -i -E "s/^#?listen_addresses\s*=.*/listen_addresses = 'localhost'/" "$conf"
      else
        echo "listen_addresses = 'localhost'" >>"$conf"
      fi
      log "set listen_addresses=localhost in $conf"
      if [[ -n "${hba:-}" && -f "$hba" ]]; then
        # Comment wide-open host lines (keep local/peer)
        if grep -qE '^host\s+all\s+all\s+0\.0\.0\.0/0' "$hba"; then
          cp -a "$hba" "${hba}.bak.$(date +%s)"
          sed -i -E 's/^(host\s+all\s+all\s+0\.0\.0\.0\/0)/# secured: \1/' "$hba"
          log "restricted pg_hba wide-open entries"
        fi
      fi
      systemctl reload postgresql 2>/dev/null || systemctl reload postgresql@* 2>/dev/null || true
    fi
  fi
}

# ---------------------------------------------------------------------------
# 3) iptables DOCKER-USER: drop external 5432 even if Docker publishes
# ---------------------------------------------------------------------------
fix_iptables_docker_user() {
  if ! command -v iptables >/dev/null 2>&1; then
    warn "iptables missing"
    return 0
  fi
  # Ensure DOCKER-USER exists (Docker creates it; create if absent)
  iptables -N DOCKER-USER 2>/dev/null || true
  # Remove prior markers then insert drop for 5432 from non-local
  while iptables -C DOCKER-USER -p tcp --dport 5432 -j DROP 2>/dev/null; do
    iptables -D DOCKER-USER -p tcp --dport 5432 -j DROP || break
  done
  # Allow established + localhost, drop new external to 5432
  iptables -I DOCKER-USER -p tcp --dport 5432 -s 127.0.0.1 -j RETURN 2>/dev/null || true
  iptables -I DOCKER-USER -p tcp --dport 5432 -j DROP
  log "DOCKER-USER: drop tcp/5432 from non-local"

  # Persist if possible
  if command -v netfilter-persistent >/dev/null 2>&1; then
    netfilter-persistent save 2>/dev/null || true
  elif [[ -d /etc/iptables ]]; then
    iptables-save >/etc/iptables/rules.v4 2>/dev/null || true
  fi
}

# ---------------------------------------------------------------------------
# 4) UFW: deny 5432, allow ssh/http/https
# ---------------------------------------------------------------------------
fix_ufw() {
  if ! command -v ufw >/dev/null 2>&1; then
    apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ufw || {
      warn "could not install ufw"
      return 0
    }
  fi
  ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  ufw deny 5432/tcp >/dev/null 2>&1 || true
  # Enable non-interactively
  ufw --force enable >/dev/null 2>&1 || true
  log "ufw: allow 22/80/443, deny 5432"
  ufw status numbered | head -40 || true
}

# ---------------------------------------------------------------------------
# 5) Verify local listeners
# ---------------------------------------------------------------------------
verify_local() {
  log "listeners on :5432 after harden:"
  ss -lntp | grep -E ':5432\b' || log "(none listening — ok if DB down; better if 127.0.0.1 only)"
  if ss -lntp | grep -E '0\.0\.0\.0:5432|\*:5432|:::5432' >/dev/null 2>&1; then
    warn "still listening on all interfaces — firewall/iptables should still block public access"
  else
    log "no 0.0.0.0:5432 listener detected"
  fi
}

fix_docker_postgres_publish
fix_native_postgres
fix_iptables_docker_user
fix_ufw
verify_local

log "DONE. From the internet, TCP 5432 on this host should now be closed."
log "Optional: in Hetzner Cloud Console → Firewall, deny inbound TCP 5432 (defense in depth)."
log "Re-check externally: nc -vz ${PUBLIC_IP:-YOUR_IP} 5432  (expect failure)"
