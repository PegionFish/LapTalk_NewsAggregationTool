interface StatCardProps {
  icon: string;
  label: string;
  value: string | number;
  color: string;
}

export function StatCard({ icon, label, value, color }: StatCardProps) {
  return (
    <div className="ui-stat">
      <i className={`fas ${icon} ui-stat__icon`} style={{ color }} />
      <div>
        <div className="ui-stat__value" style={{ color }}>{value}</div>
        <div className="ui-stat__label">{label}</div>
      </div>
    </div>
  );
}
