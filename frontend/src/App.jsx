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

  if (loading && sites.length === 0) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-100">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-slate-600">Loading monitoring sites...</p>
        </div>
      </div>
    )
  }

  if (error && sites.length === 0) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-100">
        <div className="text-center max-w-md p-8 bg-white rounded-lg shadow-lg">
          <div className="text-red-500 text-5xl mb-4">⚠️</div>
          <h2 className="text-xl font-bold text-slate-800 mb-2">Connection Error</h2>
          <p className="text-slate-600 mb-4">{error}</p>
          <div className="text-left bg-slate-50 p-4 rounded-lg text-sm font-mono">
            <p className="text-slate-500 mb-2">Start the API server:</p>
            <code className="text-blue-600">cd GroundwaterGPT/api && uvicorn main:app --reload</code>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-slate-100">
      <Sidebar
        sites={sites}
        selectedSite={selectedSite}
        onSiteSelect={handleSiteSelect}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
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
          setSelectedSite={setSelectedSite}
        />
      </main>
    </div>
  )
}

export default App
