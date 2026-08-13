/**
 * Real backend timing. The budget is 500ms; the bar shows how much of it the
 * run actually used.
 */

export default function PipelineTiming({ timing }) {
  if (!timing) return null

  const total = timing.total_ms ?? 0
  const budget = 500
  const used = Math.min((total / budget) * 100, 100)
  const withinBudget = total < budget

  const parts = [
    ['compile', timing.permission_compile_ms],
    ['entry', timing.entry_point_ms],
    ['bfs', timing.bfs_ms],
    ['zone 2', timing.zone2_inject_ms],
    ['5 checks', timing.check_isolation_ms != null
      ? Number((timing.check_isolation_ms * 5).toFixed(3)) : null],
    ['assemble', timing.assemble_ms],
  ].filter(([, v]) => v != null)

  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-3 flex-wrap">
        <span className="font-mono text-2xl font-semibold">{total.toFixed(2)} ms</span>
        <span className={`font-mono text-[11px] uppercase tracking-wider ${
          withinBudget ? 'text-pass' : 'text-cut'
        }`}>
          {withinBudget ? 'within 500 ms budget' : 'over budget'}
        </span>
      </div>

      <div className="h-1.5 bg-rule rounded-sm overflow-hidden">
        <div
          className={withinBudget ? 'h-full bg-pass' : 'h-full bg-cut'}
          style={{ width: `${Math.max(used, 0.5)}%` }}
        />
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-muted">
        {parts.map(([label, value]) => (
          <span key={label}>
            {label} <span className="text-ink font-semibold">{value}</span>
          </span>
        ))}
      </div>
    </div>
  )
}
