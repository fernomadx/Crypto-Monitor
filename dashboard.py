"""
dashboard.py — Web dashboard para visualizar dados do crypto-monitor.

Uso:
    python dashboard.py          # http://localhost:5000
    python dashboard.py --port 8080
"""

import argparse
import sqlite3
import os
import json
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template_string

DB_PATH = os.environ.get("DB_PATH", "./data/crypto_monitor.db")

app = Flask(__name__)


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql, params=()):
    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── API routes ────────────────────────────────────────────────────────────

@app.route("/api/prices")
def api_prices():
    rows = query("""
        SELECT source, ticker, price, ts
        FROM price_snapshots
        ORDER BY ts DESC
        LIMIT 200
    """)
    return jsonify(rows)


@app.route("/api/prices/latest")
def api_prices_latest():
    rows = query("""
        SELECT source, ticker, price, ts
        FROM price_snapshots
        WHERE (source, ticker, ts) IN (
            SELECT source, ticker, MAX(ts)
            FROM price_snapshots
            GROUP BY source, ticker
        )
        ORDER BY ticker, source
    """)
    return jsonify(rows)


@app.route("/api/funding")
def api_funding():
    rows = query("""
        SELECT ticker, funding, mark_price, ts, alerted
        FROM funding_rates
        ORDER BY ts DESC
        LIMIT 200
    """)
    return jsonify(rows)


@app.route("/api/funding/latest")
def api_funding_latest():
    rows = query("""
        SELECT ticker, funding, mark_price, ts
        FROM funding_rates
        WHERE (ticker, ts) IN (
            SELECT ticker, MAX(ts)
            FROM funding_rates
            GROUP BY ticker
        )
        ORDER BY ticker
    """)
    return jsonify(rows)


@app.route("/api/news")
def api_news():
    rows = query("""
        SELECT source, title, url, vader_score, haiku_score, haiku_summary, alerted, ts
        FROM news_articles
        ORDER BY ts DESC
        LIMIT 50
    """)
    return jsonify(rows)


@app.route("/api/portfolio")
def api_portfolio():
    rows = query("""
        SELECT source, asset, amount, usd_value, ts
        FROM portfolio
        ORDER BY ts DESC
        LIMIT 50
    """)
    return jsonify(rows)


@app.route("/api/orchestrator")
def api_orchestrator():
    rows = query("""
        SELECT summary, ts
        FROM orchestrator_log
        ORDER BY ts DESC
        LIMIT 10
    """)
    return jsonify(rows)


@app.route("/api/stats")
def api_stats():
    conn = get_conn()
    try:
        stats = {}
        for table in ["funding_rates", "price_snapshots", "portfolio", "news_articles", "orchestrator_log"]:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            stats[table] = row["cnt"]
        return jsonify(stats)
    finally:
        conn.close()


