// Lightweight SVG donut chart — no chart library needed.
export default function Donut({ segments, size = 220, thickness = 34, centerLabel, centerValue }) {
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const gap = segments.filter((s) => s.value > 0).length > 1 ? 3 : 0;
  let offset = 0;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Budget breakdown chart">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--track)" strokeWidth={thickness} />
      {segments.map((s) => {
        const len = (s.value / total) * c;
        const dash = Math.max(0, len - gap);
        const el = (
          <circle
            key={s.label}
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={s.color}
            strokeWidth={thickness}
            strokeDasharray={`${dash} ${c - dash}`}
            strokeDashoffset={-offset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          >
            <title>{`${s.label}: ${Math.round((s.value / total) * 100)}%`}</title>
          </circle>
        );
        offset += len;
        return el;
      })}
      <text x="50%" y="46%" textAnchor="middle" className="donut-label">
        {centerLabel}
      </text>
      <text x="50%" y="60%" textAnchor="middle" className="donut-value">
        {centerValue}
      </text>
    </svg>
  );
}
