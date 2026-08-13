/**
 * The only place that talks to the backend.
 *
 * Every number rendered anywhere in this app comes from these calls. Nothing
 * is computed client-side and nothing is hardcoded per user - switching the
 * dropdown re-runs the real pipeline.
 */

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = body.detail
    } catch {
      /* response had no JSON body; keep the status text */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const getHealth = () => request('/health')
export const getUsers = () => request('/users')
export const getUser = (id) => request(`/users/${encodeURIComponent(id)}`)
export const getHierarchy = () => request('/hierarchy')

/**
 * Run the pipeline.
 * Pass { user } for a seeded profile, or { role, department, ceiling,
 * clearance } to push an unseen profile through without writing to the
 * database - which is how the surprise-user test is demonstrated.
 */
export const runPipeline = (body) =>
  request('/pipeline/run', { method: 'POST', body: JSON.stringify(body) })

export const getRun = (runId) => request(`/pipeline/${runId}`)

export const comparePipelines = (userIds, opts = {}) => {
  const q = new URLSearchParams({ users: userIds.join(',') })
  if (opts.zone2 === false) q.set('zone2', 'false')
  if (opts.threshold != null) q.set('threshold', String(opts.threshold))
  if (opts.mode) q.set('mode', opts.mode)
  return request(`/pipeline/compare?${q}`)
}
