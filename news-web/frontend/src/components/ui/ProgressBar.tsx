interface ProgressBarProps {
  done: number;
  total: number;
  failed?: number;
  current?: string;
  color?: string;
}

export function ProgressBar({ done, total, failed, current, color = 'var(--accent)' }: ProgressBarProps) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="ui-progress">
      <div className="ui-progress__info">
        <span>
          {done}/{total}
          {failed && failed > 0 ? ` · ${failed} 失败` : ''}
        </span>
        <span>{pct}%</span>
      </div>
      <div className="ui-progress__bar">
        <div
          className="ui-progress__fill"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      {current && <div className="ui-progress__current">{current}</div>}
    </div>
  );
}
