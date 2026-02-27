import { useEffect, useMemo, useState } from 'react'
import {
  createExperimentPlan,
  draftResearchPaper,
  getExperimentPlan,
  listExperimentPlans,
  logExperimentRun,
} from '../api/client'

const PLAN_STATUSES = [
  { value: '', label: 'All statuses' },
  { value: 'planned', label: 'Planned' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'completed', label: 'Completed' },
  { value: 'drafted', label: 'Drafted' },
]

const DEFAULT_PLAN_FORM = {
  title: '',
  research_question: '',
  hypothesis: '',
  methodology: '',
  datasets: 'USGS Florida groundwater monitoring records',
  metrics: 'f1, reproducibility_score',
  baselines: 'manual pipeline',
  notes: '',
}

const DEFAULT_RUN_FORM = {
  run_name: '',
  config_json: '{\n  "model": "ridge",\n  "seed": 42\n}',
  metrics_json: '{\n  "f1": 0.82,\n  "reproducibility_score": 0.74\n}',
  findings: '',
  random_seed: '42',
  code_commit: '',
  environment: 'local-dev',
  executor: 'frontend_ui',
  dependency_lock: 'requirements.txt',
  artifact_path: '',
  artifact_sha256: '',
  artifact_kind: 'figure',
  artifact_description: '',
}

const DEFAULT_DRAFT_FORM = {
  target_venue: 'arXiv',
  include_methods_detail: true,
  citations: 'USGS Water Data for the Nation',
}

function splitListInput(raw) {
  return raw
    .split(',')
    .map(item => item.trim())
    .filter(Boolean)
}

function parseJsonInput(raw, label) {
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error(`${label} must be a JSON object.`)
    }
    return parsed
  } catch (error) {
    throw new Error(`${label} is invalid JSON: ${error.message}`)
  }
}

