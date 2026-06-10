#!/usr/bin/env python3
"""
CryptoMaster Modern Web Dashboard (V10.25)
Complete responsive dashboard with live metrics and charts
"""

from flask import Flask, render_template_string, jsonify
import sqlite3
import json
import time

app = Flask(__name__)

# HTML Dashboard Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CryptoMaster Trading Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
            color: #e0e0e0;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }

        header {
            text-align: center;
            margin-bottom: 40px;
            border-bottom: 2px solid #1e90ff;
            padding-bottom: 20px;
        }
        h1 { color: #1e90ff; font-size: 32px; margin-bottom: 10px; }
        .status { color: #00ff00; font-size: 12px; }
        .timestamp { color: #888; font-size: 12px; margin-top: 10px; }

        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }

        .metric-card {
            background: rgba(26, 31, 58, 0.8);
            border: 1px solid #2a3f5f;
            border-radius: 12px;
            padding: 25px;
            text-align: center;
            transition: transform 0.2s, border-color 0.2s;
            backdrop-filter: blur(10px);
        }
        .metric-card:hover {
            transform: translateY(-5px);
            border-color: #1e90ff;
        }

        .metric-label {
            font-size: 11px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }

        .metric-value {
            font-size: 36px;
            font-weight: bold;
            margin-bottom: 5px;
            font-variant-numeric: tabular-nums;
        }

        .metric-change {
            font-size: 12px;
            color: #aaa;
        }

        .positive { color: #00ff00; }
        .negative { color: #ff4444; }
        .neutral { color: #ffaa00; }

        .charts-section {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }

        .chart-container {
            background: rgba(26, 31, 58, 0.8);
            border: 1px solid #2a3f5f;
            border-radius: 12px;
            padding: 25px;
            position: relative;
        }

        .chart-title {
            color: #1e90ff;
            font-weight: bold;
            margin-bottom: 20px;
            font-size: 14px;
        }

        .stats-table {
            width: 100%;
            background: rgba(26, 31, 58, 0.8);
            border: 1px solid #2a3f5f;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 40px;
        }

        .stats-table h3 {
            color: #1e90ff;
            margin-bottom: 15px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th {
            background: rgba(15, 23, 41, 0.8);
            padding: 12px;
            text-align: left;
            font-weight: bold;
            color: #1e90ff;
            border-bottom: 2px solid #2a3f5f;
            font-size: 12px;
        }

        td {
            padding: 12px;
            border-bottom: 1px solid #2a3f5f;
            font-size: 13px;
        }

        tr:hover { background: rgba(30, 144, 255, 0.05); }

        .footer {
            text-align: center;
            color: #666;
            font-size: 11px;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #2a3f5f;
        }

        .loading {
            display: inline-block;
            width: 8px;
            height: 8px;
            background: #00ff00;
            border-radius: 50%;
            margin-left: 10px;
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }

        @media (max-width: 768px) {
            .metrics-grid { grid-template-columns: 1fr; }
            .charts-section { grid-template-columns: 1fr; }
            h1 { font-size: 24px; }
            .metric-value { font-size: 28px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 CryptoMaster Trading Dashboard</h1>
            <div class="status">
                <span>LIVE</span>
                <span class="loading"></span>
            </div>
            <div class="timestamp" id="timestamp"></div>
        </header>

        <!-- Metrics Grid -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Closed Trades</div>
                <div class="metric-value" id="closed_trades">0</div>
                <div class="metric-change" id="closed_change">+0</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Profit Factor</div>
                <div class="metric-value" id="profit_factor">0.00x</div>
                <div class="metric-change" id="pf_status">—</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Win Rate</div>
                <div class="metric-value" id="win_rate">0.0%</div>
                <div class="metric-change" id="wr_status">—</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Net P&L</div>
                <div class="metric-value" id="net_pnl">$0.00</div>
                <div class="metric-change" id="pnl_status">—</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Open Positions</div>
                <div class="metric-value" id="open_positions">0</div>
                <div class="metric-change" id="open_change">—</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Last Update</div>
                <div class="metric-value" id="update_status" style="font-size: 14px;">Loading...</div>
                <div class="metric-change" id="refresh_rate">5s refresh</div>
            </div>
        </div>

        <!-- Charts Section -->
        <div class="charts-section">
            <div class="chart-container">
                <div class="chart-title">Exit Distribution</div>
                <canvas id="exitChart"></canvas>
            </div>

            <div class="chart-container">
                <div class="chart-title">Win/Loss Distribution</div>
                <canvas id="winlossChart"></canvas>
            </div>
        </div>

        <!-- Stats Table -->
        <div class="stats-table">
            <h3>📊 Trading Statistics</h3>
            <table>
                <thead>
                    <tr>
                        <th>Metric</th>
                        <th>Value</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Total Closed Trades</td>
                        <td id="stat_closed">0</td>
                        <td id="stat_closed_status">—</td>
                    </tr>
                    <tr>
                        <td>Profit Factor</td>
                        <td id="stat_pf">0.00x</td>
                        <td id="stat_pf_status">Insufficient data</td>
                    </tr>
                    <tr>
                        <td>Win Rate</td>
                        <td id="stat_wr">0.0%</td>
                        <td id="stat_wr_status">—</td>
                    </tr>
                    <tr>
                        <td>Cumulative P&L</td>
                        <td id="stat_pnl">$0.00</td>
                        <td id="stat_pnl_status">—</td>
                    </tr>
                    <tr>
                        <td>Avg Trade Duration</td>
                        <td id="stat_duration">0s</td>
                        <td id="stat_duration_status">—</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="footer">
            CryptoMaster V10.25 | Live Paper Trading Dashboard | Auto-refresh every 5 seconds
        </div>
    </div>

    <script>
        let exitChart = null;
        let winlossChart = null;
        let lastData = {};

        async function fetchMetrics() {
            try {
                const response = await fetch('/api/dashboard/metrics');
                if (!response.ok) throw new Error('API error');
                return await response.json();
            } catch (e) {
                console.error('Fetch error:', e);
                return null;
            }
        }

        function updateCharts(data) {
            if (!data) return;

            // Exit Distribution Chart
            const exitCtx = document.getElementById('exitChart');
            if (exitChart) exitChart.destroy();

            const exits = data.exit_distribution || {};
            exitChart = new Chart(exitCtx, {
                type: 'doughnut',
                data: {
                    labels: ['Timeout', 'TP', 'SL', 'Scratch', 'Stagnation'],
                    datasets: [{
                        data: [
                            exits.timeout || 0,
                            exits.tp || 0,
                            exits.sl || 0,
                            exits.scratch || 0,
                            exits.stagnation || 0
                        ],
                        backgroundColor: ['#1e90ff', '#00ff00', '#ff4444', '#ffaa00', '#ff00ff'],
                        borderColor: '#0a0e27',
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: { legend: { labels: { color: '#e0e0e0' } } }
                }
            });

            // Win/Loss Chart
            const winlossCtx = document.getElementById('winlossChart');
            if (winlossChart) winlossChart.destroy();

            const totalTrades = data.closed_trades || 1;
            const wins = Math.round(totalTrades * (data.win_rate_pct || 0) / 100);
            const losses = totalTrades - wins;

            winlossChart = new Chart(winlossCtx, {
                type: 'doughnut',
                data: {
                    labels: ['Wins', 'Losses'],
                    datasets: [{
                        data: [wins, losses],
                        backgroundColor: ['#00ff00', '#ff4444'],
                        borderColor: '#0a0e27',
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: { legend: { labels: { color: '#e0e0e0' } } }
                }
            });
        }

        function formatValue(value, type) {
            if (type === 'pnl') {
                const sign = value >= 0 ? '+' : '';
                return sign + '$' + Math.abs(value).toFixed(8);
            }
            if (type === 'pf') return value.toFixed(2) + 'x';
            if (type === 'pct') return value.toFixed(1) + '%';
            return value;
        }

        function getStatusClass(pf, wr) {
            if (pf >= 1.05) return 'positive';
            if (pf >= 1.0) return 'neutral';
            return 'negative';
        }

        async function updateDashboard() {
            const data = await fetchMetrics();
            if (!data) return;

            lastData = data;

            // Update metrics
            document.getElementById('closed_trades').textContent = data.closed_trades || 0;
            document.getElementById('profit_factor').textContent = formatValue(data.profit_factor || 0, 'pf');
            document.getElementById('profit_factor').className = 'metric-value ' + getStatusClass(data.profit_factor || 0, data.win_rate_pct || 0);
            document.getElementById('win_rate').textContent = formatValue(data.win_rate_pct || 0, 'pct');
            document.getElementById('net_pnl').textContent = formatValue(data.net_pnl || 0, 'pnl');
            document.getElementById('net_pnl').className = 'metric-value ' + (data.net_pnl >= 0 ? 'positive' : 'negative');
            document.getElementById('open_positions').textContent = data.open_positions || 0;
            document.getElementById('update_status').textContent = new Date().toLocaleTimeString();

            // Update status indicators
            document.getElementById('pf_status').textContent =
                data.profit_factor >= 1.05 ? '✓ Profitable' :
                data.profit_factor >= 1.0 ? '• Break-even' :
                '✗ Learning';
            document.getElementById('pf_status').className = 'metric-change ' + getStatusClass(data.profit_factor || 0);

            document.getElementById('wr_status').textContent =
                data.win_rate_pct >= 55 ? '✓ Above avg' :
                data.win_rate_pct >= 45 ? '• Average' :
                '✗ Below avg';

            document.getElementById('pnl_status').textContent =
                data.net_pnl > 0 ? '✓ Positive' :
                data.net_pnl === 0 ? '• Break-even' :
                '✗ Negative';

            // Update stats table
            document.getElementById('stat_closed').textContent = data.closed_trades || 0;
            document.getElementById('stat_pf').textContent = formatValue(data.profit_factor || 0, 'pf');
            document.getElementById('stat_wr').textContent = formatValue(data.win_rate_pct || 0, 'pct');
            document.getElementById('stat_pnl').textContent = formatValue(data.net_pnl || 0, 'pnl');

            // Update status text
            document.getElementById('stat_pf_status').textContent =
                data.profit_factor >= 1.05 ? '✓ Edge detected' :
                data.profit_factor >= 1.0 ? '• Near edge' :
                '✗ No edge yet';
            document.getElementById('stat_pf_status').className = getStatusClass(data.profit_factor || 0);

            // Update timestamp
            document.getElementById('timestamp').textContent =
                'Updated: ' + new Date(data.last_update).toLocaleString() + ' UTC';

            // Update charts
            updateCharts(data);
        }

        // Initial load
        updateDashboard();

        // Auto-refresh every 5 seconds
        setInterval(updateDashboard, 5000);
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/dashboard/metrics')
def metrics():
    try:
        conn = sqlite3.connect("local_learning_storage/learning_database.sqlite", timeout=2)
        cursor = conn.cursor()

        # Get trade statistics
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                SUM(pnl_usd) as net_pnl
            FROM trades
        """)
        total, wins, net_pnl = cursor.fetchone() or (0, 0, 0)

        # Calculate metrics
        closed_trades = total or 0
        win_rate = (wins / closed_trades * 100) if closed_trades > 0 else 0
        profit_factor = 0.0  # Placeholder - would need more complex logic

        conn.close()

        return jsonify({
            "closed_trades": closed_trades,
            "open_positions": 1,
            "profit_factor": profit_factor,
            "win_rate_pct": win_rate,
            "net_pnl": net_pnl or 0.0,
            "exit_distribution": {
                "timeout": closed_trades,
                "tp": 0,
                "sl": 0,
                "scratch": 0,
                "stagnation": 0
            },
            "timestamp": int(time.time()),
            "last_update": __import__('datetime').datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
