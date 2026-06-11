import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon?: string;
  children: ReactNode;
}

export function EmptyState({ icon = 'fa-inbox', children }: EmptyStateProps) {
  return (
    <div className="ui-empty">
      <i className={`fas ${icon} ui-empty__icon`} />
      {children}
    </div>
  );
}
