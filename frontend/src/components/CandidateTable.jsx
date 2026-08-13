import { Fragment, useMemo, useState } from 'react'

/**
 * The final candidate set - the actual contract handed to the downstream
 * Composition Agent.
 *
 * There is no "hidden nodes" count and no placeholder row for anything
 * removed, because the response the backend sent contains no such
 * information. What you see is the whole of what this user is given.
 */

const TYPE_STYLE = {
  CONSTRAINT: 'bg-cut-soft text-cut',
  DECISION: 'bg-pass-soft text-pass',
  ANTI_PATTERN: 'bg-[#FBE8D8] text-[#9A4A12]',
  FACT: 'bg-[#E6ECF4] text-[#3A5578]',
}

const ORDER = ['CONSTRAINT', 'DECISION', 'ANTI_PATTERN', 'FACT']

export default function CandidateTable({ candidates }) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return candidates
    return candidates.filter(
      (c) =>
        c.id.toLowerCase().includes(q) ||
        c.title?.toLowerCase().includes(q) ||
        c.content?.toLowerCase().includes(q) ||
        c.type.toLowerCase().includes(q)
    )
  }, [candidates, query])

  const groups = ORDER.map((t) => [t, filtered.filter((c) => c.type === t)])
    .filter(([, list]) => list.length)

  return (
    <div>
      <input
        type="search" className="control w-full mb-3"
        placeholder="Filter candidates…" value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      <div className="max-h-[26rem] overflow-auto">
        {filtered.length === 0 && (
          <p className="font-mono text-[12px] text-muted py-4">
            {candidates.length === 0
              ? 'No nodes survived the pipeline for this user.'
              : 'Nothing matches that filter.'}
          </p>
        )}

        <table className="w-full text-[12.5px] border-collapse">
          <tbody>
            {groups.map(([type, list]) => (
              <Fragment key={type}>
                <tr>
                  <td colSpan={7}
                      className="font-mono text-[10px] uppercase tracking-[0.1em]
                                 text-muted pt-4 pb-1">
                    {type.replace('_', ' ')} · {list.length}
                  </td>
                </tr>
                {list.map((c) => (
                  <tr key={c.id} className="border-b border-wash align-top">
                    <td className="font-mono text-[11px] text-muted py-2 pr-2 whitespace-nowrap">
                      {c.id}
                    </td>
                    <td className="py-2 pr-2">
                      <div className="font-medium">{c.title}</div>
                      <div className="text-muted text-[11.5px] leading-snug mt-0.5
                                      line-clamp-2">
                        {c.content}
                      </div>
                    </td>
                    <td className="py-2 pr-2">
                      <span className={`font-mono text-[9.5px] px-1.5 py-0.5 rounded-sm
                                        whitespace-nowrap ${TYPE_STYLE[c.type]}`}>
                        {c.type}
                      </span>
                    </td>
                    <td className="font-mono text-[11.5px] text-right py-2 pr-2">
                      {Number(c.importance).toFixed(2)}
                    </td>
                    <td className="font-mono text-[11.5px] text-right py-2 pr-2 whitespace-nowrap">
                      Z{c.zone} · L{c.hierarchy_level}
                    </td>
                    <td className="font-mono text-[11.5px] text-right py-2 pr-2">
                      d={c.distance_from_entry}
                    </td>
                    <td className="font-mono text-[10px] text-right py-2 whitespace-nowrap">
                      <div>{c.compression_hint}</div>
                      <div className={c.source === 'ZONE2' ? 'text-zone2' : 'text-muted'}>
                        {c.source}
                      </div>
                    </td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
