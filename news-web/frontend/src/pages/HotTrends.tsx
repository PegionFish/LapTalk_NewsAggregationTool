import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { HotlistItem } from '../types';

const PLATFORM_META: Record<string, { label: string; icon: string; color: string }> = {
  weibo:    { label: '微博热搜', icon: 'fa-fire', color: '#ff3852' },
  zhihu:    { label: '知乎热榜', icon: 'fa-lightbulb', color: '#0066ff' },
  douyin:   { label: '抖音热榜', icon: 'fa-music', color: '#fe2c55' },
  toutiao:  { label: '头条热榜', icon: 'fa-bolt', color: '#e53333' },
  bilibili: { label: 'B站热门', icon: 'fa-play-circle', color: '#00a1d6' },
};

const PLATFORM_ORDER = ['weibo', 'zhihu', 'douyin', 'toutiao', 'bilibili'];

export default function HotTrends() {
  const [data, setData] = useState<Record<string, { count: number; items: HotlistItem[] }>>({});
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('weibo');
  const [error, setError] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await api.getHotlists();
      setData(result as unknown as Record<string, { count: number; items: HotlistItem[] }>);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // 确定当前活跃 tab（选第一个有数据的平台）
  useEffect(() => {
    if (!loading && data) {
      const first = PLATFORM_ORDER.find(p => data[p]?.count > 0);
      if (first) setActiveTab(first);
    }
  }, [loading, data]);

  const currentItems = data[activeTab]?.items || [];
  const totalCount = Object.values(data).reduce((s, v) => s + v.count, 0);

  return (
    <div style={{ padding: 24, overflow: 'auto', flex: 1 }}>
      {/* 标题栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
            <i className="fas fa-chart-line" style={{ marginRight: 10, color: 'var(--accent)' }} />
            实时热点
          </h1>
          <p style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '4px 0 0 0' }}>
            来自微博/知乎/抖音/头条热搜 + B站热门视频 · 共 {totalCount} 条
          </p>
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          style={{
            background: 'var(--accent)', color: '#000', border: 'none', borderRadius: 6,
            padding: '7px 16px', fontSize: 12, cursor: 'pointer', fontWeight: 600,
            opacity: loading ? 0.5 : 1, transition: 'opacity 0.2s',
          }}
        >
          <i className={`fas fa-sync-alt${loading ? ' fa-spin' : ''}`} style={{ marginRight: 6 }} />
          刷新
        </button>
      </div>

      {error && (
        <div style={{ padding: 12, marginBottom: 16, background: 'rgba(255,56,82,0.1)', borderRadius: 6, color: '#ff3852', fontSize: 13 }}>
          {error}
        </div>
      )}

      {/* 平台 Tab */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        {PLATFORM_ORDER.map(pid => {
          const meta = PLATFORM_META[pid];
          const count = data[pid]?.count || 0;
          const isActive = activeTab === pid;
          return (
            <button
              key={pid}
              onClick={() => setActiveTab(pid)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '8px 14px', borderRadius: 8, border: `1px solid ${isActive ? meta.color : 'var(--border)'}`,
                background: isActive ? `${meta.color}10` : 'var(--bg-secondary)',
                color: isActive ? meta.color : 'var(--text-secondary)',
                fontSize: 13, cursor: 'pointer', fontWeight: isActive ? 600 : 400,
                transition: 'var(--transition-fast)',
                opacity: count === 0 && !isActive ? 0.4 : 1,
              }}
            >
              <i className={`fas ${meta.icon}`} />
              <span>{meta.label}</span>
              <span style={{
                fontSize: 11, padding: '1px 6px', borderRadius: 10,
                background: isActive ? `${meta.color}20` : 'var(--bg-primary)',
                color: isActive ? meta.color : 'var(--text-secondary)',
              }}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* 榜单内容 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
          <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }} />
          <p style={{ marginTop: 12 }}>加载中...</p>
        </div>
      ) : (
        <div style={{
          background: 'var(--bg-secondary)', borderRadius: 10, border: '1px solid var(--border)',
          overflow: 'hidden',
        }}>
          <div style={{
            padding: '10px 16px', borderBottom: '1px solid var(--border)',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              <i className={`fas ${PLATFORM_META[activeTab]?.icon || 'fa-list'}`} style={{ marginRight: 8, color: PLATFORM_META[activeTab]?.color }} />
              {PLATFORM_META[activeTab]?.label} · {currentItems.length} 条
            </span>
          </div>

          {currentItems.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              暂无数据 · 请等待 pipeline 执行后自动填充
            </div>
          ) : (
            <div style={{ maxHeight: 'calc(100vh - 260px)', overflow: 'auto' }}>
              {currentItems.map((item, idx) => {
                const meta = PLATFORM_META[activeTab];
                const rankColor = item.rank && item.rank <= 3 ? meta.color : 'var(--text-muted)';
                return (
                  <a
                    key={item.id || idx}
                    href={item.url || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: 'flex', alignItems: 'flex-start', gap: 12, padding: '10px 16px',
                      borderBottom: '1px solid var(--border)',
                      textDecoration: 'none', color: 'inherit',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                  >
                    {/* 排名 */}
                    <span style={{
                      width: 24, height: 24, borderRadius: 6,
                      background: item.rank && item.rank <= 3 ? `${meta.color}20` : 'var(--bg-primary)',
                      color: rankColor, fontSize: 13, fontWeight: 700,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                    }}>
                      {item.rank || '-'}
                    </span>

                    {/* 标题 */}
                    <span style={{
                      flex: 1, fontSize: 13, color: 'var(--text-primary)',
                      lineHeight: 1.5, overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}>
                      {item.title}
                    </span>

                    {/* 热度 / 作者 */}
                    {item.heat && (
                      <span style={{
                        fontSize: 11, color: 'var(--text-muted)',
                        whiteSpace: 'nowrap', flexShrink: 0, marginLeft: 8,
                      }}>
                        {Number(item.heat) > 9999
                          ? `${(Number(item.heat) / 10000).toFixed(1)}万`
                          : item.heat}
                      </span>
                    )}
                    {item.author && (
                      <span style={{
                        fontSize: 11, color: 'var(--text-muted)',
                        whiteSpace: 'nowrap', flexShrink: 0, maxWidth: 100,
                        overflow: 'hidden', textOverflow: 'ellipsis',
                      }}>
                        <i className="fas fa-user" style={{ marginRight: 4, fontSize: 9 }} />
                        {item.author}
                      </span>
                    )}
                  </a>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
