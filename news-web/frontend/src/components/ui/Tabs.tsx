import type { ReactNode } from 'react';

interface TabsProps {
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

export function Tabs({ children, className = '', style }: TabsProps) {
  return <div className={`ui-tabs ${className}`} style={style}>{children}</div>;
}

interface TabProps {
  active?: boolean;
  icon?: string;
  count?: number;
  color?: string;
  onClick?: () => void;
  children: ReactNode;
  disabled?: boolean;
}

export function Tab({ active, icon, count, color, onClick, children, disabled }: TabProps) {
  return (
    <button
      className={`ui-tab ${active ? 'ui-tab--active' : ''}`}
      onClick={onClick}
      disabled={disabled}
      style={active && color ? {
        borderColor: color,
        color: color,
        background: `${color}10`,
      } : undefined}
    >
      {icon && <i className={`fas ${icon}`} />}
      <span>{children}</span>
      {count !== undefined && (
        <span
          className="ui-tab__count"
          style={active && color ? { background: `${color}20`, color } : undefined}
        >
          {count}
        </span>
      )}
    </button>
  );
}
