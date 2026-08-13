import { Fragment, useMemo, useState } from 'react'

const TYPE_LABEL = {
  CONSTRAINT: 'text-cut',
  DECISION: 'text-pass',
  ANTI_PATTERN: 'text-zone2',
  FACT: 'text-muted',
}
const ORDER = ['CONSTRAINT', 'DECISION', 'ANTI_PATTERN', 'FACT']

export default function CandidateTable({ candidates }) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return candidates
    return candidates.filter((c) =>
      [c.id, c.title, c.content, c.type].some((f) =>
        f?.toLowerCase().includes(q)
      )
    )
  }, [candidates, query])

  const groups = ORDER
    .map((t) => [t, filtered.filter((c) => c.type === t)])
    .filter(([, list]) => list.length)

  return (
    <div>
      <label className="sr-only" htmlFor="cand-filter">Filter candidates</label>
      <input
        id="cand-filter" type="search" className="control w-full mb-3"
        placeholder="Filter by title, content or ID"
        value={query} onChange={(e) => setQuery(e.target.value)}
      />

      {filtered.length === 0 ? (
        <p className="meta py-3">
          {candidates.length === 0
            ? 'No nodes survived the pipeline for this user.'
            : 'No candidates match that filter.'}
        </p>
      ) : (
        <div className="max-h-[26rem] overflow-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="text-[13px] sticky top-0 bg-white">
                <th scope="col" className="pb-2 pr-3">Content</th>
                <th scope="col" className="pb-2 pr-3 w-16 text-right">Imp.</th>
                <th scope="col" className="pb-2 pr-3 w-14 text-right">Dist.</th>
                <th scope="col" className="pb-2 pr-3 w-20 text-right">Zone</th>
                <th scope="col" className="pb-2 w-32 text-right">Compression</th>
              </tr>
            </thead>
            <tbody>
              {groups.map(([type, list]) => (
                <Fragment key={type}>
                  <tr>
                    <td colSpan={5}
                        className={`pt-4 pb-1 text-[13px] font-medium ${TYPE_LABEL[type]}`}>
                      {type.replace('_', ' ')} · {list.length}
                    </td>
                  </tr>
                  {list.map((c) => (
                    <tr key={c.id} className="border-b border-rule align-top">
                      <td className="py-2 pr-3">
                        <div className="flex gap-2">
                          <span className="num text-[12px] text-muted shrink-0 pt-0.5">
                            {c.id}
                          </span>
                          <span>
                            <span className="block">{c.title}</span>
                            <span className="block text-[13px] text-muted leading-snug">
                              {c.content}
                            </span>
                          </span>
                        </div>
                      </td>
                      <td className="py-2 pr-3 num text-right">
                        {Number(c.importance).toFixed(2)}
                      </td>
                      <td className="py-2 pr-3 num text-right">
                        {c.distance_from_entry}
                      </td>
                      <td className="py-2 pr-3 num text-right whitespace-nowrap">
                        <span className={c.zone === 2 ? 'text-zone2' : ''}>
                          Z{c.zone}
                        </span>
                        <span className="text-muted"> L{c.hierarchy_level}</span>
                      </td>
                      <td className="py-2 text-right text-[13px] whitespace-nowrap">
                        {c.compression_hint}
                      </td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
