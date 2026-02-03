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

export default function MapView({ sites = [], selectedSite, setSelectedSite }) {
  const getColor = (site) => {
    return site.aquifer === 'Biscayne Aquifer' ? '#3b82f6' : '#f59e0b'
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
                <div className="min-w-[200px]">
                  <h3 className="font-bold text-slate-800">{site.name}</h3>
                  <p className="text-sm text-slate-500">{site.aquifer}</p>
                  <p className="text-sm text-slate-500">{site.county} County</p>

                  <div className="mt-3 pt-3 border-t border-slate-200">
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div>
                        <p className="text-slate-400">Site ID</p>
                        <p className="font-semibold text-xs">{site.id}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Records</p>
                        <p className="font-semibold">{site.recordCount || 'N/A'}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Depth</p>
                        <p className="font-semibold">{site.depth} ft</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Coords</p>
                        <p className="font-semibold text-xs">{site.lat?.toFixed(2)}°N</p>
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={() => setSelectedSite(site)}
                    className="mt-3 w-full bg-blue-500 text-white text-sm py-2 rounded-lg hover:bg-blue-600 transition-colors"
                  >
                    View Details
                  </button>
                </div>
              </Popup>
            </CircleMarker>
          )
        })}
      </MapContainer>

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-white rounded-lg shadow-lg p-4 z-[1000]">
        <p className="text-sm font-semibold text-slate-700 mb-2">Aquifer Types</p>
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm">
            <div className="w-4 h-4 rounded-full bg-blue-500" />
            <span>Biscayne Aquifer</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <div className="w-4 h-4 rounded-full bg-amber-500" />
            <span>Floridan Aquifer</span>
          </div>
        </div>
      </div>
    </div>
  )
}
