import type { Stats } from '../types';

interface Props {
  stats: Stats | null;
  loading: boolean;
}

const CARD_STYLE: React.CSSProperties = {
  background: 'var(--bg-secondary)', padding: 20, borderRadius: 10, textAlign: 'center',
};

export default function DashboardCards({ stats, loading }: Props) {
  if (loading) return <div style={{ color: 'var(--text-secondary)' }}>加载中...</div>;
  if (!stats) return <div style={{ color: 'var(--accent-red)' }}>数据库未配置</div>;

  const cards = [
    { label: '总文章数', value: stats.articles, color: 'var(--accent)' },
    { label: '活跃事件', value: stats.active_events, color: 'var(--accent-green)' },
    { label: '待审核', value: stats.articles - stats.human_verified, color: 'var(--accent-orange)' },
    { label: '已审核', value: stats.human_verified, color: 'var(--accent-purple)' },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16 }}>
      {cards.map(c => (
        <div key={c.label} style={CARD_STYLE}>
          <div style={{ fontSize: 32, fontWeight: 'bold', color: c.color }}>{c.value}</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>{c.label}</div>
        </div>
      ))}
    </div>
  );
}
