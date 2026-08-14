import { useMemo } from 'react'

// Shows hierarchy tiers only, never node identities, so this panel cannot
// reveal what the five checks removed.
function Marker({ kind }) {
  const base = 'inline-block w-2 h-2 shrink-0'
  if (kind === 'entry') return <span className={`${base} rounded-full bg-ink`} />
  if (kind === 'zone2') return <span className={`${base} rotate-45 bg-zone2`} />
  if (kind === 'reachable') return <span className={`${base} rounded-full bg-pass`} />
  return <span className={`${base} rounded-full border border-rule-strong`} />
}

export default function DagVisualization({ hierarchy, traversal }) {
  const rows = useMemo(() => {
    if (!hierarchy?.length) return []
    const byId = Object.fromEntries(hierarchy.map((h) => [h.id, h]))
    const children = {}
    hierarchy.forEach((h) =>
      h.parent_ids.forEach((p) => {
        ;(children[p] ||= []).push(h.id)
      })
    )
    const out = []
    const seen = new Set()
    const walk = (id, depth) => {
      if (seen.has(id)) return
      seen.add(id)
      out.push({ ...byId[id], depth })
      ;(children[id] || []).sort().forEach((c) => walk(c, depth + 1))
    }
    hierarchy.filter((h) => !h.parent_ids.length).forEach((h) => walk(h.id, 0))
    return out
  }, [hierarchy])

  const reachable = useMemo(
    () => new Set(traversal?.reachable_levels || []),
    [traversal]
  )
  const entry = traversal?.entry_point

  return (
    <div>
      <div className="flex flex-wrap gap-x-5 gap-y-1 pb-2 mb-2 border-b border-rule
                      text-[13px] text-muted">
        <span className="flex items-center gap-1.5"><Marker kind="entry" /> entry point</span>
        <span className="flex items-center gap-1.5"><Marker kind="reachable" /> reachable</span>
        <span className="flex items-center gap-1.5"><Marker kind="none" /> not reachable</span>
        <span className="flex items-center gap-1.5"><Marker kind="zone2" /> Zone 2</span>
      </div>

      <ul className="max-h-[24rem] overflow-auto">
        {rows.map((r) => {
          const isReachable = reachable.has(r.id)
          const kind = r.id === entry ? 'entry'
            : r.zone === 2 ? 'zone2'
            : isReachable ? 'reachable' : 'none'

          return (
            <li
              key={r.id}
              className={`flex items-center gap-2 py-0.5 ${
                isReachable ? 'text-ink' : 'text-muted'
              }`}
              style={{ paddingLeft: `${r.depth * 14}px` }}
            >
              <Marker kind={kind} />
              <span className="num text-[12px] text-muted w-7 shrink-0">
                L{r.level_number}
              </span>
              <span className="truncate">{r.level_name}</span>
              {r.parent_ids.length > 1 && (
                <span className="text-[13px] text-muted shrink-0">multi-parent</span>
              )}
              {r.id === entry && (
                <span className="text-[13px] font-medium shrink-0">entry</span>
              )}
            </li>
          )
        })}
      </ul>

      <p className="meta mt-3 pt-2 border-t border-rule">
        {traversal?.org_wide_scope
          ? 'This role has org-wide scope: the department has no tier in the DAG, so all tiers are in scope and the five checks do the filtering.'
          : `BFS walked up ${traversal?.ancestor_path?.length ?? 0} tier(s) from the entry point to the root.`}
        {traversal?.multi_parent_hits?.length > 0 && (
          <> Converging ancestors visited once:{' '}
            <span className="num">{traversal.multi_parent_hits.join(', ')}</span>.
          </>
        )}
      </p>
    </div>
  )
}
