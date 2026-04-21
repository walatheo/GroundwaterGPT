import MapView from './MapView'
import TimeSeriesChart from './TimeSeriesChart'
import HeatmapChart from './HeatmapChart'
import AnalysisView from './AnalysisView'
import ChatView from './ChatView'
import ResearchWorkbenchView from './ResearchWorkbenchView'
import StatsCard from './StatsCard'
import { TrendingUp, TrendingDown, Minus, Droplet, Database, Activity } from 'lucide-react'

export default function Dashboard({
  site,
  data,
  heatmapData,
  stats,
  sites,
  loading,
  error,
  activeTab,
  setActiveTab,
  setSelectedSite,
  networkSummary,
  workbenchSeed,
  onOpenWorkbench,
  onWorkbenchSeedConsumed,
}) {
  const getTrendIcon = (trend) => {
    if (trend > 0.1) return <TrendingUp className="w-4 h-4 text-red-500" />
    if (trend < -0.1) return <TrendingDown className="w-4 h-4 text-green-500" />
    return <Minus className="w-4 h-4 text-slate-400" />
  }

  const getTrendLabel = (change) => {
    if (change > 0.1) return 'Rising'
    if (change < -0.1) return 'Falling'
    return 'Stable'
  }

  const getTrendColor = (change) => {
    if (change > 0.1) return 'red'
    if (change < -0.1) return 'green'
    return 'slate'
  }

  const tabCopy = {
    map: {
      eyebrow: 'Monitoring Network',
      title: 'Groundwater monitoring across Florida aquifer systems',
      description: 'Explore monitoring wells spatially, then move directly into time-series, analysis, and research workflows.',
    },
    timeseries: {
      eyebrow: 'Hydrograph',
      title: 'Historical water-level trajectories',
      description: 'Review long-term movement, reversals, and seasonal structure for the selected well.',
    },
    heatmap: {
      eyebrow: 'Seasonality',
      title: 'Recurring wet-season and dry-season behavior',
      description: 'Use the heatmap to spot recurring depth patterns, timing shifts, and unusual years.',
    },
    analysis: {
      eyebrow: 'Diagnostics',
      title: 'Statistical groundwater analysis',
      description: 'Summaries, seasonal signals, and yearly aggregation for the active monitoring site.',
    },
    chat: {
      eyebrow: 'Groundwater Assistant',
      title: 'Ask groundwater questions in plain language',
      description: 'Quick chat handles targeted groundwater prompts, and research mode adds deeper synthesis with citations.',
    },
    research_workbench: {
      eyebrow: 'Research Workbench',
      title: 'Side-by-side well comparison',
      description: 'Pick wells, align a date window, and compare trends, ranges, and recent records next to each other.',
    },
  }

  const activeCopy = tabCopy[activeTab] || tabCopy.map
  const siteEyebrow = site ? `${site.county} County • ${site.aquifer}` : 'Florida Groundwater'
  const networkHighlights = [
    { label: 'Monitoring sites', value: networkSummary?.totalSites || 0 },
    { label: 'Counties covered', value: networkSummary?.countyCount || 0 },
    { label: 'Aquifer systems', value: networkSummary?.aquiferCount || 0 },
    { label: 'Records indexed', value: (networkSummary?.totalRecords || 0).toLocaleString() },
  ]

  if (activeTab === 'chat') {
    return (
      <div className="h-[calc(100dvh-76px)] min-h-[640px] bg-white/90 lg:h-screen lg:min-h-0">
        <ChatView selectedSite={site} onOpenWorkbench={onOpenWorkbench} fullScreen />
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6">
      <header className="mb-6 overflow-hidden rounded-[30px] border border-white/70 bg-[radial-gradient(circle_at_top_left,_rgba(20,184,166,0.18),_transparent_28%),linear-gradient(135deg,_rgba(255,255,255,0.92),_rgba(241,245,249,0.86))] p-6 shadow-[0_30px_80px_rgba(15,23,42,0.08)] backdrop-blur">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-teal-700">
              {activeCopy.eyebrow}
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900 md:text-4xl">
              {activeCopy.title}
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600 md:text-base">
              {activeCopy.description}
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <span className="rounded-full bg-white/80 px-3 py-1.5 text-xs font-medium text-slate-600 ring-1 ring-slate-200/80">
                {siteEyebrow}
              </span>
              {site && (
                <span className="rounded-full bg-teal-50 px-3 py-1.5 text-xs font-medium text-teal-700 ring-1 ring-teal-200">
                  Selected well: {site.name}
                </span>
              )}
              <span className="rounded-full bg-slate-900 px-3 py-1.5 text-xs font-medium text-white">
                USGS-backed records
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:min-w-[520px]">
            {networkHighlights.map(item => (
              <div key={item.label} className="rounded-2xl border border-white/70 bg-white/80 p-4 shadow-sm">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-400">{item.label}</p>
                <p className="mt-2 text-2xl font-semibold text-slate-900">{item.value}</p>
              </div>
            ))}
          </div>
        </div>
      </header>

      {/* Loading indicator */}
      {loading && (
        <div className="mb-6 flex h-20 items-center justify-center rounded-2xl border border-white/80 bg-white/80 shadow-sm">
          <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-teal-600" />
          <span className="ml-3 text-slate-500">Loading data…</span>
        </div>
      )}

      {/* Stats Cards (shown when site selected) */}
      {site && stats && !loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <StatsCard
            title="Min Level"
            value={`${stats.min} ft`}
            subtitle="Shallowest recorded"
            icon={<Droplet className="w-5 h-5" />}
            color="blue"
          />
          <StatsCard
            title="Mean Level"
            value={`${stats.mean} ft`}
            subtitle={`Range: ${stats.min} - ${stats.max} ft`}
            icon={<Activity className="w-5 h-5" />}
            color="cyan"
          />
          <StatsCard
            title="Trend"
            value={getTrendLabel(stats.annualChange)}
            subtitle={`${stats.annualChange > 0 ? '+' : ''}${stats.annualChange} ft/year`}
            icon={getTrendIcon(stats.annualChange)}
            color={getTrendColor(stats.annualChange)}
          />
          <StatsCard
            title="Records"
            value={stats.count?.toLocaleString() || '0'}
            subtitle="Data points"
            icon={<Database className="w-5 h-5" />}
            color="purple"
          />
        </div>
      )}

      {/* Site Info Banner */}
      {site && (
        <div className="mb-6 rounded-[26px] border border-slate-200/70 bg-[linear-gradient(135deg,_#0f766e,_#155e75)] p-5 text-white shadow-[0_24px_70px_rgba(14,116,144,0.22)]">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-teal-100/80">Selected Monitoring Site</p>
              <h3 className="mt-2 text-xl font-semibold">{site.name}</h3>
              <p className="mt-1 text-sm text-teal-50/85">
                {site.aquifer} • {site.county} County
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm text-teal-50/90 md:min-w-[360px]">
              <div className="rounded-2xl bg-white/10 p-3">
                <p className="text-xs uppercase tracking-[0.18em] text-teal-100/70">Coordinates</p>
                <p className="mt-2 font-mono text-sm">{site.lat?.toFixed(4)}°N, {Math.abs(site.lng || 0).toFixed(4)}°W</p>
              </div>
              <div className="rounded-2xl bg-white/10 p-3">
                <p className="text-xs uppercase tracking-[0.18em] text-teal-100/70">Well depth</p>
                <p className="mt-2 text-sm font-semibold">{site.well_depth_ft ?? site.depth ?? 'N/A'} ft</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="overflow-hidden rounded-[28px] border border-white/80 bg-white/90 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur">
        {activeTab === 'map' && (
          <MapView sites={sites} selectedSite={site} setSelectedSite={setSelectedSite} setActiveTab={setActiveTab} />
        )}
        {activeTab === 'timeseries' && (
          <TimeSeriesChart data={data} site={site} />
        )}
        {activeTab === 'heatmap' && (
          <HeatmapChart data={data} heatmapData={heatmapData} site={site} />
        )}
        {activeTab === 'analysis' && (
          <AnalysisView data={data} site={site} stats={stats} />
        )}
        {activeTab === 'research_workbench' && (
          <ResearchWorkbenchView
            sites={sites}
            selectedSite={site}
            seed={workbenchSeed}
            onSeedConsumed={onWorkbenchSeedConsumed}
          />
        )}
      </div>

      {/* No site selected message */}
      {!site && activeTab !== 'map' && activeTab !== 'research_workbench' && (
        <div className="flex h-96 items-center justify-center text-slate-400">
          <div className="text-center">
            <Droplet className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p className="text-lg font-medium">Select a monitoring site</p>
            <p className="text-sm">Choose a site from the sidebar to view data</p>
          </div>
        </div>
      )}
    </div>
  )
}
