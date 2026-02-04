import MapView from './MapView'
import TimeSeriesChart from './TimeSeriesChart'
import HeatmapChart from './HeatmapChart'
import AnalysisView from './AnalysisView'
import ChatView from './ChatView'
import StatsCard from './StatsCard'
import { TrendingUp, TrendingDown, Minus, Droplet, Calendar, Database, Activity } from 'lucide-react'

export default function Dashboard({ site, data, heatmapData, stats, sites, loading, error, activeTab, setSelectedSite }) {
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

  return (
    <div className="p-6">
      {/* Header */}
      <header className="mb-6">
        <h2 className="text-2xl font-bold text-slate-800">
          {activeTab === 'map' && '🗺️ Geographic Map'}
          {activeTab === 'timeseries' && '📈 Time Series Analysis'}
          {activeTab === 'heatmap' && '🌡️ Water Level Heatmap'}
          {activeTab === 'analysis' && '📊 Statistical Analysis'}
          {activeTab === 'chat' && '🤖 AI Assistant'}
        </h2>
        <p className="text-slate-500 mt-1">
          {activeTab === 'map' && 'Interactive map of Florida groundwater monitoring sites'}
          {activeTab === 'timeseries' && 'Historical water level data with trends'}
          {activeTab === 'heatmap' && 'Temporal patterns by month and year'}
          {activeTab === 'analysis' && 'Detailed statistics and distributions'}
          {activeTab === 'chat' && 'Ask questions about groundwater, irrigation, and crops'}
        </p>
      </header>

      {/* Loading indicator */}
      {loading && (
        <div className="flex items-center justify-center h-20 mb-6">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
          <span className="ml-3 text-slate-500">Loading data...</span>
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
        <div className="bg-gradient-to-r from-blue-500 to-cyan-500 rounded-xl p-4 mb-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-bold text-lg">{site.name}</h3>
              <p className="text-blue-100 text-sm">
                {site.aquifer} • {site.county} County
              </p>
            </div>
            <div className="text-right">
              <p className="text-sm text-blue-100">Coordinates</p>
              <p className="font-mono text-sm">{site.lat?.toFixed(4)}°N, {Math.abs(site.lng || 0).toFixed(4)}°W</p>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        {activeTab === 'map' && (
          <MapView sites={sites} selectedSite={site} setSelectedSite={setSelectedSite} />
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
        {activeTab === 'chat' && (
          <ChatView selectedSite={site} />
        )}
      </div>

      {/* No site selected message */}
      {!site && activeTab !== 'map' && (
        <div className="flex items-center justify-center h-96 text-slate-400">
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
