import type { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
  flat?: boolean;
  style?: React.CSSProperties;
}

export function Card({ children, className = '', flat, style }: CardProps) {
  return (
    <div className={`ui-card ${flat ? 'ui-card--flat' : ''} ${className}`} style={style}>
      {children}
    </div>
  );
}

interface CardHeaderProps {
  icon?: string;
  iconColor?: string;
  title: string;
  desc?: string;
}

export function CardHeader({ icon, iconColor, title, desc }: CardHeaderProps) {
  return (
    <div className="ui-card__header">
      {icon && (
        <i
          className={`fas ${icon} ui-card__icon`}
          style={{ color: iconColor || 'var(--accent)' }}
        />
      )}
      <div>
        <div className="ui-card__title">{title}</div>
        {desc && <div className="ui-card__desc">{desc}</div>}
      </div>
    </div>
  );
}

export function CardBody({ children }: { children: ReactNode }) {
  return <div className="ui-card__body">{children}</div>;
}