# ── Dashboard ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="pt-BR" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Monitor — Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        dark: { 900: '#0b0f19', 800: '#111827', 700: '#1e293b', 600: '#334155' },
                        neon: { green: '#00ff88', red: '#ff4466', blue: '#3b82f6', yellow: '#fbbf24', purple: '#a855f7' }
                    }
                }
            }
        }
    </script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap');
        body { font-family: 'Inter', sans-serif; background: #0b0f19; }
        .mono { font-family: 'JetBrains Mono', monospace; }
        .glass { background: rgba(17, 24, 39, 0.8); backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.06); }
        .glow-green { box-shadow: 0 0 20px rgba(0,255,136,0.1); }
        .glow-blue { box-shadow: 0 0 20px rgba(59,130,246,0.1); }
        .pulse-dot { animation: pulse 2s infinite; }
        @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #111827; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        .fade-in { animation: fadeIn 0.5s ease-out; }
        @keyframes fadeIn { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
        .sentiment-bar { height: 6px; border-radius: 3px; transition: width 0.5s ease; }
    </style>
</head>
<body class="text-gray-200 min-h-screen">

<!-- Header -->
<header class="glass sticky top-0 z-50 border-b border-gray-800/50">
    <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-3">
            <div class="text-2xl">📡</div>
            <div>
                <h1 class="text-lg font-bold text-white">Crypto Monitor</h1>
                <p class="text-xs text-gray-500">Dashboard em tempo real</p>
            </div>
        </div>
        <div class="flex items-center gap-4">
            <div class="flex items-center gap-2 text-xs text-gray-400">
                <span class="pulse-dot w-2 h-2 bg-green-400 rounded-full inline-block"></span>
                <span id="last-update">Carregando...</span>
            </div>
            <button onclick="refreshAll()" class="px-3 py-1.5 text-xs font-medium bg-gray-700 hover:bg-gray-600 rounded-lg transition">
                ↻ Atualizar
            </button>
        </div>
    </div>
</header>

<main class="max-w-7xl mx-auto px-4 py-6 space-y-6">

    <!-- Price Cards -->
    <section id="price-cards" class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="glass rounded-xl p-5 glow-green fade-in" id="card-BTC">
            <div class="flex justify-between items-start">
                <div>
                    <p class="text-xs text-gray-400 uppercase tracking-wider">Bitcoin</p>
                    <p class="text-3xl font-bold text-white mono mt-1" id="price-BTC">—</p>
                </div>
                <span class="text-3xl">₿</span>
            </div>
            <div class="mt-3 flex items-center gap-2">
                <span class="text-xs text-gray-500">Funding:</span>
                <span class="text-xs mono" id="funding-BTC">—</span>
            </div>
        </div>
        <div class="glass rounded-xl p-5 glow-blue fade-in" id="card-ETH">
            <div class="flex justify-between items-start">
                <div>
                    <p class="text-xs text-gray-400 uppercase tracking-wider">Ethereum</p>
                    <p class="text-3xl font-bold text-white mono mt-1" id="price-ETH">—</p>
                </div>
                <span class="text-3xl">⟠</span>
            </div>
            <div class="mt-3 flex items-center gap-2">
                <span class="text-xs text-gray-500">Funding:</span>
                <span class="text-xs mono" id="funding-ETH">—</span>
            </div>
        </div>
        <div class="glass rounded-xl p-5 fade-in" style="box-shadow: 0 0 20px rgba(168,85,247,0.1);" id="card-SOL">
            <div class="flex justify-between items-start">
                <div>
                    <p class="text-xs text-gray-400 uppercase tracking-wider">Solana</p>
                    <p class="text-3xl font-bold text-white mono mt-1" id="price-SOL">—</p>
                </div>
                <span class="text-3xl">◎</span>
            </div>
            <div class="mt-3 flex items-center gap-2">
                <span class="text-xs text-gray-500">Funding:</span>
                <span class="text-xs mono" id="funding-SOL">—</span>
            </div>
        </div>
    </section>

    <!-- Charts Row -->
    <section class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- Price History Chart -->
        <div class="glass rounded-xl p-5">
            <h2 class="text-sm font-semibold text-gray-300 mb-4">📈 Histórico de Preços</h2>
            <div style="height: 280px;">
                <canvas id="priceChart"></canvas>
            </div>
        </div>
        <!-- Funding History Chart -->
        <div class="glass rounded-xl p-5">
            <h2 class="text-sm font-semibold text-gray-300 mb-4">💸 Funding Rates</h2>
            <div style="height: 280px;">
                <canvas id="fundingChart"></canvas>
            </div>
        </div>
    </section>

    <!-- Stats Bar -->
    <section class="glass rounded-xl p-4">
        <div class="grid grid-cols-2 md:grid-cols-5 gap-4" id="stats-bar">
            <div class="text-center">
                <p class="text-2xl font-bold text-white mono" id="stat-funding">—</p>
                <p class="text-xs text-gray-500">Funding Rates</p>
            </div>
            <div class="text-center">
                <p class="text-2xl font-bold text-white mono" id="stat-prices">—</p>
                <p class="text-xs text-gray-500">Price Snapshots</p>
            </div>
            <div class="text-center">
                <p class="text-2xl font-bold text-white mono" id="stat-portfolio">—</p>
                <p class="text-xs text-gray-500">Portfolio</p>
            </div>
            <div class="text-center">
                <p class="text-2xl font-bold text-white mono" id="stat-news">—</p>
                <p class="text-xs text-gray-500">Artigos</p>
            </div>
            <div class="text-center">
                <p class="text-2xl font-bold text-white mono" id="stat-consensus">—</p>
                <p class="text-xs text-gray-500">Consensus</p>
            </div>
        </div>
    </section>

    <!-- Bottom Row -->
    <section class="grid grid-cols-1 lg:grid-cols-2 gap-4">

        <!-- News Feed -->
        <div class="glass rounded-xl p-5">
            <h2 class="text-sm font-semibold text-gray-300 mb-4">📰 Últimas Notícias</h2>
            <div class="space-y-3 max-h-96 overflow-y-auto pr-2" id="news-feed">
                <p class="text-gray-500 text-sm">Carregando...</p>
            </div>
        </div>

        <!-- Funding Table -->
        <div class="glass rounded-xl p-5">
            <h2 class="text-sm font-semibold text-gray-300 mb-4">💰 Funding Rates — Histórico</h2>
            <div class="overflow-x-auto max-h-96 overflow-y-auto">
                <table class="w-full text-sm">
                    <thead class="text-xs text-gray-400 uppercase sticky top-0 bg-gray-900/90">
                        <tr>
                            <th class="text-left py-2 px-2">Hora</th>
                            <th class="text-left py-2 px-2">Ticker</th>
                            <th class="text-right py-2 px-2">Funding</th>
                            <th class="text-right py-2 px-2">Mark Price</th>
                        </tr>
                    </thead>
                    <tbody id="funding-table" class="mono text-xs">
                        <tr><td colspan="4" class="text-gray-500 py-4 text-center">Carregando...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </section>

    <!-- Orchestrator Consensus -->
    <section class="glass rounded-xl p-5">
        <h2 class="text-sm font-semibold text-gray-300 mb-4">🧠 Consensus — Sínteses do Orchestrator</h2>
        <div class="space-y-4" id="consensus-feed">
            <p class="text-gray-500 text-sm">Nenhuma síntese disponível ainda.</p>
        </div>
    </section>

</main>

<footer class="text-center py-6 text-xs text-gray-600">
    crypto-monitor dashboard · dados atualizados a cada 60s
</footer>

<script>
let priceChart = null;
let fundingChart = null;

function fmt(n, decimals=2) {
    return n != null ? Number(n).toLocaleString('en-US', {minimumFractionDigits: decimals, maximumFractionDigits: decimals}) : '—';
}

function fmtTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts);
    return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

