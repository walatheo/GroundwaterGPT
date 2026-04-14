export default function StatsCard({ title, value, subtitle, icon, color = 'blue' }) {
  const colorClasses = {
    blue: 'from-blue-50 to-cyan-50 text-blue-700 border-blue-100/80',
    cyan: 'from-cyan-50 to-teal-50 text-cyan-700 border-cyan-100/80',
    green: 'from-emerald-50 to-lime-50 text-emerald-700 border-emerald-100/80',
    red: 'from-rose-50 to-orange-50 text-rose-700 border-rose-100/80',
    purple: 'from-fuchsia-50 to-violet-50 text-fuchsia-700 border-fuchsia-100/80',
    amber: 'from-amber-50 to-yellow-50 text-amber-700 border-amber-100/80',
    slate: 'from-slate-50 to-white text-slate-700 border-slate-200/80',
  }

  const iconColorClasses = {
    blue: 'bg-blue-100 text-blue-700',
    cyan: 'bg-cyan-100 text-cyan-700',
    green: 'bg-emerald-100 text-emerald-700',
    red: 'bg-rose-100 text-rose-700',
    purple: 'bg-fuchsia-100 text-fuchsia-700',
    amber: 'bg-amber-100 text-amber-700',
    slate: 'bg-slate-100 text-slate-700',
  }

  return (
    <div className={`rounded-[24px] border bg-gradient-to-br p-5 shadow-sm ${colorClasses[color]}`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">{title}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">{value}</p>
          {subtitle && <p className="mt-2 text-sm text-slate-500">{subtitle}</p>}
        </div>
        <div className={`rounded-2xl p-3 shadow-sm ${iconColorClasses[color]}`}>
          {icon}
        </div>
      </div>
    </div>
  )
}