function formatDateTime(value) {
  if (!value) return 'N/A'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

export default function ResearchWorkflowView() {
  const [plans, setPlans] = useState([])
  const [statusFilter, setStatusFilter] = useState('')
  const [selectedPlanId, setSelectedPlanId] = useState('')
  const [selectedPlan, setSelectedPlan] = useState(null)

  const [planForm, setPlanForm] = useState(DEFAULT_PLAN_FORM)
  const [runForm, setRunForm] = useState(DEFAULT_RUN_FORM)
  const [draftForm, setDraftForm] = useState(DEFAULT_DRAFT_FORM)

  const [draftResult, setDraftResult] = useState(null)
  const [loadingPlans, setLoadingPlans] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const selectedPlanSummary = useMemo(() => {
    if (!selectedPlan) return null
    return {
      status: selectedPlan.status || 'unknown',
      runCount: (selectedPlan.runs || []).length,
      updatedAt: selectedPlan.updated_at,
      createdAt: selectedPlan.created_at,
    }
  }, [selectedPlan])

  async function loadPlans(preferredPlanId = '') {
    try {
      setLoadingPlans(true)
      const response = await listExperimentPlans({ status: statusFilter || undefined, limit: 25 })
      const nextPlans = response.plans || []
      setPlans(nextPlans)

      const fallback = nextPlans[0]?.plan_id || ''
      const nextSelectedId = preferredPlanId || selectedPlanId || fallback
      if (nextSelectedId) {
        setSelectedPlanId(nextSelectedId)
        await loadPlan(nextSelectedId)
      } else {
        setSelectedPlanId('')
        setSelectedPlan(null)
      }
    } catch (err) {
      setError(err.message || 'Failed to load plans.')
    } finally {
      setLoadingPlans(false)
    }
  }

  async function loadPlan(planId) {
    if (!planId) return
    try {
      const response = await getExperimentPlan(planId)
      setSelectedPlan(response.plan || null)
    } catch (err) {
      setError(err.message || `Failed to load plan ${planId}.`)
    }
  }

  useEffect(() => {
    loadPlans()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter])

  const handlePlanInput = (event) => {
    const { name, value } = event.target
    setPlanForm(prev => ({ ...prev, [name]: value }))
  }

  const handleRunInput = (event) => {
    const { name, value } = event.target
    setRunForm(prev => ({ ...prev, [name]: value }))
  }

  const handleDraftInput = (event) => {
    const { name, value, type, checked } = event.target
    setDraftForm(prev => ({ ...prev, [name]: type === 'checkbox' ? checked : value }))
  }

  const submitPlan = async (event) => {
    event.preventDefault()
    setError('')
    setSuccess('')
    setSubmitting(true)

    try {
      const payload = {
        title: planForm.title,
        research_question: planForm.research_question,
        hypothesis: planForm.hypothesis,
        methodology: planForm.methodology,
        datasets: splitListInput(planForm.datasets),
        metrics: splitListInput(planForm.metrics),
        baselines: splitListInput(planForm.baselines),
        notes: planForm.notes,
      }

      const response = await createExperimentPlan(payload)
      const createdId = response.plan?.plan_id
      setSuccess(`Plan created: ${createdId}`)
      setPlanForm(DEFAULT_PLAN_FORM)
      await loadPlans(createdId)
    } catch (err) {
      setError(err.message || 'Failed to create plan.')
    } finally {
      setSubmitting(false)
    }
  }

  const submitRun = async (event) => {
    event.preventDefault()
    if (!selectedPlanId) {
      setError('Select a plan before logging a run.')
      return
    }

    setError('')
    setSuccess('')
    setSubmitting(true)

    try {
      const config = parseJsonInput(runForm.config_json, 'Config JSON')
      const metrics = parseJsonInput(runForm.metrics_json, 'Metrics JSON')

      const artifactPath = runForm.artifact_path.trim()
      const artifacts = artifactPath
        ? [
            {
              path: artifactPath,
              sha256: runForm.artifact_sha256.trim(),
              kind: runForm.artifact_kind.trim() || 'artifact',
              description: runForm.artifact_description.trim(),
            },
          ]
        : []

      const payload = {
        run_name: runForm.run_name,
        config,
        metrics,
        findings: runForm.findings,
        reproducibility: {
          random_seed: Number.parseInt(runForm.random_seed, 10),
          code_commit: runForm.code_commit.trim(),
          environment: runForm.environment.trim(),
          executor: runForm.executor.trim(),
          dependency_lock: runForm.dependency_lock.trim(),
        },
        artifacts,
      }

      if (Number.isNaN(payload.reproducibility.random_seed)) {
        throw new Error('Random seed must be an integer.')
      }

      await logExperimentRun(selectedPlanId, payload)
      setSuccess(`Run logged for ${selectedPlanId}`)
      setRunForm(prev => ({ ...DEFAULT_RUN_FORM, code_commit: prev.code_commit }))
      await loadPlan(selectedPlanId)
      await loadPlans(selectedPlanId)
    } catch (err) {
      setError(err.message || 'Failed to log run.')
    } finally {
      setSubmitting(false)
    }
  }

  const submitDraft = async (event) => {
    event.preventDefault()
    if (!selectedPlanId) {
      setError('Select a plan before drafting a manuscript.')
      return
    }

    setError('')
    setSuccess('')
    setSubmitting(true)

    try {
      const payload = {
        target_venue: draftForm.target_venue,
        include_methods_detail: draftForm.include_methods_detail,
        citations: splitListInput(draftForm.citations),
      }

      const response = await draftResearchPaper(selectedPlanId, payload)
      setDraftResult(response)
      setSuccess(`Draft generated for ${selectedPlanId}`)
      await loadPlan(selectedPlanId)
      await loadPlans(selectedPlanId)
    } catch (err) {
      setError(err.message || 'Failed to draft manuscript.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-6 space-y-6">
      <section className="bg-slate-900 text-slate-100 rounded-xl p-5">
        <h3 className="text-lg font-semibold">Research Workflow Lab</h3>
        <p className="text-sm text-slate-300 mt-1">
          Create experiment plans, log reproducible runs, and generate manuscript drafts with
          provenance.
        </p>
      </section>

      {(error || success) && (
        <section className="grid grid-cols-1 gap-2">
          {error && <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-3 text-sm">{error}</div>}
          {success && <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-lg p-3 text-sm">{success}</div>}
        </section>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <section className="xl:col-span-1 bg-white border border-slate-200 rounded-xl p-4 space-y-4">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold text-slate-800">Experiment Plans</h4>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="text-xs border border-slate-300 rounded-md px-2 py-1"
            >
              {PLAN_STATUSES.map(option => (
                <option key={option.value || 'all'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="max-h-72 overflow-y-auto space-y-2 pr-1">
            {loadingPlans && <p className="text-sm text-slate-500">Loading plans...</p>}
            {!loadingPlans && plans.length === 0 && (
              <p className="text-sm text-slate-500">No plans found for this filter.</p>
            )}
            {plans.map(plan => (
              <button
                key={plan.plan_id}
                onClick={() => {
                  setSelectedPlanId(plan.plan_id)
                  loadPlan(plan.plan_id)
                }}
                className={`w-full text-left rounded-lg border px-3 py-2 transition-colors ${
                  selectedPlanId === plan.plan_id
                    ? 'border-blue-300 bg-blue-50'
                    : 'border-slate-200 hover:bg-slate-50'
                }`}
              >
                <p className="text-sm font-medium text-slate-800 truncate">{plan.title}</p>
                <p className="text-xs text-slate-500 mt-1">
                  {plan.status} • runs: {plan.run_count}
                </p>
              </button>
            ))}
          </div>

          <form className="space-y-3 border-t border-slate-200 pt-4" onSubmit={submitPlan}>
            <h5 className="text-sm font-semibold text-slate-700">Create Plan</h5>
            <input
              name="title"
              value={planForm.title}
              onChange={handlePlanInput}
              placeholder="Plan title"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
              required
            />
            <textarea
              name="research_question"
              value={planForm.research_question}
              onChange={handlePlanInput}
              placeholder="Research question"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm h-16"
              required
            />
            <textarea
              name="hypothesis"
              value={planForm.hypothesis}
              onChange={handlePlanInput}
              placeholder="Hypothesis"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm h-16"
              required
            />
            <textarea
              name="methodology"
              value={planForm.methodology}
              onChange={handlePlanInput}
              placeholder="Methodology"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm h-20"
              required
            />
            <input
              name="datasets"
              value={planForm.datasets}
              onChange={handlePlanInput}
              placeholder="Datasets (comma-separated)"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
            <input
              name="metrics"
              value={planForm.metrics}
              onChange={handlePlanInput}
              placeholder="Metrics (comma-separated)"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
            <input
              name="baselines"
              value={planForm.baselines}
              onChange={handlePlanInput}
              placeholder="Baselines (comma-separated)"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
            <textarea
              name="notes"
              value={planForm.notes}
              onChange={handlePlanInput}
              placeholder="Notes"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm h-16"
            />
            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-slate-900 text-white rounded-lg px-4 py-2 text-sm hover:bg-slate-700 disabled:opacity-50"
            >
              Create Experiment Plan
            </button>
          </form>
        </section>

        <section className="xl:col-span-2 space-y-4">
          <div className="bg-white border border-slate-200 rounded-xl p-4">
            <h4 className="font-semibold text-slate-800">Selected Plan</h4>
            {!selectedPlan && (
              <p className="text-sm text-slate-500 mt-2">Select or create a plan to continue.</p>
            )}
            {selectedPlan && (
              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <div className="bg-slate-50 rounded-lg p-3">
                  <p className="text-slate-500">Title</p>
                  <p className="font-medium text-slate-800">{selectedPlan.title}</p>
                </div>
                <div className="bg-slate-50 rounded-lg p-3">
                  <p className="text-slate-500">Status</p>
                  <p className="font-medium text-slate-800">{selectedPlanSummary?.status}</p>
                </div>
                <div className="bg-slate-50 rounded-lg p-3">
                  <p className="text-slate-500">Created</p>
                  <p className="font-medium text-slate-800">{formatDateTime(selectedPlanSummary?.createdAt)}</p>
                </div>
                <div className="bg-slate-50 rounded-lg p-3">
                  <p className="text-slate-500">Updated</p>
                  <p className="font-medium text-slate-800">{formatDateTime(selectedPlanSummary?.updatedAt)}</p>
                </div>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <form className="bg-white border border-slate-200 rounded-xl p-4 space-y-3" onSubmit={submitRun}>
              <h4 className="font-semibold text-slate-800">Log Experiment Run</h4>
              <input
                name="run_name"
                value={runForm.run_name}
                onChange={handleRunInput}
                placeholder="run_name"
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
                required
              />
              <textarea
                name="config_json"
                value={runForm.config_json}
                onChange={handleRunInput}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-xs font-mono h-28"
              />
              <textarea
                name="metrics_json"
                value={runForm.metrics_json}
                onChange={handleRunInput}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-xs font-mono h-24"
              />
              <textarea
                name="findings"
                value={runForm.findings}
                onChange={handleRunInput}
                placeholder="findings"
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm h-16"
              />

              <div className="grid grid-cols-2 gap-2">
                <input
                  name="random_seed"
                  value={runForm.random_seed}
                  onChange={handleRunInput}
                  placeholder="random_seed"
                  className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
                  required
                />
                <input
                  name="code_commit"
                  value={runForm.code_commit}
                  onChange={handleRunInput}
                  placeholder="code_commit (7+ chars)"
                  className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
                  required
                />
                <input
                  name="environment"
                  value={runForm.environment}
                  onChange={handleRunInput}
                  placeholder="environment"
                  className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
                  required
                />
                <input
                  name="executor"
                  value={runForm.executor}
                  onChange={handleRunInput}
                  placeholder="executor"
                  className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
                  required
                />
              </div>

              <input
                name="dependency_lock"
                value={runForm.dependency_lock}
                onChange={handleRunInput}
                placeholder="dependency lock reference"
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
              />

              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <input
                  name="artifact_path"
                  value={runForm.artifact_path}
                  onChange={handleRunInput}
                  placeholder="artifact path (optional)"
                  className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
                />
                <input
                  name="artifact_sha256"
                  value={runForm.artifact_sha256}
                  onChange={handleRunInput}
                  placeholder="sha256 (optional)"
                  className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
                />
                <input
                  name="artifact_kind"
                  value={runForm.artifact_kind}
                  onChange={handleRunInput}
                  placeholder="artifact kind"
                  className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
                />
                <input
                  name="artifact_description"
                  value={runForm.artifact_description}
                  onChange={handleRunInput}
                  placeholder="artifact description"
                  className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
                />
              </div>

              <button
                type="submit"
                disabled={submitting || !selectedPlanId}
                className="w-full bg-blue-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-blue-700 disabled:opacity-50"
              >
                Log Run (Reproducible)
              </button>
            </form>

            <form className="bg-white border border-slate-200 rounded-xl p-4 space-y-3" onSubmit={submitDraft}>
              <h4 className="font-semibold text-slate-800">Draft Manuscript</h4>
              <input
                name="target_venue"
                value={draftForm.target_venue}
                onChange={handleDraftInput}
                placeholder="Target venue"
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
              />
              <textarea
                name="citations"
                value={draftForm.citations}
                onChange={handleDraftInput}
                placeholder="Citations (comma-separated)"
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm h-20"
              />
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  name="include_methods_detail"
                  checked={draftForm.include_methods_detail}
                  onChange={handleDraftInput}
                />
                Include detailed methods section
              </label>
              <button
                type="submit"
                disabled={submitting || !selectedPlanId}
                className="w-full bg-indigo-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-indigo-700 disabled:opacity-50"
              >
                Generate Draft + Provenance
              </button>

              {draftResult && (
                <div className="mt-3 border border-slate-200 rounded-lg">
                  <div className="bg-slate-50 border-b border-slate-200 px-3 py-2 text-xs text-slate-600">
                    <p>Draft: {draftResult.draft?.path}</p>
                    <p>Provenance: {draftResult.draft?.provenance_path}</p>
                  </div>
                  <pre className="p-3 text-xs text-slate-700 max-h-80 overflow-auto whitespace-pre-wrap">
                    {draftResult.draft?.markdown}
                  </pre>
                </div>
              )}
            </form>
          </div>
        </section>
      </div>
    </div>
  )
}
