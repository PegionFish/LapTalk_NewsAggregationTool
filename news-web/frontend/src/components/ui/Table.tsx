import type { ReactNode } from 'react';

interface TableProps {
  children: ReactNode;
  className?: string;
}

export function Table({ children, className = '' }: TableProps) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className={`ui-table ${className}`}>
        {children}
      </table>
    </div>
  );
}

export function TableHead({ children }: { children: ReactNode }) {
  return <thead>{children}</thead>;
}

export function TableRow({ children, active, className = '' }: { children: ReactNode; active?: boolean; className?: string }) {
  return (
    <tr className={`${active ? 'ui-table__row--active' : ''} ${className}`}>
      {children}
    </tr>
  );
}
