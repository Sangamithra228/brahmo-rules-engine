import { useCallback, useEffect, useState } from 'react'

import CandidateTable from '../components/CandidateTable'
import DagVisualization from '../components/DagVisualization'
import PipelineFunnel from '../components/PipelineFunnel'
import PipelineTiming from '../components/PipelineTiming'
import UserComparison from '../components/UserComparison'
import UserSelector from '../components/UserSelector'
import {
  comparePipelines, getHealth, getHierarchy, getUsers, runPipeline,
} from '../services/api'

function Panel({ title, aside, children }) {
  return (
    <section className="panel">
      <div className="panel-hd">
        <h2 className="panel-ttl">{title}</h2>
        {aside}
      </div>
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
  // Only Zone 2 is demo-controllable. The derivability threshold and
  // permission mode come from organization configuration on the backend.
  const [options, setOptions] = useState({ zone2: true })
  const [busy, setBusy] = useState(false)
  const [comparing, setComparing] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    ;(async () => {
      try {
        const [h, u, hier] = await Promise.all([getHealth(), getUsers(), getHierarchy()])
        setHealth(h)
        setUsers(u)
        setHierarchy(hier)
        setSelectedId(u[0]?.id ?? '')
      } catch (e) {
        setError(
          `Cannot reach the backend (${e.message}). Start it with: uvicorn backend.main:app --port 8000`
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

  // Re-run on any change so the screen always shows a real result for the
  // current settings.
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
    setOptions((o) => ({ ...o, [key]: value }))
  }

  const dbLabel = health?.database_backend === 'supabase'
    ? 'Supabase / PostgreSQL'
    : health?.database_backend === 'sqlite'
      ? 'SQLite (local fallback)'
      : '—'

  return (
    <div className="min-h-screen">
      <header className="bg-ink text-white">
        <div className="max-w-[1200px] mx-auto px-5 py-3
                        flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <div className="flex items-baseline gap-3 flex-wrap">
            <h1 className="text-[15px] font-semibold">BRAHMO Rules Engine</h1>
            <p className="text-[13px] text-[#9CB3AF]">
              Deterministic Knowledge Graph → Candidate Set
            </p>
          </div>
          {health && (
            <p className="text-[13px] text-[#9CB3AF]">
              Zero LLM · Deterministic · {dbLabel} · {health.nodes} nodes
              {!health.graph_acyclic && (
                <span className="text-white"> · cycle detected</span>
              )}
            </p>
          )}
        </div>
      </header>

      <main className="max-w-[1200px] mx-auto px-5 py-4 pb-14 space-y-4">
        {error && (
          <div role="alert" className="panel border-cut">
            <p className="p-3 text-cut">{error}</p>
          </div>
        )}

        <UserSelector
          users={users}
          selectedId={selectedId}
          onSelect={setSelectedId}
          profile={result?.user_profile}
          options={options}
          onOptionChange={setOption}
          effectiveThreshold={result?.options?.derivability_threshold}
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
            <Panel
              title="Filter pipeline"
              aside={
                <span className="meta">
                  Entry point <span className="num">{result.entry_point}</span>
                  {' · '}
                  <PipelineTiming timing={result.pipeline_timing} />
                </span>
              }
            >
              <PipelineFunnel
                funnel={result.funnel}
                finalCount={result.candidate_set.length}
              />
            </Panel>

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
              <Panel
                title="Hierarchy traversal"
                aside={
                  <span className="meta">
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
                  <span className="meta">
                    {result.candidate_set.length} nodes
                  </span>
                }
              >
                <CandidateTable candidates={result.candidate_set} />
              </Panel>
            </div>
          </>
        )}

        <Panel title="User comparison">
          <UserComparison runs={comparison} busy={comparing} onRun={runComparison} />
        </Panel>
      </main>
    </div>
  )
}
