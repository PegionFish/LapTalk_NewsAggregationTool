import type { Stats } from '../types';
import { StatCard } from './ui';

interface Props {
  stats: Stats | null;
  loading: boolean;
}

export default function DashboardCards({ stats, loading }: Props) {
  if (loading) return <div style={{ color: 'var(--text-secondary)', padding: '20px 0' }}>加载中...</div>;
  if (!stats) return <div style={{ color: 'var(--accent-red)', padding: '20px 0' }}>数据库未配置</div>;

  const cards = [
    { label: '总文章数', value: stats.articles, color: 'var(--accent)', icon: 'fa-newspaper' },
    { label: '活跃事件', value: stats.active_events, color: 'var(--accent-green)', icon: 'fa-bolt' },
    { label: '待审核', value: stats.articles - stats.human_verified, color: 'var(--accent-orange)', icon: 'fa-clock' },
    { label: '已审核', value: stats.human_verified, color: 'var(--accent-purple)', icon: 'fa-check-circle' },
  ];

  const cacheCards = [
    { label: 'HTML 已缓存', value: stats.cache_cached, color: 'var(--accent-green)', icon: 'fa-database' },
    { label: '文本已提取', value: stats.cache_text, color: 'var(--accent)', icon: 'fa-file-alt' },
    { label: '下载失败', value: stats.cache_failed, color: 'var(--accent-red)', icon: 'fa-exclamation-triangle' },
    { label: '待下载', value: stats.cache_pending, color: 'var(--accent-orange)', icon: 'fa-download' },
  ];

  const cacheCoverage = stats.articles > 0 ? Math.round((stats.cache_cached / stats.articles) * 100) : 0;
  const textCoverage = stats.articles > 0 ? Math.round((stats.cache_text / stats.articles) * 100) : 0;

  const getCoverageColor = (pct: number, thresholds: [number, number]) => {
    if (pct > thresholds[0]) return 'var(--accent-tertiary)';
    if (pct > thresholds[1]) return 'var(--accent-orange)';
    return 'var(--accent-red)';
  };

  const getCoverageGradient = (pct: number, thresholds: [number, number]) => {
    if (pct > thresholds[0]) return 'var(--gradient-accent)';
    if (pct > thresholds[1]) return 'linear-gradient(90deg, #ffb74d, #00d4ff)';
    return 'var(--gradient-secondary)';
  };

  return (
    <div className="ui-fade-in">
      {/* 核心统计 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
        gap: 16,
        marginBottom: 16,
      }}>
        {cards.map(c => (
          <StatCard key={c.label} icon={c.icon} label={c.label} value={c.value} color={c.color} />
        ))}
      </div>

      {/* 缓存统计 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
        gap: 16,
      }}>
        {cacheCards.map(c => (
          <StatCard key={c.label} icon={c.icon} label={c.label} value={c.value} color={c.color} />
        ))}
      </div>

      {/* 缓存覆盖率进度条 */}
      <div style={{
        background: 'var(--bg-secondary)',
        borderRadius: 'var(--radius-lg)',
        padding: '16px 20px',
        marginTop: 16,
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
      }}>
        {/* HTML 缓存 */}
        <div>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 12,
            color: 'var(--text-secondary)',
            marginBottom: 6,
          }}>
            <span><i className="fas fa-archive" style={{ marginRight: 6 }} />HTML 缓存</span>
            <span style={{
              fontWeight: 600,
              color: getCoverageColor(cacheCoverage, [70, 40]),
            }}>
              {cacheCoverage}% · {stats.cache_cached}/{stats.articles}
            </span>
          </div>
          <div style={{
            height: 6,
            background: 'var(--bg-primary)',
            borderRadius: 3,
            overflow: 'hidden',
          }}>
            <div style={{
              height: '100%',
              borderRadius: 3,
              transition: 'width 0.6s ease',
              width: `${cacheCoverage}%`,
              background: getCoverageGradient(cacheCoverage, [70, 40]),
            }} />
          </div>
        </div>
        {/* 文本提取 */}
        <div>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 12,
            color: 'var(--text-secondary)',
            marginBottom: 6,
          }}>
            <span><i className="fas fa-file-alt" style={{ marginRight: 6 }} />文本提取</span>
            <span style={{
              fontWeight: 600,
              color: getCoverageColor(textCoverage, [50, 20]),
            }}>
              {textCoverage}% · {stats.cache_text}/{stats.articles}
            </span>
          </div>
          <div style={{
            height: 6,
            background: 'var(--bg-primary)',
            borderRadius: 3,
            overflow: 'hidden',
          }}>
            <div style={{
              height: '100%',
              borderRadius: 3,
              transition: 'width 0.6s ease',
              width: `${textCoverage}%`,
              background: getCoverageGradient(textCoverage, [50, 20]),
            }} />
          </div>
        </div>
      </div>
    </div>
  );
}
