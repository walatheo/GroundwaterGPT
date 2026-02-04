import { useEffect } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'

// Component to fit map bounds
function FitBounds({ sites }) {
  const map = useMap()

  useEffect(() => {
    if (sites && sites.length > 0) {
      const bounds = sites.map(s => [s.lat, s.lng])
      map.fitBounds(bounds, { padding: [50, 50] })
    }
  }, [sites, map])

  return null
}

// County color mapping
const COUNTY_COLORS = {
  'Miami-Dade': '#3b82f6',  // Blue
  'Lee': '#f59e0b',         // Amber
  'Collier': '#10b981',     // Green
  'Sarasota': '#8b5cf6',    // Purple
  'Hendry': '#ef4444',      // Red
}

export default function MapView({ sites = [], selectedSite, setSelectedSite }) {
  const getColor = (site) => {
    return COUNTY_COLORS[site.county] || '#64748b'  // Default slate
  }

  return (
    <div className="h-[600px] relative">
      <MapContainer
        center={[25.8, -80.8]}
        zoom={8}
        className="h-full w-full"
        scrollWheelZoom={true}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {sites.length > 0 && <FitBounds sites={sites} />}

        {sites.map(site => {
          const isSelected = selectedSite?.id === site.id

          return (
            <CircleMarker
              key={site.id}
              center={[site.lat, site.lng]}
              radius={isSelected ? 15 : 10}
              pathOptions={{
                color: isSelected ? '#1e40af' : getColor(site),
                fillColor: getColor(site),
                fillOpacity: 0.8,
                weight: isSelected ? 3 : 2
              }}
              eventHandlers={{
                click: () => setSelectedSite(site)
              }}
            >
              <Popup>
                <div className="min-w-[220px]">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="font-bold text-slate-800">{site.name}</h3>
                    <span className="bg-green-100 text-green-700 text-xs px-2 py-0.5 rounded-full">
                      ✓ USGS Verified
                    </span>
                  </div>
                  <p className="text-sm text-slate-500">{site.aquifer}</p>
                  <p className="text-sm text-slate-500">{site.county} County, Florida</p>

                  <div className="mt-3 pt-3 border-t border-slate-200">
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div>
                        <p className="text-slate-400">Site ID</p>
                        <p className="font-mono text-xs">{site.id}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Records</p>
                        <p className="font-semibold">{site.recordCount?.toLocaleString() || 'N/A'}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Well Depth</p>
                        <p className="font-semibold">{site.depth} ft</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Coordinates</p>
                        <p className="font-mono text-xs">{site.lat?.toFixed(3)}°N</p>
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={() => setSelectedSite(site)}
                    className="mt-3 w-full bg-blue-500 text-white text-sm py-2 rounded-lg hover:bg-blue-600 transition-colors"
                  >
                    View Time Series →
                  </button>
                </div>
              </Popup>
            </CircleMarker>
          )
        })}
      </MapContainer>

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-white rounded-lg shadow-lg p-4 z-[1000]">
        <p className="text-sm font-semibold text-slate-700 mb-2">Counties ({sites.length} sites)</p>
        <div className="space-y-1.5">
          {Object.entries(COUNTY_COLORS).map(([county, color]) => {
            const count = sites.filter(s => s.county === county).length
            if (count === 0) return null
            return (
              <div key={county} className="flex items-center gap-2 text-sm">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
                <span className="text-slate-600">{county}</span>
                <span className="text-slate-400 text-xs">({count})</span>
              </div>
            )
          })}
        </div>
        <div className="mt-3 pt-2 border-t border-slate-200">
          <div className="flex items-center gap-1 text-xs text-green-600">
            <span>✓</span>
            <span>All data from USGS NWIS</span>
          </div>
        </div>
      </div>

      {/* Site count badge */}
      <div className="absolute top-4 right-4 bg-white rounded-lg shadow-lg px-3 py-2 z-[1000]">
        <p className="text-sm font-semibold text-slate-700">
          📍 {sites.length} Monitoring Sites
        </p>
      </div>
    </div>
  )
}
