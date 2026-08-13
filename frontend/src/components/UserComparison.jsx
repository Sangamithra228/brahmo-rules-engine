// Every row is a real pipeline run against the same graph.
export default function UserComparison({ runs, busy, onRun }) {
  if (runs.length === 0) {
    return (
      <div className="flex items-center gap-4 flex-wrap">
        <button className="btn-quiet" onClick={onRun} disabled={busy}>
          {busy ? 'Running…' : 'Run comparison'}
        </button>
        <span className="meta">
          Runs the pipeline once per user against the same 50-node graph.
        </span>
      </div>
    )
  }

  return (
    <div>
      <div className="overflow-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="text-[13px] border-b border-rule">
              <th scope="col" className="pb-2 pr-4">User</th>
              <th scope="col" className="pb-2 pr-4">Role</th>
              <th scope="col" className="pb-2 pr-4">Department</th>
              <th scope="col" className="pb-2 pr-4">Entry point</th>
              <th scope="col" className="pb-2 pr-4 text-right">BFS reach</th>
              <th scope="col" className="pb-2 pr-4 text-right">Candidates</th>
              <th scope="col" className="pb-2 text-right">Time</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.user} className="border-b border-rule">
                <td className="py-2 pr-4">{run.user_name}</td>
                <td className="py-2 pr-4">{run.role}</td>
                <td className="py-2 pr-4">{run.department}</td>
                <td className="py-2 pr-4 num text-[12px]">{run.entry_point}</td>
                <td className="py-2 pr-4 num text-right">{run.funnel.after_bfs}</td>
                <td className="py-2 pr-4 num text-right font-semibold">
                  {run.candidate_set.length}
                </td>
                <td className="py-2 num text-right">
                  {run.pipeline_timing.total_ms} ms
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="meta mt-3">
        Same graph, same pipeline. The results differ because the user profile
        differs.
      </p>
      <button className="btn-quiet mt-3" onClick={onRun} disabled={busy}>
        {busy ? 'Running…' : 'Re-run comparison'}
      </button>
    </div>
  )
}
