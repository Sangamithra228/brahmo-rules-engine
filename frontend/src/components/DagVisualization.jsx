import { useMemo } from 'react'

/**
 * The hierarchy DAG, drawn as an indented tree from the org root.
 *
 * Deliberately hand-rolled rather than pulling in a graph library: the
 * structure is a shallow tree of twenty tiers, and the only thing the
 * evaluator needs to read off it is which tiers this user can reach.
 *
 * Note what is shown - hierarchy TIERS, not knowledge nodes. Marking a tier
 * unreachable reveals nothing about what it contains, so this panel cannot
 * become a side channel around silent exclusion.
 */

function Legend() {
  const items = [
    ['bg-ink ring-4 ring-pass-soft', 'entry point'],
    ['bg-pass', 'reachable'],
    ['bg-transparent border border-rule-strong', 'not reachable'],
    ['bg-zone2 rotate-45 rounded-none', 'zone 2 / global'],
  ]
  return (
    <div className="flex flex-wrap gap-4 pb-3 mb-2 border-b border-rule">
      {items.map(([cls, label]) => (
        <span key={label} className="flex items-center gap-2 font-mono text-[10px] text-muted">
          <span className={`w-2 h-2 rounded-full ${cls}`} />
          {label}
        </span>
      ))}
    </div>
  )
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
    const roots = hierarchy.filter((h) => !h.parent_ids.length).map((h) => h.id)

    const out = []
    const seen = new Set()
    const walk = (id, depth) => {
      if (seen.has(id)) return
      seen.add(id)
      out.push({ ...byId[id], depth })
      ;(children[id] || []).sort().forEach((c) => walk(c, depth + 1))
    }
    roots.forEach((r) => walk(r, 0))
    return out
  }, [hierarchy])

  const reachable = useMemo(
    () => new Set(traversal?.reachable_levels || []),
    [traversal]
  )
  const entry = traversal?.entry_point

  return (
    <div>
      <Legend />
      <div className="font-mono text-[12px] max-h-[26rem] overflow-auto">
        {rows.map((r) => {
          const isReachable = reachable.has(r.id)
          const isEntry = r.id === entry
          const dot = isEntry
            ? 'bg-ink ring-4 ring-pass-soft'
            : r.zone === 2
              ? 'bg-zone2 rounded-none rotate-45'
              : isReachable
                ? 'bg-pass'
                : 'bg-transparent border border-rule-strong'

          return (
            <div
              key={r.id}
              className={`flex items-center gap-2 py-0.5 ${
                isReachable ? 'text-ink' : 'text-rule-strong'
              }`}
              style={{ paddingLeft: `${r.depth * 15}px` }}
            >
              <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
              <span className="text-[10px] text-muted w-7 shrink-0">L{r.level_number}</span>
              <span className="truncate">{r.level_name}</span>
              {r.parent_ids.length > 1 && (
                <span className="text-[10px] text-muted shrink-0">◇ multi-parent</span>
              )}
              {isEntry && (
                <span className="text-[9px] tracking-widest bg-ink text-white
                                 px-1.5 py-px rounded-sm shrink-0">
                  ENTRY
                </span>
              )}
            </div>
          )
        })}
      </div>

      {traversal?.blocked_foreign_parents?.length > 0 && (
        <p className="font-mono text-[11px] text-muted mt-3 pt-3 border-t border-rule
                      border-l-2 border-l-rule-strong pl-2.5">
          Refused to ascend into co-parent departments:{' '}
          <span className="text-ink">
            {traversal.blocked_foreign_parents.join(', ')}
          </span>
          . A jointly-owned node is not a bridge into the co-owner&apos;s subtree.
        </p>
      )}
    </div>
  )
}
