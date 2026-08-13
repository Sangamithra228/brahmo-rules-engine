// Measured backend execution time. The 500ms figure is the assessment target.
export default function PipelineTiming({ timing }) {
  if (!timing) return null
  const total = timing.total_ms ?? 0
  const withinBudget = total < 500

  return (
    <span className="meta">
      Pipeline time{' '}
      <span className={`num font-medium ${withinBudget ? 'text-pass' : 'text-cut'}`}>
        {total.toFixed(2)} ms
      </span>
      <span className="text-muted"> / 500 ms target</span>
    </span>
  )
}
