import type { ReactNode } from 'react';

type BadgeVariant = 'green' | 'blue' | 'orange' | 'red' | 'purple' | 'muted';

interface BadgeProps {
  variant?: BadgeVariant;
  icon?: string;
  children: ReactNode;
  className?: string;
}

const variantClass: Record<BadgeVariant, string> = {
  green: 'ui-badge--green',
  blue: 'ui-badge--blue',
  orange: 'ui-badge--orange',
  red: 'ui-badge--red',
  purple: 'ui-badge--purple',
  muted: 'ui-badge--muted',
};

export function Badge({ variant = 'muted', icon, children, className = '' }: BadgeProps) {
  return (
    <span className={`ui-badge ${variantClass[variant]} ${className}`}>
      {icon && <i className={`fas ${icon}`} />}
      {children}
    </span>
  );
}
