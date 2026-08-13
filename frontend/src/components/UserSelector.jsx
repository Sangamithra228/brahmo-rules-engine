import { useState } from 'react'

/**
 * User selection and pipeline controls.
 *
 * The profile panel renders whatever the backend returned for the selected
 * user; nothing about any specific person is baked in here. The "unseen
 * profile" form builds a user that exists in no database, which is how the
 * surprise-user test is run live.
 */

const ROLES = ['VIEWER', 'EDITOR', 'HOD', 'QUALITY', 'AUDITOR', 'ADMIN']

function Fact({ label, value }) {
  return (
    <div className="pr-6 mr-6 border-r border-rule last:border-r-0 last:mr-0 last:pr-0">
      <div className="label">{label}</div>
      <div className="font-mono text-sm">{value ?? '—'}</div>
    </div>
  )
}

export default function UserSelector({
  users, selectedId, onSelect, profile, options, onOptionChange,
  onRun, onRunAdhoc, busy,
}) {
  const [open, setOpen] = useState(false)
  const [adhoc, setAdhoc] = useState({
    name: 'External Auditor', role: 'AUDITOR', department: 'audit',
    ceiling: 3, clearance: 'MNPI',
  })

  const set = (k) => (e) => setAdhoc({ ...adhoc, [k]: e.target.value })

  return (
    <section className="panel">
      <div className="p-4">
        <div className="flex flex-wrap gap-4 items-end">
          <div className="flex flex-col gap-1.5">
            <label className="label" htmlFor="user">Session user</label>
            <select
              id="user" className="control min-w-[16rem]" value={selectedId}
              onChange={(e) => onSelect(e.target.value)}
            >
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} — {u.role}, L{u.ceiling_level}, {u.department}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="label" htmlFor="mode">Permission mode</label>
            <select
              id="mode" className="control" value={options.mode}
              onChange={(e) => onOptionChange('mode', e.target.value)}
            >
              <option value="strict">strict</option>
              <option value="scope_aware">scope_aware</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="label" htmlFor="thr">Derivability</label>
            <input
              id="thr" type="number" min="0" max="1" step="0.05"
              className="control w-24" value={options.threshold}
              onChange={(e) => onOptionChange('threshold', e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="label">Zone 2 injection</span>
            <button
              type="button"
              aria-pressed={options.zone2}
              onClick={() => onOptionChange('zone2', !options.zone2)}
              className={`font-mono text-[12px] uppercase tracking-[0.1em] px-4 py-2
                          rounded-sm border transition-colors ${
                            options.zone2
                              ? 'bg-pass border-pass text-white'
                              : 'bg-transparent border-rule-strong text-ink hover:bg-wash'
                          }`}
            >
              {options.zone2 ? 'On' : 'Off'}
            </button>
          </div>

          <button className="btn" onClick={onRun} disabled={busy}>
            {busy ? 'Running…' : 'Run pipeline'}
          </button>
        </div>

        {profile && (
          <div className="flex flex-wrap mt-4 pt-3 border-t border-rule">
            <Fact label="Name" value={profile.name} />
            <Fact label="Role" value={profile.role} />
            <Fact label="Department" value={profile.department} />
            <Fact label="Hierarchy ceiling" value={`L${profile.ceiling_level}`} />
            <Fact
              label="Compliance clearance"
              value={profile.compliance_clearance?.length
                ? profile.compliance_clearance.join(', ')
                : 'none'}
            />
            <Fact label="Organization" value={profile.org_id} />
          </div>
        )}

        <div className="mt-3">
          <button
            type="button" onClick={() => setOpen(!open)}
            className="label hover:text-ink"
          >
            {open ? '▾' : '▸'} Test an unseen profile
          </button>

          {open && (
            <div className="mt-3 pt-3 border-t border-rule">
              <div className="flex flex-wrap gap-3 items-end">
                <div className="flex flex-col gap-1.5">
                  <label className="label" htmlFor="a-name">Name</label>
                  <input id="a-name" className="control w-44"
                         value={adhoc.name} onChange={set('name')} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="label" htmlFor="a-role">Role</label>
                  <select id="a-role" className="control w-36"
                          value={adhoc.role} onChange={set('role')}>
                    {ROLES.map((r) => <option key={r}>{r}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="label" htmlFor="a-dept">Department</label>
                  <input id="a-dept" className="control w-36"
                         value={adhoc.department} onChange={set('department')} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="label" htmlFor="a-ceil">Ceiling</label>
                  <input id="a-ceil" type="number" min="1" max="15"
                         className="control w-20"
                         value={adhoc.ceiling} onChange={set('ceiling')} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="label" htmlFor="a-clr">Clearance</label>
                  <input id="a-clr" className="control w-36" placeholder="MNPI,PHI"
                         value={adhoc.clearance} onChange={set('clearance')} />
                </div>
                <button className="btn-ghost" disabled={busy}
                        onClick={() => onRunAdhoc(adhoc)}>
                  Run this profile
                </button>
              </div>
              <p className="font-mono text-[11px] text-muted mt-3">
                Nothing is written to the database. The profile is assembled at
                request time and pushed through the same pipeline, because every
                rule reads profile fields rather than names.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
