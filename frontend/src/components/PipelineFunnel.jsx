import { useEffect, useState } from 'react'

// Stage counts come straight from the backend funnel object. The bar width is
// the only thing computed here.
const STAGES = [
  { key: 'total_nodes', label: 'Total graph' },
  { key: 'after_bfs', label: 'BFS reach' },
  { key: 'after_zone2', label: 'Zone 2 injected', tone: 'zone2' },
  { key: 'after_isolation', label: '1. Isolation' },
  { key: 'after_compliance', label: '2. Compliance' },
  { key: 'after_permission', label: '3. Permission' },
  { key: 'after_temporal', label: '4. Temporal' },
  { key: 'after_derivability', label: '5. Derivability' },
]

export default function PipelineFunnel({ funnel, finalCount }) {
  const [armed, setArmed] = useState(false)

  useEffect(() => {
    setArmed(false)
    const id = requestAnimationFrame(() => setArmed(true))
    return () => cancelAnimationFrame(id)
  }, [funnel])

  if (!funnel) return null
  const max = funnel.total_nodes || 1
  let previous = null

  return (
    <table className="w-full border-collapse">
      <caption className="sr-only">
        Node count remaining after each pipeline stage
      </caption>
      <thead>
        <tr className="text-[13px]">
          <th scope="col" className="pb-2 w-44">Stage</th>
          <th scope="col" className="pb-2">Remaining</th>
          <th scope="col" className="pb-2 w-16 text-right">Count</th>
          <th scope="col" className="pb-2 w-20 text-right">Removed</th>
        </tr>
      </thead>
      <tbody>
        {STAGES.map((stage) => {
          const value = funnel[stage.key] ?? 0
          const delta = previous === null ? null : value - previous
          previous = value
          const pct = Math.max((value / max) * 100, 1)
          const fill =
            stage.tone === 'zone2'
              ? 'bg-zone2-soft border-zone2'
              : 'bg-pass-soft border-pass'

          return (
            <tr key={stage.key} className="align-middle">
              <th scope="row" className="py-1 pr-3 font-normal text-ink">
                {stage.label}
              </th>
              <td className="py-1">
                <div className="h-5 bg-wash border border-rule">
                  <div
                    className={`h-full border-r-2 ${fill}`}
                    style={{
                      width: armed ? `${pct}%` : '0%',
                      transition: 'width .3s ease-out',
                    }}
                  />
                </div>
              </td>
              <td className="py-1 pl-3 num text-right">{value}</td>
              <td className="py-1 pl-3 num text-right text-[13px]">
                {delta === null && <span className="text-muted">—</span>}
                {delta === 0 && <span className="text-muted">0</span>}
                {delta > 0 && <span className="text-zone2">+{delta}</span>}
                {delta < 0 && <span className="text-cut">−{Math.abs(delta)}</span>}
              </td>
            </tr>
          )
        })}
        <tr className="border-t border-rule">
          <th scope="row" className="pt-2 pr-3 font-semibold text-ink">
            Candidate set
          </th>
          <td />
          <td className="pt-2 pl-3 num text-right font-semibold text-base">
            {finalCount}
          </td>
          <td />
        </tr>
      </tbody>
    </table>
  )
}
