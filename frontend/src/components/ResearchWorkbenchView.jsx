import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { Download, Filter, FlaskConical, Search } from 'lucide-react'
import { runResearchWorkbench } from '../api/client'

const AgentChart = lazy(() => import('./AgentChart'))
const ResearchChartsPanel = lazy(() => import('./ResearchChartsPanel'))

const DEFAULT_FILTERS = {
  county: [],
  aquifer: [],
  confined: null,
}

const DEFAULT_DATE_WINDOW = {
  preset: 'last_10y',
  start_date: '',
  end_date: '',
}

const SORTABLE_NUMERIC_KEYS = new Set([
  'record_count',
  'coverage_pct',
  'net_change_ft',
  'annual_change_ft_yr',
  'mean_level_ft',
  'std_dev_ft',
  'seasonal_amplitude_ft',
])

function toggleValue(values, nextValue) {
  return values.includes(nextValue)
    ? values.filter((value) => value !== nextValue)
    : [...values, nextValue]
}

function downloadTextFile(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function sortMetricsRows(rows, sortKey, sortDirection) {
  const sorted = [...rows].sort((left, right) => {
    const leftValue = left[sortKey]
    const rightValue = right[sortKey]

    if (SORTABLE_NUMERIC_KEYS.has(sortKey)) {
      return Number(leftValue ?? 0) - Number(rightValue ?? 0)
    }

    return String(leftValue ?? '').localeCompare(String(rightValue ?? ''))
  })

  return sortDirection === 'asc' ? sorted : sorted.reverse()
}

export default function ResearchWorkbenchView({ sites = [], selectedSite, seed, onSeedConsumed }) {
  const [searchTerm, setSearchTerm] = useState('')
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [selectedIds, setSelectedIds] = useState([])
  const [dateWindow, setDateWindow] = useState(DEFAULT_DATE_WINDOW)
  const [aggregation, setAggregation] = useState('monthly')
  const [normalization, setNormalization] = useState('raw')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sortKey, setSortKey] = useState('annual_change_ft_yr')
  const [sortDirection, setSortDirection] = useState('asc')
  const initialSiteAppliedRef = useRef(false)

  useEffect(() => {
    if (seed?.nonce) {
      setSelectedIds(seed.siteIds || [])
      setError('')
      onSeedConsumed?.()
    }
  }, [seed, onSeedConsumed])

  useEffect(() => {
    if (initialSiteAppliedRef.current || !selectedSite?.id || selectedIds.length > 0) {
      return
    }
    setSelectedIds([selectedSite.id])
    initialSiteAppliedRef.current = true
  }, [selectedIds.length, selectedSite])

  const counties = useMemo(
    () => [...new Set(sites.map((site) => site.county).filter(Boolean))].sort(),
    [sites]
  )
  const aquifers = useMemo(
    () => [...new Set(sites.map((site) => site.aquifer).filter(Boolean))].sort(),
    [sites]
  )

  const visibleSites = useMemo(() => {
    const term = searchTerm.trim().toLowerCase()
    return sites.filter((site) => {
      if (filters.county.length > 0 && !filters.county.includes(site.county)) return false
      if (filters.aquifer.length > 0 && !filters.aquifer.includes(site.aquifer)) return false
      if (filters.confined !== null && Boolean(site.confined) !== filters.confined) return false

      if (!term) return true
      const haystack = [
        site.name,
        site.id,
        site.county,
        site.aquifer,
        site.aquifer_zone,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(term)
    })
  }, [filters, searchTerm, sites])

  useEffect(() => {
    if (selectedIds.length === 0) {
      setResult(null)
      return
    }

    const timerId = window.setTimeout(async () => {
      setLoading(true)
      setError('')
      try {
        const payload = {
          site_ids: selectedIds,
          filters,
          date_window: {
            preset: dateWindow.preset,
            start_date: dateWindow.preset === 'custom' ? dateWindow.start_date : undefined,
            end_date: dateWindow.preset === 'custom' ? dateWindow.end_date : undefined,
          },
          aggregation,
          normalization,
        }
        const response = await runResearchWorkbench(payload)
        setResult(response)
      } catch (err) {
        setResult(null)
        setError(err.message || 'Failed to build workbench.')
      } finally {
        setLoading(false)
      }
    }, 250)

    return () => window.clearTimeout(timerId)
  }, [aggregation, dateWindow, filters, normalization, selectedIds])

  const sortedMetrics = useMemo(() => {
    const rows = result?.metrics_table || []
    return sortMetricsRows(rows, sortKey, sortDirection)
  }, [result, sortDirection, sortKey])

  const selectedSites = useMemo(
    () => sites.filter((site) => selectedIds.includes(site.id)),
    [selectedIds, sites]
  )

  const unequalCoverage = useMemo(() => {
    const rows = result?.metrics_table || []
    if (rows.length < 2) return false
    const coverageValues = rows.map((row) => row.coverage_pct)
    return Math.max(...coverageValues) - Math.min(...coverageValues) > 0.1
  }, [result])

  const toggleSite = (siteId) => {
    setSelectedIds((current) => {
      if (current.includes(siteId)) {
        return current.filter((id) => id !== siteId)
      }
      if (current.length >= 8) {
        return current
      }
      return [...current, siteId]
    })
  }

  const handleSort = (nextKey) => {
    if (sortKey === nextKey) {
      setSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'))
      return
    }
    setSortKey(nextKey)
    setSortDirection(SORTABLE_NUMERIC_KEYS.has(nextKey) ? 'desc' : 'asc')
  }

  const exportBaseName = useMemo(() => {
    if (selectedSites.length === 0) return 'research-workbench'
    return selectedSites
      .slice(0, 3)
      .map((site) => site.name || site.id)
      .join('-')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '')
  }, [selectedSites])

  return (
    <div className="min-h-[700px] bg-slate-50 p-5">
      <div className="grid gap-5 xl:grid-cols-[340px,minmax(0,1fr)]">
        <div className="space-y-4">
          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Workbench Controls
                </div>
                <div className="mt-1 text-sm text-slate-700">
                  Build a reproducible comparison across up to 8 monitoring wells.
                </div>
              </div>
              <div className="rounded-xl bg-slate-900 p-2 text-white">
                <FlaskConical className="h-4 w-4" />
              </div>
            </div>

            <div className="mt-4 space-y-3">
              <label className="block" htmlFor="workbench-date-window">
                <span className="text-xs font-medium text-slate-500">Date Window</span>
                <select
                  id="workbench-date-window"
                  value={dateWindow.preset}
                  onChange={(event) => setDateWindow((current) => ({
                    ...current,
                    preset: event.target.value,
                  }))}
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                >
                  <option value="last_5y">Last 5 years</option>
                  <option value="last_10y">Last 10 years</option>
                  <option value="full_record">Full record</option>
                  <option value="custom">Custom range</option>
                </select>
              </label>

              {dateWindow.preset === 'custom' && (
                <div className="grid grid-cols-2 gap-2">
                  <label className="block" htmlFor="workbench-custom-start">
                    <span className="text-xs font-medium text-slate-500">Start</span>
                    <input
                      id="workbench-custom-start"
                      type="date"
                      value={dateWindow.start_date}
                      onChange={(event) => setDateWindow((current) => ({
                        ...current,
                        start_date: event.target.value,
                      }))}
                      className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                    />
                  </label>
                  <label className="block" htmlFor="workbench-custom-end">
                    <span className="text-xs font-medium text-slate-500">End</span>
                    <input
                      id="workbench-custom-end"
                      type="date"
                      value={dateWindow.end_date}
                      onChange={(event) => setDateWindow((current) => ({
                        ...current,
                        end_date: event.target.value,
                      }))}
                      className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                    />
                  </label>
                </div>
              )}

              <div className="grid grid-cols-2 gap-2">
                <label className="block" htmlFor="workbench-aggregation">
                  <span className="text-xs font-medium text-slate-500">Aggregation</span>
                  <select
                    id="workbench-aggregation"
                    value={aggregation}
                    onChange={(event) => setAggregation(event.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                  >
                    <option value="monthly">Monthly</option>
                    <option value="quarterly">Quarterly</option>
                    <option value="annual">Annual</option>
                  </select>
                </label>
                <label className="block" htmlFor="workbench-normalization">
                  <span className="text-xs font-medium text-slate-500">Normalization</span>
                  <select
                    id="workbench-normalization"
                    value={normalization}
                    onChange={(event) => setNormalization(event.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                  >
                    <option value="raw">Raw</option>
                    <option value="delta_from_first">Delta from first</option>
                    <option value="zscore">Z-score</option>
                  </select>
                </label>
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-slate-500" />
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Site Picker
              </div>
            </div>

            <label className="mt-3 flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <Search className="h-4 w-4 text-slate-400" />
              <input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="Search wells, aquifers, counties"
                className="w-full bg-transparent text-sm outline-none"
              />
            </label>

            <div className="mt-3 space-y-3">
              <div>
                <div className="text-xs font-medium text-slate-500">County</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {counties.map((county) => (
                    <button
                      key={county}
                      type="button"
                      onClick={() => setFilters((current) => ({
                        ...current,
                        county: toggleValue(current.county, county),
                      }))}
                      className={`rounded-full border px-2.5 py-1 text-[11px] ${
                        filters.county.includes(county)
                          ? 'border-blue-200 bg-blue-50 text-blue-700'
                          : 'border-slate-200 bg-white text-slate-500'
                      }`}
                    >
                      {county}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="text-xs font-medium text-slate-500">Aquifer</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {aquifers.map((aquifer) => (
                    <button
                      key={aquifer}
                      type="button"
                      onClick={() => setFilters((current) => ({
                        ...current,
                        aquifer: toggleValue(current.aquifer, aquifer),
                      }))}
                      className={`rounded-full border px-2.5 py-1 text-[11px] ${
                        filters.aquifer.includes(aquifer)
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          : 'border-slate-200 bg-white text-slate-500'
                      }`}
                    >
                      {aquifer}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="text-xs font-medium text-slate-500">Confinement</div>
                <div className="mt-1 flex gap-1.5">
                  {[
                    { value: null, label: 'All' },
                    { value: true, label: 'Confined' },
                    { value: false, label: 'Unconfined' },
                  ].map((option) => (
                    <button
                      key={String(option.value)}
                      type="button"
                      onClick={() => setFilters((current) => ({
                        ...current,
                        confined: option.value,
                      }))}
                      className={`rounded-full border px-2.5 py-1 text-[11px] ${
                        filters.confined === option.value
                          ? 'border-violet-200 bg-violet-50 text-violet-700'
                          : 'border-slate-200 bg-white text-slate-500'
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between text-xs text-slate-500">
              <span>{selectedIds.length}/8 selected</span>
              <button
                type="button"
                onClick={() => setSelectedIds([])}
                className="font-medium text-slate-400 hover:text-slate-600"
              >
                Clear
              </button>
            </div>

            <div className="mt-3 max-h-[380px] space-y-2 overflow-y-auto pr-1">
              {visibleSites.map((site) => {
                const checked = selectedIds.includes(site.id)
                const disabled = !checked && selectedIds.length >= 8
                return (
                  <button
                    key={site.id}
                    type="button"
                    onClick={() => !disabled && toggleSite(site.id)}
                    className={`w-full rounded-xl border p-3 text-left transition-colors ${
                      checked
                        ? 'border-blue-200 bg-blue-50'
                        : disabled
                          ? 'border-slate-100 bg-slate-50 text-slate-300'
                          : 'border-slate-200 bg-white hover:bg-slate-50'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="text-sm font-medium text-slate-800">{site.name}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          {site.county} · {site.aquifer}
                        </div>
                      </div>
                      <div className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        checked ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-500'
                      }`}>
                        {checked ? 'Selected' : site.confined ? 'Confined' : 'Unconfined'}
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          </section>
        </div>

        <div className="space-y-4">
          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Research Workbench
                </div>
                <div className="mt-1 text-sm text-slate-700">
                  Interactive comparison with export-ready evidence, methods, and derived metrics.
                </div>
              </div>
              {result?.export_bundle && (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => downloadTextFile(
                      result.export_bundle.series_csv,
                      `${exportBaseName || 'research-workbench'}-series.csv`,
                      'text/csv;charset=utf-8;'
                    )}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Series CSV
                  </button>
                  <button
                    type="button"
                    onClick={() => downloadTextFile(
                      result.export_bundle.metrics_csv,
                      `${exportBaseName || 'research-workbench'}-metrics.csv`,
                      'text/csv;charset=utf-8;'
                    )}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Metrics CSV
                  </button>
                  <button
                    type="button"
                    onClick={() => downloadTextFile(
                      result.export_bundle.methods_json,
                      `${exportBaseName || 'research-workbench'}-methods.json`,
                      'application/json;charset=utf-8;'
                    )}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Methods JSON
                  </button>
                </div>
              )}
            </div>

            {loading && (
              <div className="mt-4 flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
                Updating comparative analysis…
              </div>
            )}

            {error && (
              <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            {!loading && !error && selectedIds.length === 0 && (
              <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                Select one or more monitoring wells to generate the workbench.
              </div>
            )}

            {result?.resolved_sites?.length > 0 && (
              <div className="mt-4 space-y-4">
                <div className="flex flex-wrap gap-2">
                  {result.resolved_sites.map((site) => (
                    <span
                      key={site.site_id}
                      className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600"
                    >
                      {site.name}
                    </span>
                  ))}
                </div>

                {unequalCoverage && (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                    Coverage differs across selected wells within the chosen date window. Use the metrics table and methods panel when comparing slopes or means.
                  </div>
                )}

                <Suspense fallback={<div className="h-[320px]" />}>
                  <AgentChart chartData={result.primary_chart} />
                </Suspense>
                <Suspense fallback={<div className="h-[320px]" />}>
                  <ResearchChartsPanel chartSpecs={result.chart_specs} recommendedViews={['annual-change', 'seasonal-profile']} />
                </Suspense>
              </div>
            )}
          </section>

          {result?.metrics_table?.length > 0 && (
            <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Derived Metrics
                  </div>
                  <div className="mt-1 text-sm text-slate-700">
                    Computed from filtered, non-normalized aggregated series.
                  </div>
                </div>
                <div className="text-xs text-slate-400">
                  Sorted by {sortKey} ({sortDirection})
                </div>
              </div>

              <div className="mt-4 overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                      {[
                        ['name', 'Site'],
                        ['record_count', 'Bins'],
                        ['coverage_pct', 'Coverage %'],
                        ['net_change_ft', 'Net Change'],
                        ['annual_change_ft_yr', 'Annual Change'],
                        ['mean_level_ft', 'Mean'],
                        ['std_dev_ft', 'Std Dev'],
                        ['seasonal_amplitude_ft', 'Seasonal Amp'],
                        ['trend', 'Trend'],
                      ].map(([key, label]) => (
                        <th key={key} className="px-3 py-2">
                          <button
                            type="button"
                            onClick={() => handleSort(key)}
                            className="font-semibold text-slate-500 hover:text-slate-700"
                          >
                            {label}
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sortedMetrics.map((row) => (
                      <tr key={row.site_id} className="border-b border-slate-100 text-slate-700">
                        <td className="px-3 py-3">
                          <div className="font-medium">{row.name}</div>
                          <div className="text-xs text-slate-400">
                            {row.start_date} to {row.end_date}
                          </div>
                        </td>
                        <td className="px-3 py-3">{row.record_count}</td>
                        <td className="px-3 py-3">{row.coverage_pct}</td>
                        <td className="px-3 py-3">{row.net_change_ft}</td>
                        <td className="px-3 py-3">{row.annual_change_ft_yr}</td>
                        <td className="px-3 py-3">{row.mean_level_ft}</td>
                        <td className="px-3 py-3">{row.std_dev_ft}</td>
                        <td className="px-3 py-3">{row.seasonal_amplitude_ft}</td>
                        <td className="px-3 py-3 capitalize">{row.trend}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {result?.methods && (
            <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Methods and Provenance
              </div>
              <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1.25fr),minmax(0,1fr)]">
                <div className="space-y-3">
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                    <div><span className="font-medium">Aggregation:</span> {result.methods.aggregation}</div>
                    <div><span className="font-medium">Normalization:</span> {result.methods.normalization}</div>
                    <div><span className="font-medium">Date window:</span> {result.methods.date_window.start_date} to {result.methods.date_window.end_date}</div>
                    <div><span className="font-medium">Source granularity:</span> {result.methods.source_granularity}</div>
                    <div><span className="font-medium">Trend units:</span> {result.methods.trend_units}</div>
                    <div><span className="font-medium">Chart-only normalization:</span> {String(result.methods.normalization_applies_to_chart_only)}</div>
                  </div>

                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Caveats</div>
                    <ul className="mt-2 space-y-1 text-sm text-slate-600">
                      {(result.methods.caveats || []).map((caveat, index) => (
                        <li key={index}>{caveat}</li>
                      ))}
                    </ul>
                  </div>
                </div>

                <div className="space-y-3">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Metric Definitions</div>
                    <div className="mt-2 space-y-2 text-sm text-slate-600">
                      {Object.entries(result.methods.metric_definitions || {}).map(([key, value]) => (
                        <div key={key}>
                          <div className="font-medium text-slate-700">{key}</div>
                          <div>{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">USGS Sources</div>
                    <ul className="mt-2 space-y-1 text-sm">
                      {(result.citations || []).map((citation) => (
                        <li key={citation.site_id}>
                          <a
                            href={citation.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline"
                          >
                            {citation.name}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
