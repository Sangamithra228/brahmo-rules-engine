/**
 * Same graph, different people.
 *
 * Every column here is a separate real pipeline run against the same 50-node
 * graph. The counts are whatever the backend returned - if they were
 * hardcoded, changing the derivability threshold or toggling Zone 2 would not
 * move them, and it does.
 *
 * The probe rows show specific nodes appearing or not appearing per user,
 * which is the most direct way to see the checks doing their job.
 */

const PROBES = [
  ['Ortho budget (MNPI)', 'N-O11'],
  ['Vendor strategy (MNPI+CONF)', 'N-O12'],
  ['Cardiology trial (MNPI+CONF)', 'N-C04'],
  ['Warfarin/NSAID (Zone 2)', 'N-G01'],
  ['Sepsis v2 (superseded)', 'N-M08'],
  ['TKR definition (derivable)', 'N-D01'],
]

export default function UserComparison({ runs, busy, onRun }) {
  return (
    <div>
      {runs.length === 0 && (
        <div className="flex items-center gap-4 flex-wrap">
          <button className="btn-ghost" onClick={onRun} disabled={busy}>
            {busy ? 'Running…' : 'Compare all users'}
          </button>
          <span className="font-mono text-[11px] text-muted">
            Runs the pipeline once per user against the same graph.
          </span>
        </div>
      )}

      {runs.length > 0 && (
        <div className="grid gap-px bg-rule border border-rule
                        grid-cols-[repeat(auto-fit,minmax(13rem,1fr))]">
          {runs.map((run) => {
            const ids = new Set(run.candidate_set.map((c) => c.id))
            return (
              <div key={run.user} className="bg-white">
                <div className="px-3 pt-3">
                  <div className="font-mono text-[13px] font-semibold truncate">
                    {run.user_name}
                  </div>
                  <div className="font-mono text-[10.5px] text-muted mt-0.5">
                    {run.role} · L{run.ceiling_level} · {run.department}
                  </div>
                </div>

                <div className="text-center py-3 my-3 border-y border-rule">
                  <div className="font-mono text-3xl font-semibold leading-none">
                    {run.candidate_set.length}
                  </div>
                  <div className="label mt-1">nodes</div>
                </div>

                <div className="px-3 pb-3 font-mono text-[11px] space-y-1">
                  <div className="flex justify-between">
                    <span className="text-muted">BFS reach</span>
                    <span>{run.funnel.after_bfs}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">+ Zone 2</span>
                    <span>{run.funnel.after_zone2}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">entry</span>
                    <span className="truncate ml-2" title={run.entry_point}>
                      {run.entry_point?.replace('HL-', '')}
                    </span>
                  </div>
                  <div className="flex justify-between pb-1 border-b border-wash">
                    <span className="text-muted">time</span>
                    <span>{run.pipeline_timing.total_ms} ms</span>
                  </div>

                  {PROBES.map(([label, nodeId]) => {
                    const present = ids.has(nodeId)
                    // For stale/derivable nodes, present == leak.
                    const shouldBeAbsent = nodeId === 'N-M08' || nodeId === 'N-D01'
                    const good = shouldBeAbsent ? !present : present
                    return (
                      <div key={nodeId} className="flex justify-between gap-2">
                        <span className="text-muted truncate" title={label}>{label}</span>
                        <span className={good ? 'text-pass font-semibold' : 'text-cut'}>
                          {present ? (shouldBeAbsent ? 'LEAK' : 'visible') : 'absent'}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
