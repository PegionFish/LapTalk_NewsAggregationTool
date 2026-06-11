interface LogPanelProps {
  entries: string[];
  maxLines?: number;
}

function getLineColor(line: string): string {
  if (line.includes('✅')) return 'ui-log__line--green';
  if (line.includes('❌')) return 'ui-log__line--red';
  if (line.includes('⚠') || line.includes('⏭')) return 'ui-log__line--yellow';
  return 'ui-log__line--blue';
}

export function LogPanel({ entries, maxLines = 40 }: LogPanelProps) {
  const lines = entries.slice(-maxLines);

  return (
    <div className="ui-log">
      {lines.map((line, i) => (
        <div key={i} className={`ui-log__line ${getLineColor(line)}`}>
          {line}
        </div>
      ))}
    </div>
  );
}
