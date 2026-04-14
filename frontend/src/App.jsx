import { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar'
import Dashboard from './components/Dashboard'
import { fetchSites, fetchSiteData, fetchHeatmapData } from './api/client'

function App() {
  const [sites, setSites] = useState([])
  const [selectedSite, setSelectedSite] = useState(null)
  const [siteData, setSiteData] = useState(null)
  const [heatmapData, setHeatmapData] = useState(null)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('map')
  const [workbenchSeed, setWorkbenchSeed] = useState(null)

  // Fetch sites on mount
  useEffect(() => {
    async function loadSites() {
      try {
        setLoading(true)
        const sitesData = await fetchSites()
        setSites(sitesData)
        if (sitesData.length > 0) {
          setSelectedSite(sitesData[0])
        }
      } catch (err) {
        console.error('Failed to load sites:', err)
        setError('Failed to load monitoring sites. Make sure the API server is running.')
      } finally {
        setLoading(false)
      }
    }
    loadSites()
  }, [])

  // Fetch data when site changes
  useEffect(() => {
    async function loadSiteData() {
      if (!selectedSite) return

      try {
        setLoading(true)
        setError(null)

        // Fetch both time series and heatmap data
        const [timeSeriesResponse, heatmapResponse] = await Promise.all([
          fetchSiteData(selectedSite.id),
          fetchHeatmapData(selectedSite.id)
        ])

        setSiteData(timeSeriesResponse.data)
        setStats(timeSeriesResponse.stats)
        setHeatmapData(heatmapResponse)
      } catch (err) {
        console.error('Failed to load site data:', err)
        setError(`Failed to load data for ${selectedSite.name}`)
      } finally {
        setLoading(false)
      }
    }
    loadSiteData()
  }, [selectedSite])

  const handleSiteSelect = (site) => {
    setSelectedSite(site)
  }

  const handleOpenWorkbench = ({ siteIds = [], sourceLabel = '' }) => {
    setWorkbenchSeed({
      nonce: Date.now(),
      siteIds,
      sourceLabel,
    })
    setActiveTab('research_workbench')
  }

  const handleWorkbenchSeedConsumed = () => {
    setWorkbenchSeed(null)
  }

  const countyCount = new Set(sites.map(site => site.county).filter(Boolean)).size
  const aquiferCount = new Set(sites.map(site => site.aquifer).filter(Boolean)).size
  const totalRecords = sites.reduce((sum, site) => sum + (site.recordCount || 0), 0)
  const networkSummary = {
    totalSites: sites.length,
    countyCount,
    aquiferCount,
    totalRecords,
  }

  if (loading && sites.length === 0) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_rgba(20,184,166,0.18),_transparent_38%),linear-gradient(180deg,_#f6fbfb_0%,_#edf4f7_100%)] px-6">
        <div className="text-center rounded-[28px] border border-white/70 bg-white/85 px-10 py-12 shadow-[0_30px_80px_rgba(15,23,42,0.12)] backdrop-blur">
          <div className="mx-auto mb-5 h-14 w-14 animate-spin rounded-full border-4 border-teal-100 border-t-teal-600" />
          <p className="text-sm font-semibold uppercase tracking-[0.28em] text-teal-700">GroundwaterGPT</p>
          <p className="mt-2 text-lg text-slate-700">Loading monitoring sites and groundwater context…</p>
        </div>
      </div>
    )
  }

  if (error && sites.length === 0) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_rgba(248,113,113,0.12),_transparent_36%),linear-gradient(180deg,_#fffaf7_0%,_#f6f2ef_100%)] px-6">
        <div className="max-w-xl rounded-[28px] border border-white/70 bg-white/90 p-8 shadow-[0_30px_80px_rgba(15,23,42,0.12)] backdrop-blur">
          <h2 className="text-2xl font-semibold text-slate-900">Connection Error</h2>
          <p className="mt-3 text-slate-600">{error}</p>
          <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50/70 p-4 text-sm">
            <p className="mb-2 font-semibold text-amber-900">Start the API server</p>
            <code className="text-amber-700">cd GroundwaterGPT/api && uvicorn main:app --reload</code>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-[radial-gradient(circle_at_top_left,_rgba(20,184,166,0.18),_transparent_28%),radial-gradient(circle_at_top_right,_rgba(14,165,233,0.12),_transparent_34%),linear-gradient(180deg,_#f6fbfb_0%,_#edf4f7_52%,_#f8fbfd_100%)] text-slate-900 lg:flex-row">
      <Sidebar
        sites={sites}
        selectedSite={selectedSite}
        onSiteSelect={handleSiteSelect}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        networkSummary={networkSummary}
      />
      <main className="flex-1 overflow-auto">
        <Dashboard
          site={selectedSite}
          data={siteData}
          heatmapData={heatmapData}
          stats={stats}
          sites={sites}
          loading={loading}
          error={error}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          setSelectedSite={setSelectedSite}
          workbenchSeed={workbenchSeed}
          onWorkbenchSeedConsumed={handleWorkbenchSeedConsumed}
          onOpenWorkbench={handleOpenWorkbench}
          networkSummary={networkSummary}
        />
      </main>
    </div>
  )
}

export default App
