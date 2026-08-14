import { useState } from 'react'

const ROLES = ['VIEWER', 'EDITOR', 'HOD', 'QUALITY', 'AUDITOR', 'ADMIN']

function ProfileField({ label, value, mono }) {
  return (
    <div>
      <dt className="text-[13px] text-muted">{label}</dt>
      <dd className={mono ? 'num' : ''}>{value ?? '—'}</dd>
    </div>
  )
}

export default function UserSelector({
  users, selectedId, onSelect, profile, options, onOptionChange,
  effectiveThreshold, onRun, onRunAdhoc, busy,
}) {
  const [showAdhoc, setShowAdhoc] = useState(false)
  const [adhoc, setAdhoc] = useState({
    name: 'External Auditor', role: 'AUDITOR', department: 'audit',
    ceiling: 3, clearance: 'MNPI',
  })
  const set = (k) => (e) => setAdhoc({ ...adhoc, [k]: e.target.value })

  return (
    <section className="panel">
      <div className="p-4">
        <div className="flex flex-wrap gap-x-5 gap-y-3 items-end">
          <div>
            <label className="field-label" htmlFor="user">User</label>
            <select
              id="user" className="control min-w-[19rem]" value={selectedId}
              onChange={(e) => onSelect(e.target.value)}
            >
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} — {u.role} — L{u.ceiling_level} — {u.department}
                </option>
              ))}
            </select>
          </div>

          <button className="btn" onClick={onRun} disabled={busy}>
            {busy ? 'Running…' : 'Run pipeline'}
          </button>

          <div className="flex flex-wrap gap-x-5 gap-y-3 items-end ml-auto">
            <div>
              <label className="field-label" htmlFor="zone2">Zone 2 injection</label>
              <button
                id="zone2" type="button" aria-pressed={options.zone2}
                onClick={() => onOptionChange('zone2', !options.zone2)}
                className={`text-sm px-3.5 py-1.5 border ${
                  options.zone2
                    ? 'bg-pass-soft border-pass text-pass font-medium'
                    : 'bg-white border-rule-strong text-muted'
                }`}
              >
                {options.zone2 ? 'On' : 'Off'}
              </button>
            </div>
            <div>
              <span className="field-label">Derivability threshold</span>
              <p className="num py-1.5" title="Configured on the organization; not editable from the dashboard">
                {effectiveThreshold != null ? effectiveThreshold.toFixed(2) : '—'}
              </p>
            </div>
          </div>
        </div>

        {profile && (
          <dl className="flex flex-wrap gap-x-10 gap-y-2 mt-4 pt-3 border-t border-rule">
            <ProfileField label="Name" value={profile.name} />
            <ProfileField label="Role" value={profile.role} />
            <ProfileField label="Department" value={profile.department} />
            <ProfileField label="Ceiling" value={`L${profile.ceiling_level}`} mono />
            <ProfileField
              label="Compliance clearance"
              value={profile.compliance_clearance?.length
                ? profile.compliance_clearance.join(', ')
                : 'none'}
            />
            <ProfileField label="Organization" value={profile.org_id} mono />
          </dl>
        )}

        <div className="mt-3 pt-3 border-t border-rule">
          <button
            type="button" aria-expanded={showAdhoc}
            onClick={() => setShowAdhoc(!showAdhoc)}
            className="text-[13px] text-muted hover:text-ink"
          >
            {showAdhoc ? '▾' : '▸'} Test unseen profile
          </button>

          {showAdhoc && (
            <div className="mt-3">
              <div className="flex flex-wrap gap-x-4 gap-y-3 items-end">
                <div>
                  <label className="field-label" htmlFor="a-name">Name</label>
                  <input id="a-name" className="control w-44"
                         value={adhoc.name} onChange={set('name')} />
                </div>
                <div>
                  <label className="field-label" htmlFor="a-role">Role</label>
                  <select id="a-role" className="control w-32"
                          value={adhoc.role} onChange={set('role')}>
                    {ROLES.map((r) => <option key={r}>{r}</option>)}
                  </select>
                </div>
                <div>
                  <label className="field-label" htmlFor="a-dept">Department</label>
                  <input id="a-dept" className="control w-36"
                         value={adhoc.department} onChange={set('department')} />
                </div>
                <div>
                  <label className="field-label" htmlFor="a-ceil">Ceiling</label>
                  <input id="a-ceil" type="number" min="1" max="15"
                         className="control w-20 num"
                         value={adhoc.ceiling} onChange={set('ceiling')} />
                </div>
                <div>
                  <label className="field-label" htmlFor="a-clr">Clearance</label>
                  <input id="a-clr" className="control w-36" placeholder="MNPI,PHI"
                         value={adhoc.clearance} onChange={set('clearance')} />
                </div>
                <button className="btn-quiet" disabled={busy}
                        onClick={() => onRunAdhoc(adhoc)}>
                  Run profile
                </button>
              </div>
              <p className="meta mt-2">
                Not written to the database. Built at request time and run
                through the same pipeline.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
