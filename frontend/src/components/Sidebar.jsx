import { Map, BarChart3, LineChart, Activity, Droplets, MessageSquare } from 'lucide-react'

const navItems = [
  { id: 'map', label: 'Map', icon: Map },
  { id: 'timeseries', label: 'Time Series', icon: LineChart },
  { id: 'heatmap', label: 'Heatmap', icon: BarChart3 },
  { id: 'analysis', label: 'Analysis', icon: Activity },
  { id: 'chat', label: 'AI Assistant', icon: MessageSquare, badge: 'Beta' },
]

export default function Sidebar({ sites, selectedSite, onSiteSelect, activeTab, setActiveTab }) {
  return (
    <aside className="w-72 bg-white border-r border-slate-200 flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-slate-200">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-cyan-400 rounded-xl flex items-center justify-center">
            <Droplets className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-lg text-slate-800">GroundwaterGPT</h1>
            <p className="text-xs text-slate-500">Florida Aquifer Monitor</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Visualizations
        </p>
        <div className="space-y-1">
          {navItems.map(item => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all ${
                activeTab === item.id
                  ? 'bg-blue-50 text-blue-600'
                  : 'text-slate-600 hover:bg-slate-50'
              }`}
            >
              <item.icon className="w-5 h-5" />
              {item.label}
              {item.badge && (
                <span className="ml-auto text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">
                  {item.badge}
                </span>
              )}
            </button>
          ))}
        </div>
      </nav>

      {/* Site Selector */}
      <div className="p-4 border-t border-slate-200 flex-1 overflow-hidden flex flex-col">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Monitoring Sites ({sites.length})
        </p>
        <div className="space-y-2 overflow-y-auto flex-1">
          {sites.map(site => (
            <button
              key={site.id}
              onClick={() => onSiteSelect(site)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-all ${
                selectedSite?.id === site.id
                  ? 'bg-blue-50 border-2 border-blue-200'
                  : 'bg-slate-50 border-2 border-transparent hover:border-slate-200'
              }`}
            >
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${
                  site.aquifer === 'Biscayne Aquifer' ? 'bg-blue-500' : 'bg-amber-500'
                }`} />
                <span className="font-medium text-slate-700 truncate">{site.name}</span>
              </div>
              <p className="text-xs text-slate-500 mt-1 pl-4">{site.county} County</p>
            </button>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="p-4 border-t border-slate-200">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Aquifer Types
        </p>
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <div className="w-3 h-3 rounded-full bg-blue-500" />
            Biscayne Aquifer
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <div className="w-3 h-3 rounded-full bg-amber-500" />
            Floridan Aquifer
          </div>
        </div>
      </div>
    </aside>
  )
}
