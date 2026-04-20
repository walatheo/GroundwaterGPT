import {
  Map,
  BarChart3,
  LineChart,
  Activity,
  Droplets,
  MessageSquare,
  Waves,
  ArrowRight,
  FlaskConical,
} from 'lucide-react'

const navItems = [
  { id: 'map', label: 'Map', icon: Map },
  { id: 'timeseries', label: 'Time Series', icon: LineChart },
  { id: 'heatmap', label: 'Heatmap', icon: BarChart3 },
  { id: 'analysis', label: 'Analysis', icon: Activity },
  { id: 'chat', label: 'AI Assistant', icon: MessageSquare, badge: 'Beta' },
  { id: 'research_workbench', label: 'Research Workbench', icon: FlaskConical },
]

export default function Sidebar({
  sites,
  selectedSite,
  onSiteSelect,
  activeTab,
  setActiveTab,
  networkSummary,
}) {
  return (
    <aside className="flex w-full flex-col border-b border-slate-200/70 bg-slate-950 text-slate-100 shadow-[18px_0_50px_rgba(15,23,42,0.08)] lg:min-h-screen lg:w-[320px] lg:border-b-0 lg:border-r">
      <div className="border-b border-white/10 bg-[radial-gradient(circle_at_top,_rgba(45,212,191,0.28),_transparent_45%),linear-gradient(180deg,_rgba(15,23,42,0.92),_rgba(15,23,42,0.98))] p-6">
        <div className="flex items-start gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/10 ring-1 ring-white/15">
            <Droplets className="h-6 w-6 text-teal-200" />
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-[0.3em] text-teal-200/80">EAGLE</p>
            <h1 className="mt-1 text-lg font-semibold text-white">Florida Aquifer Analysis</h1>
            <p className="mt-1 text-sm leading-relaxed text-slate-300">
              Monitoring, interpretation, and groundwater research workflows in one place.
            </p>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400">Sites</p>
            <p className="mt-2 text-2xl font-semibold text-white">{networkSummary?.totalSites || 0}</p>
            <p className="mt-1 text-xs text-slate-400">
              {networkSummary?.countyCount || 0} counties monitored
            </p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400">Aquifers</p>
            <p className="mt-2 text-2xl font-semibold text-white">{networkSummary?.aquiferCount || 0}</p>
            <p className="mt-1 text-xs text-slate-400">
              {networkSummary?.totalRecords?.toLocaleString() || '0'} records indexed
            </p>
          </div>
        </div>

        <div className="mt-5 rounded-2xl border border-teal-300/20 bg-teal-400/10 p-4">
          <div className="flex items-center gap-2 text-teal-100">
            <Waves className="h-4 w-4" />
            <p className="text-sm font-medium">Active station focus</p>
          </div>
          <p className="mt-2 text-base font-semibold text-white">
            {selectedSite?.name || 'Select a monitoring well'}
          </p>
          <p className="mt-1 text-sm text-teal-50/80">
            {selectedSite
              ? `${selectedSite.aquifer} • ${selectedSite.county} County`
              : 'Choose a site to anchor charts, analysis, and chat context.'}
          </p>
        </div>
      </div>

      <nav className="p-5">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">
          Workspace
        </p>
        <div className="space-y-1">
          {navItems.map(item => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`group flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left text-sm font-medium transition-all ${
                activeTab === item.id
                  ? 'bg-white text-slate-900 shadow-[0_10px_25px_rgba(15,23,42,0.16)]'
                  : 'text-slate-300 hover:bg-white/5 hover:text-white'
              }`}
            >
              <span className={`flex h-10 w-10 items-center justify-center rounded-xl ${
                activeTab === item.id ? 'bg-teal-50 text-teal-700' : 'bg-white/5 text-slate-400 group-hover:text-teal-200'
              }`}>
                <item.icon className="h-5 w-5" />
              </span>
              <span className="flex-1">
                <span className="block">{item.label}</span>
                <span className={`block text-xs ${
                  activeTab === item.id ? 'text-slate-500' : 'text-slate-500 group-hover:text-slate-400'
                }`}>
                  {item.id === 'chat' && 'Fast groundwater Q&A and deep research'}
                  {item.id === 'map' && 'Spatial view of the monitoring network'}
                  {item.id === 'timeseries' && 'Historical water-level trajectories'}
                  {item.id === 'heatmap' && 'Seasonal intensity and recurrence'}
                  {item.id === 'analysis' && 'Derived trends, ranges, and summaries'}
                  {item.id === 'research_workbench' && 'Side-by-side well comparison'}
                </span>
              </span>
              {item.badge && (
                <span className={`ml-auto rounded-full px-2 py-0.5 text-[11px] ${
                  activeTab === item.id
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-amber-400/10 text-amber-200'
                }`}>
                  {item.badge}
                </span>
              )}
              {!item.badge && activeTab === item.id && <ArrowRight className="h-4 w-4 text-slate-400" />}
            </button>
          ))}
        </div>
      </nav>

      <div className="border-t border-white/10 px-5 py-4 lg:flex-1 lg:overflow-hidden">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">
            Monitoring Sites
          </p>
          <span className="rounded-full bg-white/5 px-2 py-1 text-[11px] text-slate-400">
            {sites.length} total
          </span>
        </div>
        <div className="mb-3 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-400">
          Pick a site to sync the chart tabs and use it as your working groundwater reference point.
        </div>
        <div className="flex flex-col lg:h-full lg:overflow-hidden">
          <div className="space-y-2 lg:overflow-y-auto lg:pr-1">
            {sites.map(site => (
              <button
                key={site.id}
                onClick={() => onSiteSelect(site)}
                className={`w-full rounded-2xl border px-3 py-3 text-left transition-all ${
                  selectedSite?.id === site.id
                    ? 'border-teal-300/60 bg-teal-300/12 shadow-[0_10px_30px_rgba(20,184,166,0.14)]'
                    : 'border-white/8 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className={`mt-1 h-2.5 w-2.5 rounded-full ${
                    site.aquifer === 'Biscayne Aquifer' ? 'bg-sky-400' : 'bg-amber-300'
                  }`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium text-white">{site.name}</span>
                      <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-400">
                        {site.county}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-xs text-slate-400">{site.aquifer}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                      <span>{site.recordCount?.toLocaleString() || 0} records</span>
                      <span>•</span>
                      <span>{site.well_depth_ft ?? site.depth ?? 'N/A'} ft depth</span>
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="border-t border-white/10 p-5">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">
          Network Legend
        </p>
        <div className="space-y-2 rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="flex items-center gap-2 text-sm text-slate-300">
            <div className="h-3 w-3 rounded-full bg-sky-400" />
            Biscayne Aquifer
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-300">
            <div className="h-3 w-3 rounded-full bg-amber-300" />
            Floridan and inland systems
          </div>
          <div className="rounded-xl bg-slate-900/60 p-3 text-xs leading-relaxed text-slate-400">
            Use the map for spatial orientation, then switch to analysis or chat to interpret long-term behavior.
          </div>
        </div>
      </div>
    </aside>
  )
}