function fmtDate(ts) {
    if (!ts) return '—';
    const d = new Date(ts);
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

function fundingColor(val) {
    if (val == null) return 'text-gray-400';
    const abs = Math.abs(val);
    if (abs >= 0.0005) return val > 0 ? 'text-green-400' : 'text-red-400';
    return 'text-gray-300';
}

function sentimentColor(score) {
    if (score == null) return '#6b7280';
    if (score > 0.5) return '#00ff88';
    if (score > 0.2) return '#4ade80';
    if (score < -0.5) return '#ff4466';
    if (score < -0.2) return '#f87171';
    return '#fbbf24';
}

function sentimentLabel(score) {
    if (score == null) return '';
    if (score > 0.5) return 'Bullish 🚀';
    if (score > 0.2) return 'Levemente bullish';
    if (score < -0.5) return 'Bearish 💀';
    if (score < -0.2) return 'Levemente bearish';
    return 'Neutro';
}

async function fetchJSON(url) {
    const resp = await fetch(url);
    return resp.json();
}

async function loadPrices() {
    const latest = await fetchJSON('/api/prices/latest');
    const all = await fetchJSON('/api/prices');

    for (const row of latest) {
        const el = document.getElementById(`price-${row.ticker}`);
        if (el) el.textContent = `$${fmt(row.price)}`;
    }

    // Build chart
    const tickers = [...new Set(all.map(r => r.ticker))];
    const colors = { BTC: '#f7931a', ETH: '#627eea', SOL: '#9945ff' };

    const datasets = tickers.map(ticker => {
        const points = all.filter(r => r.ticker === ticker && r.source === 'hyperliquid')
            .reverse()
            .map(r => ({ x: new Date(r.ts), y: r.price }));
        return {
            label: ticker,
            data: points,
            borderColor: colors[ticker] || '#3b82f6',
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 2,
            tension: 0.3
        };
    });

    if (priceChart) priceChart.destroy();
    const ctx = document.getElementById('priceChart').getContext('2d');
    priceChart = new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            scales: {
                x: {
                    type: 'timeseries',
                    time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
                    ticks: { color: '#6b7280', font: { size: 10 } },
                    grid: { color: 'rgba(255,255,255,0.04)' }
                },
                y: {
                    ticks: { color: '#6b7280', font: { size: 10 }, callback: v => '$' + v.toLocaleString() },
                    grid: { color: 'rgba(255,255,255,0.04)' }
                }
            },
            plugins: {
                legend: { labels: { color: '#9ca3af', font: { size: 11 } } },
                tooltip: {
                    callbacks: { label: ctx => `${ctx.dataset.label}: $${fmt(ctx.parsed.y)}` }
                }
            }
        }
    });
}

