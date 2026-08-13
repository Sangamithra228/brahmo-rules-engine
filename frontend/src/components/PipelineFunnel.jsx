import { useEffect, useState } from 'react'

/**
 * The filter funnel, and the centrepiece of the demo.
 *
 * Each stage is a bar whose ground is hatched. The solid fill is what
 * survived; the hatching still showing through is what the check removed. The
 * evaluator can see the shape of every cut rather than only the survivors.
 */

const STAGES = [
  { key: 'total_nodes', label: 'Total graph', tone: 'neutral' },
  { key: 'after_bfs', label: 'BFS reach', tone: 'neutral' },
  { key: 'after_zone2', label: '+ Zone 2', tone: 'zone2' },
  { key: 'after_isolation', label: '1 · Isolation', tone: 'pass' },
  { key: 'after_compliance', label: '2 · Compliance', tone: 'pass' },
  { key: 'after_permission', label: '3 · Permission', tone: 'pass' },
  { key: 'after_temporal', label: '4 · Temporal', tone: 'pass' },
  { key: 'after_derivability', label: '5 · Derivability', tone: 'pass' },
]

const TONE = {
  neutral: 'bg-[#E4EAE9] border-rule-strong',
  zone2: 'bg-zone2-soft border-zone2',
  pass: 'bg-pass-soft border-pass',
}

export default function PipelineFunnel({ funnel, finalCount }) {
  const [armed, setArmed] = useState(false)

  // Re-arm on every new result so the bars animate down the stages again.
  useEffect(() => {
    setArmed(false)
    const id = requestAnimationFrame(() => setArmed(true))
    return () => cancelAnimationFrame(id)
  }, [funnel])

  if (!funnel) return null
  const max = funnel.total_nodes || 1
  let previous = null

  return (
    <div className="space-y-1">
      {STAGES.map((stage, i) => {
        const value = funnel[stage.key] ?? 0
        const delta = previous === null ? null : value - previous
        previous = value
        const pct = Math.max((value / max) * 100, 2.5)

        return (
          <div
            key={stage.key}
            className="grid grid-cols-[7.5rem_1fr_5rem] sm:grid-cols-[9rem_1fr_6rem]
                       gap-3 items-center"
          >
            <div
              className={`font-mono text-[11px] uppercase tracking-wider text-right ${
                delta ? 'text-ink font-semibold' : 'text-muted'
              }`}
            >
              {stage.label}
            </div>

            <div className="relative h-8 border border-rule rounded-sm overflow-hidden sieve-track">
              <div
                className={`sieve-fill absolute inset-y-0 left-0 border-r-2 ${TONE[stage.tone]}`}
                style={{
                  width: armed ? `${pct}%` : '0%',
                  transition: 'width .45s cubic-bezier(.3,.8,.35,1)',
                  transitionDelay: `${i * 70}ms`,
                }}
              />
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 font-mono
                               text-[13px] font-semibold z-10">
                {value}
              </span>
            </div>

            <div className="font-mono text-[12px]">
              {delta === null && <span className="text-rule-strong">of {max}</span>}
              {delta === 0 && <span className="text-rule-strong">—</span>}
              {delta > 0 && <span className="text-zone2">+{delta}</span>}
              {delta < 0 && <span className="text-cut">−{Math.abs(delta)} cut</span>}
            </div>
          </div>
        )
      })}

      <div className="grid grid-cols-[7.5rem_1fr_5rem] sm:grid-cols-[9rem_1fr_6rem]
                      gap-3 items-center pt-2 mt-1 border-t border-rule">
        <div className="font-mono text-[11px] uppercase tracking-wider text-right
                        font-semibold">
          Candidate set
        </div>
        <div className="font-mono text-2xl font-semibold">{finalCount}</div>
        <div />
      </div>
    </div>
  )
}
