interface StatCardProps {
  icon: string;
  label: string;
  value: string | number;
  color: string;
  onClick?: () => void;
  trend?: 'up' | 'down' | 'flat' | null;
  hint?: string;
}

export function StatCard({ icon, label, value, color, onClick, trend, hint }: StatCardProps) {
  const content = (
    <>
      <i className={`fas ${icon} ui-stat__icon`} style={{ color }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="ui-stat__value" style={{ color }}>
          <span>{value}</span>
          {trend === 'up' && <i className="fas fa-arrow-trend-up ui-stat__trend ui-stat__trend--up" />}
          {trend === 'down' && <i className="fas fa-arrow-trend-down ui-stat__trend ui-stat__trend--down" />}
          {trend === 'flat' && <i className="fas fa-minus ui-stat__trend ui-stat__trend--flat" />}
        </div>
        <div className="ui-stat__label">{label}</div>
      </div>
      {onClick && <i className="fas fa-chevron-right ui-stat__arrow" />}
      {hint && !onClick && <i className="fas fa-info-circle ui-stat__hint" title={hint} />}
    </>
  );

  if (onClick) {
    return (
      <button className="ui-stat ui-stat--clickable" onClick={onClick} title={hint}>
        {content}
      </button>
    );
  }
  return <div className="ui-stat">{content}</div>;
}