async function loadFunding() {
    const latest = await fetchJSON('/api/funding/latest');
    const all = await fetchJSON('/api/funding');

    for (const row of latest) {
        const el = document.getElementById(`funding-${row.ticker}`);
        if (el) {
            const pct = (row.funding * 100).toFixed(4);
            el.textContent = `${row.funding > 0 ? '+' : ''}${pct}%`;
            el.className = `text-xs mono ${fundingColor(row.funding)}`;
        }
    }

    // Table
    const tbody = document.getElementById('funding-table');
    if (all.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-gray-500 py-4 text-center">Sem dados</td></tr>';
    } else {
        tbody.innerHTML = all.slice(0, 50).map(r => `
            <tr class="border-t border-gray-800/50 hover:bg-gray-800/30">
                <td class="py-1.5 px-2 text-gray-400">${fmtTime(r.ts)}</td>
                <td class="py-1.5 px-2 font-semibold text-white">${r.ticker}</td>
                <td class="py-1.5 px-2 text-right ${fundingColor(r.funding)}">${(r.funding*100).toFixed(4)}%</td>
                <td class="py-1.5 px-2 text-right text-gray-300">$${fmt(r.mark_price)}</td>
            </tr>
        `).join('');
    }

    // Chart
    const tickers = [...new Set(all.map(r => r.ticker))];
    const colors = { BTC: '#f7931a', ETH: '#627eea', SOL: '#9945ff' };

    const datasets = tickers.map(ticker => {
        const points = all.filter(r => r.ticker === ticker)
            .reverse()
            .map(r => ({ x: new Date(r.ts), y: r.funding * 100 }));
        return {
            label: ticker,
            data: points,
            borderColor: colors[ticker] || '#3b82f6',
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 2,
            tension: 0.3
        };
    });

    if (fundingChart) fundingChart.destroy();
    const ctx = document.getElementById('fundingChart').getContext('2d');
    fundingChart = new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            scales: {
                x: {
                    type: 'timeseries',
                    time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
                    ticks: { color: '#6b7280', font: { size: 10 } },
                    grid: { color: 'rgba(255,255,255,0.04)' }
                },
                y: {
                    ticks: { color: '#6b7280', font: { size: 10 }, callback: v => v.toFixed(4) + '%' },
                    grid: { color: 'rgba(255,255,255,0.04)' }
                }
            },
            plugins: {
                legend: { labels: { color: '#9ca3af', font: { size: 11 } } },
                tooltip: {
                    callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(4)}%` }
                }
            }
        }
    });
}

async function loadNews() {
    const news = await fetchJSON('/api/news');
    const feed = document.getElementById('news-feed');

    if (news.length === 0) {
        feed.innerHTML = '<p class="text-gray-500 text-sm">Nenhum artigo registrado ainda.</p>';
        return;
    }

    feed.innerHTML = news.map(a => {
        const score = a.haiku_score ?? a.vader_score;
        const barWidth = score != null ? Math.abs(score) * 100 : 0;
        const barColor = sentimentColor(score);
        return `
        <div class="p-3 rounded-lg bg-gray-800/40 hover:bg-gray-800/60 transition">
            <div class="flex items-start justify-between gap-2">
                <div class="flex-1 min-w-0">
                    ${a.url ? `<a href="${a.url}" target="_blank" class="text-sm text-gray-200 hover:text-white leading-snug line-clamp-2">${a.title}</a>` : `<p class="text-sm text-gray-200 leading-snug line-clamp-2">${a.title}</p>`}
                    <div class="flex items-center gap-3 mt-1.5">
                        <span class="text-[10px] text-gray-500 uppercase">${a.source}</span>
                        <span class="text-[10px] text-gray-500">${fmtDate(a.ts)}</span>
                        ${score != null ? `<span class="text-[10px] mono" style="color:${barColor}">${sentimentLabel(score)} (${score > 0 ? '+' : ''}${score.toFixed(2)})</span>` : ''}
                    </div>
                    ${a.haiku_summary ? `<p class="text-xs text-gray-400 mt-1 italic">"${a.haiku_summary}"</p>` : ''}
                </div>
                ${a.alerted ? '<span class="text-xs">🔔</span>' : ''}
            </div>
            ${score != null ? `<div class="mt-2 w-full bg-gray-700/50 rounded-full"><div class="sentiment-bar" style="width:${barWidth}%;background:${barColor}"></div></div>` : ''}
        </div>`;
    }).join('');
}

async function loadStats() {
    const stats = await fetchJSON('/api/stats');
    document.getElementById('stat-funding').textContent = stats.funding_rates ?? 0;
    document.getElementById('stat-prices').textContent = stats.price_snapshots ?? 0;
    document.getElementById('stat-portfolio').textContent = stats.portfolio ?? 0;
    document.getElementById('stat-news').textContent = stats.news_articles ?? 0;
    document.getElementById('stat-consensus').textContent = stats.orchestrator_log ?? 0;
}

async function loadConsensus() {
    const logs = await fetchJSON('/api/orchestrator');
    const feed = document.getElementById('consensus-feed');

    if (logs.length === 0) {
        feed.innerHTML = '<p class="text-gray-500 text-sm">Nenhuma síntese disponível — o orchestrator roda a cada 4h.</p>';
        return;
    }

    feed.innerHTML = logs.map(l => `
        <div class="p-4 rounded-lg bg-gray-800/40 border-l-2 border-neon-blue">
            <p class="text-xs text-gray-500 mb-2">${fmtDate(l.ts)}</p>
            <p class="text-sm text-gray-300 whitespace-pre-line leading-relaxed">${l.summary}</p>
        </div>
    `).join('');
}

async function refreshAll() {
    await Promise.all([loadPrices(), loadFunding(), loadNews(), loadStats(), loadConsensus()]);
    document.getElementById('last-update').textContent = `Atualizado ${new Date().toLocaleTimeString('pt-BR')}`;
}

// Initial load + auto-refresh
refreshAll();
setInterval(refreshAll, 60000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Monitor Dashboard")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    print(f"🚀 Dashboard: http://localhost:{args.port}")
    app.run(host=args.host, port=args.port, debug=True)
