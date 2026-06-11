interface LoadingProps {
  text?: string;
}

export function Loading({ text = '加载中...' }: LoadingProps) {
  return (
    <div className="ui-loading">
      <i className="fas fa-spinner ui-loading__spinner" style={{ color: 'var(--accent)' }} />
      <span>{text}</span>
    </div>
  );
}
