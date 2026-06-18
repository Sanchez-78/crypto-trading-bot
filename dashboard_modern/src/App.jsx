import { useState, useEffect } from 'react'

export default function App() {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [positions, setPositions] = useState([])
  const [trades, setTrades] = useState([])

  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const resp = await fetch('/api/dashboard/metrics')
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const data = await resp.json()
        setMetrics(data)
        setError(null)
        if (data.open_positions_list) setPositions(data.open_positions_list)
      } catch (e) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }

    fetchMetrics()
    const interval = setInterval(fetchMetrics, 5000)
    return () => clearInterval(interval)
  }, [])

  if (loading) return <div className="loading">Loading metrics...</div>
  if (error) return <div className="loading" style={{color: '#f87171'}}>Error: {error}</div>
  if (!metrics) return <div className="loading">No data available</div>

  return (
    <div className="container">
      <div className="header">
        <h1>🤖 CryptoMaster Live Dashboard</h1>
        <p style={{color: '#888', fontSize: '13px'}}>Last update: {new Date(metrics.last_update).toLocaleTimeString()}</p>
      </div>

      <div className="metrics">
        <div className="metric-card">
          <div className="metric-label">Win Rate</div>
          <div className={`metric-value ${metrics.win_rate_pct > 50 ? 'positive' : metrics.win_rate_pct > 0 ? 'neutral' : 'negative'}`}>{Math.round(metrics.win_rate_pct || 0)}%</div>
          <div style={{fontSize: '11px', color: '#666', marginTop: '8px'}}>
            {metrics.exit_distribution.tp} TP / {metrics.exit_distribution.sl} SL / {metrics.exit_distribution.timeout} TO
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-label">Profit Factor</div>
          <div className={`metric-value ${metrics.pf > 1 ? 'positive' : 'negative'}`}>{metrics.pf.toFixed(2)}x</div>
          <div style={{fontSize: '11px', color: '#666', marginTop: '8px'}}>
            {metrics.closed_trades} closed trades
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-label">Net P&L</div>
          <div className={`metric-value ${metrics.net_pnl > 0 ? 'positive' : 'negative'}`}>
            ${metrics.net_pnl.toFixed(2)}
          </div>
          <div style={{fontSize: '11px', color: '#666', marginTop: '8px'}}>
            {metrics.open_positions} open positions
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-label">Bot Status</div>
          <div className="metric-value positive">🟢 RUNNING</div>
          <div style={{fontSize: '11px', color: '#666', marginTop: '8px'}}>
            Paper trading active
          </div>
        </div>
      </div>

      <div className="tables">
        <div>
          <h3 style={{marginBottom: '15px', fontSize: '16px'}}>Open Positions ({positions.length})</h3>
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Current</th>
                <th>P&L %</th>
                <th>Hold</th>
              </tr>
            </thead>
            <tbody>
              {positions.slice(0, 10).map(p => (
                <tr key={p.trade_id}>
                  <td>{p.symbol}</td>
                  <td style={{color: p.side === 'BUY' ? '#4ade80' : '#f87171'}}>{p.side}</td>
                  <td>{p.entry_price.toFixed(4)}</td>
                  <td>{p.current_price.toFixed(4)}</td>
                  <td className={p.pnl_pct > 0 ? 'status-ok' : 'status-fail'}>
                    {(p.pnl_pct > 0 ? '+' : '')}{p.pnl_pct.toFixed(2)}%
                  </td>
                  <td>{Math.round(p.current_hold_s)}s / {p.max_hold_s}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <h3 style={{marginBottom: '15px', fontSize: '16px'}}>Exit Distribution</h3>
          <table>
            <thead>
              <tr>
                <th>Exit Type</th>
                <th>Count</th>
                <th>%</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(metrics.exit_distribution).map(([type, count]) => (
                <tr key={type}>
                  <td style={{textTransform: 'capitalize'}}>{type}</td>
                  <td>{count}</td>
                  <td>
                    {metrics.closed_trades > 0
                      ? Math.round((count / metrics.closed_trades) * 100)
                      : 0}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
