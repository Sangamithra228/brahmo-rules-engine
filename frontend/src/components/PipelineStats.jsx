/**
 * The funnel as discrete figures, for evaluators who want to read the numbers
 * rather than the bars. Every value comes from the backend response.
 */

export default function PipelineStats({ funnel, finalCount, entryPoint }) {
  if (!funnel) return null

  const cells = [
    ['Total nodes', funnel.total_nodes],
    ['BFS reachable', funnel.after_bfs],
    ['After Zone 2', funnel.after_zone2],
    ['After Isolation', funnel.after_isolation],
    ['After Compliance', funnel.after_compliance],
    ['After Permission', funnel.after_permission],
    ['After Temporal', funnel.after_temporal],
    ['After Derivability', funnel.after_derivability],
    ['Final candidates', finalCount],
    ['Entry point', entryPoint],
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 border-t border-l border-rule">
      {cells.map(([label, value]) => (
        <div key={label} className="border-r border-b border-rule px-3 py-2.5">
          <div className="label">{label}</div>
          <div className="font-mono text-lg font-semibold truncate" title={String(value)}>
            {value}
          </div>
        </div>
      ))}
    </div>
  )
}
