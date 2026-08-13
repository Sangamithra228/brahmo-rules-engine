import { useCallback, useEffect, useState } from 'react'

import CandidateTable from '../components/CandidateTable'
import DagVisualization from '../components/DagVisualization'
import PipelineFunnel from '../components/PipelineFunnel'
import PipelineStats from '../components/PipelineStats'
import PipelineTiming from '../components/PipelineTiming'
import UserComparison from '../components/UserComparison'
import UserSelector from '../components/UserSelector'
import {
  comparePipelines, getHealth, getHierarchy, getUsers, runPipeline,
} from '../services/api'

function Badge({ children, tone = 'quiet' }) {
  const cls = tone === 'live'
    ? 'border-[#6FBFAA] text-[#B7E4D8]'
    : 'border-ink-line text-[#9CC7BE]'
  return (
    <span className={`font-mono text-[11px] uppercase tracking-[0.08em]
                      border px-2.5 py-1 rounded-sm ${cls}`}>
      {children}
    </span>
  )
}

function Panel({ title, aside, children, className = '' }) {
  return (
    <section className={`panel ${className}`}>
      {(title || aside) && (
        <div className="panel-hd">
          {title && <h2 className="panel-title">{title}</h2>}
          {aside}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export default function Dashboard() {
  const [health, setHealth] = useState(null)
  const [users, setUsers] = useState([])
  const [hierarchy, setHierarchy] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [result, setResult] = useState(null)
  const [comparison, setComparison] = useState([])
  const [options, setOptions] = useState({
    zone2: true, threshold: 0.7, mode: 'strict',
  })
  const [busy, setBusy] = useState(false)
  const [comparing, setComparing] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    ;(async () => {
      try {
        const [h, u, hier] = await Promise.all([
          getHealth(), getUsers(), getHierarchy(),
        ])
        setHealth(h)
        setUsers(u)
        setHierarchy(hier)
        setSelectedId(u[0]?.id ?? '')
      } catch (e) {
        setError(
          `${e.message}. Start the backend: uvicorn backend.main:app --port 8000`
        )
      }
    })()
  }, [])

  const run = useCallback(
    async (body) => {
      setBusy(true)
      setError(null)
      try {
        setResult(await runPipeline({ ...options, ...body }))
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    },
    [options]
  )

  // Re-run whenever the user or any option changes, so what is on screen is
  // always a real result for the current settings.
  useEffect(() => {
    if (selectedId) run({ user: selectedId })
  }, [selectedId, options, run])

  const runComparison = async () => {
    setComparing(true)
    try {
      setComparison(await comparePipelines(users.map((u) => u.id), options))
    } catch (e) {
      setError(e.message)
    } finally {
      setComparing(false)
    }
  }

  const setOption = (key, value) => {
    setComparison([])
    setOptions((o) => ({
      ...o,
      [key]: key === 'threshold' ? Number(value) : value,
    }))
  }

  return (
    <div className="min-h-screen">
      <header className="bg-ink text-[#EAF2F0] py-5">
        <div className="max-w-[1280px] mx-auto px-5 flex flex-wrap gap-4
                        items-baseline justify-between">
          <div>
            <h1 className="font-mono text-[15px] font-semibold uppercase
                           tracking-[0.14em] m-0">
              BRAHMO <span className="text-[#6FBFAA]">/</span> Rules Engine
            </h1>
            <p className="font-mono text-[12px] text-[#8FA8A4] mt-1">
              Deterministic Knowledge Graph → Candidate Set
            </p>
          </div>
          <div className="flex gap-2 flex-wrap">
            <Badge tone="live">Zero LLM</Badge>
            <Badge tone="live">Deterministic</Badge>
            <Badge tone="live">Security-aware</Badge>
            {health && (
              <>
                <Badge>{health.nodes} nodes</Badge>
                <Badge>db: {health.database_backend}</Badge>
                <Badge>{health.graph_acyclic ? 'DAG verified' : 'CYCLE FOUND'}</Badge>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-[1280px] mx-auto px-5 pb-16 pt-5 space-y-4">
        {error && (
          <div className="panel border-cut">
            <div className="p-4 font-mono text-[12px] text-cut">{error}</div>
          </div>
        )}

        <UserSelector
          users={users}
          selectedId={selectedId}
          onSelect={setSelectedId}
          profile={result?.user_profile}
          options={options}
          onOptionChange={setOption}
          onRun={() => run({ user: selectedId })}
          onRunAdhoc={(p) =>
            run({
              user: null,
              role: p.role,
              department: p.department,
              ceiling: Number(p.ceiling),
              name: p.name,
              clearance: p.clearance
                ? p.clearance.split(',').map((c) => c.trim()).filter(Boolean)
                : [],
            })
          }
          busy={busy}
        />

        {result && (
          <>
            <Panel title="Pipeline overview">
              <PipelineStats
                funnel={result.funnel}
                finalCount={result.candidate_set.length}
                entryPoint={result.entry_point}
              />
            </Panel>

            <Panel
              title="Filter funnel — where every node was lost"
              aside={
                <span className="font-mono text-[11px] text-muted">
                  hatching shows what each check removed
                </span>
              }
            >
              <PipelineFunnel
                funnel={result.funnel}
                finalCount={result.candidate_set.length}
              />
              {result.notes?.length > 0 && (
                <div className="mt-4 space-y-1.5">
                  {result.notes.map((n) => (
                    <p key={n} className="font-mono text-[11px] text-muted
                                          border-l-2 border-rule-strong pl-2.5">
                      {n}
                    </p>
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="Execution time">
              <PipelineTiming timing={result.pipeline_timing} />
            </Panel>

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
              <Panel
                title="Hierarchy DAG"
                aside={
                  <span className="font-mono text-[11px] text-muted">
                    {result.traversal?.reachable_levels?.length ?? 0} of{' '}
                    {hierarchy.length} tiers reachable
                  </span>
                }
              >
                <DagVisualization
                  hierarchy={hierarchy}
                  traversal={result.traversal}
                />
              </Panel>

              <Panel
                title="Candidate set"
                aside={
                  <span className="font-mono text-[11px] text-muted">
                    {result.candidate_set.length} nodes
                  </span>
                }
              >
                <CandidateTable candidates={result.candidate_set} />
              </Panel>
            </div>
          </>
        )}

        <Panel
          title="Same graph, different people"
          aside={
            comparison.length > 0 && (
              <button className="btn-ghost" onClick={runComparison} disabled={comparing}>
                {comparing ? 'Running…' : 'Re-run comparison'}
              </button>
            )
          }
        >
          <UserComparison runs={comparison} busy={comparing} onRun={runComparison} />
        </Panel>
      </main>
    </div>
  )
}
