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

  // 核心统计卡片
  const cards = [
    { label: '总文章数', value: stats.articles, color: 'var(--accent)' },
    { label: '活跃事件', value: stats.active_events, color: 'var(--accent-green)' },
    { label: '待审核', value: stats.articles - stats.human_verified, color: 'var(--accent-orange)' },
    { label: '已审核', value: stats.human_verified, color: 'var(--accent-purple)' },
  ];

  // 缓存统计卡片
  const cacheCards = [
    { label: '已缓存', value: stats.cache_cached, color: 'var(--accent-green)', icon: 'fa-database' },
    { label: '待下载', value: stats.cache_pending, color: 'var(--accent-orange)', icon: 'fa-download' },
    { label: '下载失败', value: stats.cache_failed, color: 'var(--accent-red)', icon: 'fa-exclamation-triangle' },
  ];

  const cacheCoverage = stats.articles > 0 ? Math.round((stats.cache_cached / stats.articles) * 100) : 0;

  return (
    <div>
      {/* 核心统计 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16, marginBottom: 16 }}>
        {cards.map(c => (
          <div key={c.label} style={CARD_STYLE}>
            <div style={{ fontSize: 32, fontWeight: 'bold', color: c.color }}>{c.value}</div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>{c.label}</div>
          </div>
        ))}
      </div>

      {/* 缓存统计 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16 }}>
        {cacheCards.map(c => (
          <div key={c.label} style={{ ...CARD_STYLE, display: 'flex', alignItems: 'center', gap: 14, textAlign: 'left', padding: '16px 20px' }}>
            <i className={`fas ${c.icon}`} style={{ color: c.color, fontSize: 24, width: 32, textAlign: 'center' }} />
            <div>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: c.color }}>{c.value}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{c.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* 缓存覆盖率进度条 */}
      <div style={{ background: 'var(--bg-secondary)', borderRadius: 10, padding: '14px 20px', marginTop: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-secondary)', marginBottom: 6 }}>
          <span><i className="fas fa-archive" style={{ marginRight: 6 }} />缓存覆盖率</span>
          <span style={{ fontWeight: 600, color: cacheCoverage > 70 ? 'var(--accent-tertiary)' : cacheCoverage > 40 ? 'var(--accent-orange)' : 'var(--accent-red)' }}>{cacheCoverage}%</span>
        </div>
        <div style={{ height: 6, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{
            height: '100%', borderRadius: 3, transition: 'width 0.6s ease',
            width: `${cacheCoverage}%`,
            background: cacheCoverage > 70 ? 'var(--gradient-accent)'
              : cacheCoverage > 40 ? 'linear-gradient(90deg, #ffb74d, #00d4ff)'
              : 'var(--gradient-secondary)',
          }} />
        </div>
      </div>
    </div>
  );
}
