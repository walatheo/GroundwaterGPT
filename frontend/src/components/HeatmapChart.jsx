import { useMemo } from 'react'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export default function HeatmapChart({ data, heatmapData, site }) {
  const processedData = useMemo(() => {
    if (!heatmapData || !heatmapData.data) return { matrix: [], years: [], minLevel: 0, maxLevel: 0 }

    const aggregated = heatmapData.data
    const years = [...new Set(aggregated.map(d => d.year))].sort()
    const minLevel = heatmapData.min
    const maxLevel = heatmapData.max

    // Create matrix
    const matrix = years.map(year => {
      const yearData = aggregated.filter(d => d.year === year)
      return MONTHS.map((_, monthIndex) => {
        const monthData = yearData.find(d => d.month === monthIndex + 1)
        return monthData ? monthData.value : null
      })
    })

    return { matrix, years, minLevel, maxLevel }
  }, [heatmapData])

  if (!heatmapData || !site) {
    return (
      <div className="h-[500px] flex items-center justify-center text-slate-400">
        Select a site to view heatmap data
      </div>
    )
  }

  const { matrix, years, minLevel, maxLevel } = processedData

  // Color scale function (blue = shallow, red = deep)
  const getColor = (value) => {
    if (value === null) return '#f1f5f9'

    const range = maxLevel - minLevel
    const normalized = (value - minLevel) / range

    // Interpolate between blue (#3b82f6) and red (#ef4444)
    const r = Math.round(59 + normalized * (239 - 59))
    const g = Math.round(130 + normalized * (68 - 130))
    const b = Math.round(246 + normalized * (68 - 246))

    return `rgb(${r}, ${g}, ${b})`
  }

  return (
    <div className="p-6">
      <div className="overflow-x-auto">
        <div className="inline-block min-w-full">
          {/* Month headers */}
          <div className="flex">
            <div className="w-16 shrink-0" /> {/* Spacer for year labels */}
            {MONTHS.map(month => (
              <div key={month} className="w-12 text-center text-xs font-medium text-slate-500 pb-2">
                {month}
              </div>
            ))}
          </div>

          {/* Heatmap grid */}
          <div className="space-y-1">
            {matrix.map((row, yearIndex) => (
              <div key={years[yearIndex]} className="flex items-center">
                <div className="w-16 shrink-0 text-sm font-medium text-slate-600 pr-2 text-right">
                  {years[yearIndex]}
                </div>
                {row.map((value, monthIndex) => (
                  <div
                    key={monthIndex}
                    className="w-12 h-8 mx-0.5 rounded-sm relative group cursor-pointer transition-transform hover:scale-110"
                    style={{ backgroundColor: getColor(value) }}
                  >
                    {/* Tooltip */}
                    {value !== null && (
                      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-slate-800 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10">
                        {MONTHS[monthIndex]} {years[yearIndex]}: {value.toFixed(2)} ft
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>

          {/* Color scale legend */}
          <div className="mt-6 flex items-center justify-center gap-4">
            <span className="text-sm text-slate-500">Shallow</span>
            <div className="flex h-4 rounded overflow-hidden">
              {Array.from({ length: 20 }).map((_, i) => {
                const value = minLevel + (i / 19) * (maxLevel - minLevel)
                return (
                  <div
                    key={i}
                    className="w-4 h-full"
                    style={{ backgroundColor: getColor(value) }}
                  />
                )
              })}
            </div>
            <span className="text-sm text-slate-500">Deep</span>
          </div>
          <div className="text-center mt-2 text-xs text-slate-400">
            {minLevel.toFixed(1)} ft — {maxLevel.toFixed(1)} ft below land surface
          </div>
        </div>
      </div>

      {/* Info */}
      <div className="mt-6 p-4 bg-amber-50 rounded-lg text-sm text-amber-800">
        <strong>Reading the Heatmap:</strong>
        <ul className="mt-2 list-disc list-inside space-y-1">
          <li><span className="text-blue-600 font-semibold">Blue</span> = Shallower water levels (closer to surface)</li>
          <li><span className="text-red-600 font-semibold">Red</span> = Deeper water levels (further from surface)</li>
          <li>Look for horizontal patterns (seasonal variations)</li>
          <li>Look for vertical gradients (long-term trends)</li>
        </ul>
      </div>
    </div>
  )
}
