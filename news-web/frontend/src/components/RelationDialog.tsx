interface Props {
  open: boolean;
  onClose: () => void;
  onSelect: (relation: string) => void;
}

const RELATIONS = [
  { value: 'before', label: '之前发生', desc: '此事件在目标事件之前' },
  { value: 'after', label: '之后发生', desc: '此事件在目标事件之后' },
  { value: 'update', label: '更新', desc: '同一事件的新信息' },
  { value: 'spawn', label: '衍生', desc: '此事件导致另一事件' },
  { value: 'related', label: '相关', desc: '非时间性关联' },
];

export default function RelationDialog({ open, onClose, onSelect }: Props) {
  if (!open) return null;
  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
      onClick={onClose}>
      <div style={{ background: 'var(--bg-secondary)', borderRadius: 12, padding: 20, minWidth: 280 }} onClick={e => e.stopPropagation()}>
        <h3 style={{ fontSize: 14, marginBottom: 12 }}>选择关系类型</h3>
        {RELATIONS.map(r => (
          <div key={r.value} onClick={() => onSelect(r.value)}
            style={{ padding: '8px 12px', borderRadius: 6, cursor: 'pointer', marginBottom: 4, background: 'var(--bg-card)' }}>
            <div style={{ fontWeight: 'bold', fontSize: 12 }}>{r.label}</div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{r.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
