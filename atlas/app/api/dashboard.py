"""Minimal ATLAS dashboard (single HTML page)."""

from __future__ import annotations

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ATLAS</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg0: #0f1419;
      --bg1: #172029;
      --ink: #e8eef4;
      --muted: #8fa3b5;
      --line: rgba(232,238,244,0.12);
      --long: #3dba7c;
      --short: #e35d5d;
      --flat: #c9a45c;
      --accent: #5b9fd4;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(1200px 600px at 10% -10%, rgba(91,159,212,0.18), transparent 55%),
        radial-gradient(900px 500px at 100% 0%, rgba(61,186,124,0.08), transparent 50%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
      min-height: 100vh;
    }
    header {
      padding: 2.5rem 1.5rem 1rem;
      max-width: 1100px;
      margin: 0 auto;
    }
    .brand {
      font-family: "IBM Plex Serif", serif;
      font-size: clamp(2.4rem, 6vw, 3.6rem);
      letter-spacing: -0.03em;
      margin: 0;
    }
    .tag {
      color: var(--muted);
      margin-top: 0.4rem;
      max-width: 42rem;
      line-height: 1.45;
    }
    main {
      max-width: 1100px;
      margin: 0 auto;
      padding: 0 1.5rem 3rem;
      display: grid;
      gap: 1.25rem;
    }
    .hero-decision {
      display: grid;
      gap: 0.75rem;
      padding: 1.25rem 0 0.5rem;
      border-top: 1px solid var(--line);
    }
    .decision {
      font-size: clamp(1.8rem, 4vw, 2.4rem);
      font-weight: 600;
    }
    .decision.LONG { color: var(--long); }
    .decision.SHORT { color: var(--short); }
    .decision.NO_TRADE { color: var(--flat); }
    .meta { color: var(--muted); font-size: 0.95rem; }
    section h2 {
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin: 1.2rem 0 0.6rem;
      font-weight: 500;
    }
    .row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 0.75rem;
    }
    .panel {
      border-top: 1px solid var(--line);
      padding: 0.85rem 0;
    }
    .panel strong { display: block; margin-bottom: 0.25rem; }
    .panel span { color: var(--muted); font-size: 0.92rem; }
    button {
      appearance: none;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.03);
      color: var(--ink);
      padding: 0.65rem 1rem;
      border-radius: 2px;
      cursor: pointer;
      font: inherit;
    }
    button:hover { border-color: var(--accent); }
    .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.5rem; }
    pre {
      white-space: pre-wrap;
      color: var(--muted);
      font-size: 0.86rem;
      line-height: 1.45;
      max-height: 320px;
      overflow: auto;
      border-top: 1px solid var(--line);
      padding-top: 0.75rem;
    }
    .alert {
      border-left: 3px solid var(--accent);
      padding: 0.5rem 0 0.5rem 0.75rem;
      margin: 0.4rem 0;
    }
    .err { color: var(--short); }
  </style>
</head>
<body>
  <header>
    <h1 class="brand">ATLAS</h1>
    <p class="tag">Adaptive Trading, Learning and Analysis System — apoio à decisão para BTC. NO TRADE é válido. Sem promessa de lucro.</p>
    <div class="actions">
      <button id="btn-refresh">Atualizar</button>
      <button id="btn-run">Rodar análise</button>
    </div>
  </header>
  <main>
    <div class="hero-decision">
      <div id="decision" class="decision">—</div>
      <div id="meta" class="meta">Carregando…</div>
    </div>
    <section>
      <h2>Especialistas</h2>
      <div id="specialists" class="row"></div>
    </section>
    <section>
      <h2>Alertas</h2>
      <div id="alerts"></div>
    </section>
    <section>
      <h2>Resumo</h2>
      <pre id="summary"></pre>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    async function j(url, opts) {
      const r = await fetch(url, opts);
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    }
    function renderDecision(latest) {
      if (!latest) {
        $("decision").textContent = "Sem análise";
        $("meta").textContent = "Execute uma análise para começar.";
        return;
      }
      const d = latest.decision;
      const el = $("decision");
      el.textContent = d.decision;
      el.className = "decision " + d.decision;
      $("meta").textContent =
        `conf ${d.confidence.toFixed(2)} · dq ${d.data_quality.toFixed(2)} · ` +
        `${d.market_regime} · preço ${d.price ?? "—"} · ${latest.decision_id}`;
      $("summary").textContent = (latest.report_markdown || "").slice(0, 4000);
      const box = $("specialists");
      box.innerHTML = "";
      (d.specialist_votes || []).forEach((s) => {
        const div = document.createElement("div");
        div.className = "panel";
        div.innerHTML = `<strong>${s.specialist}</strong><span>${s.bias} · conf ${Number(s.confidence).toFixed(2)} · ${s.availability}</span>`;
        box.appendChild(div);
      });
    }
    function renderAlerts(items) {
      const box = $("alerts");
      if (!items.length) {
        box.innerHTML = '<div class="meta">Nenhum alerta recente.</div>';
        return;
      }
      box.innerHTML = items.slice(0, 8).map((a) =>
        `<div class="alert"><strong>${a.kind}</strong><div class="meta">${a.message}<br/>${a.created_at || ""}</div></div>`
      ).join("");
    }
    async function load() {
      try {
        let latest = null;
        try { latest = await j("/analysis/btc/latest"); } catch (_) {}
        renderDecision(latest);
        const alerts = await j("/alerts?limit=20");
        renderAlerts(alerts);
      } catch (e) {
        $("meta").innerHTML = `<span class="err">${e.message}</span>`;
      }
    }
    $("btn-refresh").onclick = load;
    $("btn-run").onclick = async () => {
      $("meta").textContent = "Rodando análise…";
      try {
        const out = await j("/analysis/btc/run?collect=true", { method: "POST" });
        renderDecision(out);
        const alerts = await j("/alerts?limit=20");
        renderAlerts(alerts);
      } catch (e) {
        $("meta").innerHTML = `<span class="err">${e.message}</span>`;
      }
    };
    load();
  </script>
</body>
</html>
"""
