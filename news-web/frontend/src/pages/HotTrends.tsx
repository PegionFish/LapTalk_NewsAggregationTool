import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../api/client';
import type { HotlistItem } from '../types';
import { Card, Button, Tabs, Tab, EmptyState, Loading } from '../components/ui';

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
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [activeTab, setActiveTab] = useState('weibo');
  const [error, setError] = useState('');
  const [hasLoaded, setHasLoaded] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  // 轮询实时抓取状态
  const pollLive = useCallback(async () => {
    try {
      const res = await api.getHotlistsLive();
      if (res.status === 'done' && res.data) {
        setData(res.data);
        setFetching(false);
        setHasLoaded(true);
        clearInterval(timerRef.current);
      }
    } catch {
      clearInterval(timerRef.current);
      setFetching(false);
    }
  }, []);

  // 启动实时抓取
  const handleFetch = useCallback(async () => {
    setFetching(true);
    setError('');
    try {
      await api.startLiveFetch();
      // 开始轮询
      timerRef.current = setInterval(pollLive, 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : '启动失败');
      setFetching(false);
    }
  }, [pollLive]);

  // 页面挂载时自动抓取
  useEffect(() => {
    handleFetch();
    return () => clearInterval(timerRef.current);
  }, []); // eslint-disable-line

  // 选第一个有数据的平台
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
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 24,
      }}>
        <div>
          <h2 style={{
            fontSize: 20,
            fontWeight: 700,
            margin: 0,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}>
            <i className="fas fa-chart-line" style={{ color: 'var(--accent)' }} />
            实时热点
          </h2>
          <p style={{
            fontSize: 12,
            color: 'var(--text-muted)',
            margin: '4px 0 0 30px',
          }}>
            现场抓取 · 仅展示当前实时数据 · 共 {totalCount} 条
          </p>
        </div>
        <Button
          variant="primary"
          icon="fa-sync-alt"
          loading={fetching}
          onClick={handleFetch}
        >
          重新抓取
        </Button>
      </div>

      {error && (
        <div style={{
          padding: 12,
          marginBottom: 16,
          background: 'rgba(255, 56, 82, 0.1)',
          borderRadius: 8,
          color: '#ff3852',
          fontSize: 13,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <i className="fas fa-exclamation-circle" />
          {error}
        </div>
      )}

      {/* 平台 Tab */}
      <Tabs>
        {PLATFORM_ORDER.map(pid => {
          const meta = PLATFORM_META[pid];
          const count = data[pid]?.count || 0;
          return (
            <Tab
              key={pid}
              active={activeTab === pid}
              icon={meta.icon}
              count={count}
              color={meta.color}
              onClick={() => setActiveTab(pid)}
            >
              {meta.label}
            </Tab>
          );
        })}
      </Tabs>

      {/* 榜单内容 */}
      {fetching && !hasLoaded ? (
        <Loading text="正在抓取各平台热点数据..." />
      ) : (
        <Card flat style={{ padding: 0 }}>
          {/* 列表头 */}
          <div style={{
            padding: '12px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <span style={{
              fontSize: 14,
              fontWeight: 600,
              color: 'var(--text-primary)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}>
              <i
                className={`fas ${PLATFORM_META[activeTab]?.icon || 'fa-list'}`}
                style={{ color: PLATFORM_META[activeTab]?.color }}
              />
              {PLATFORM_META[activeTab]?.label}
            </span>
            <span style={{
              fontSize: 12,
              color: 'var(--text-muted)',
            }}>
              {currentItems.length} 条
            </span>
          </div>

          {currentItems.length === 0 ? (
            <EmptyState icon="fa-inbox">
              <p>暂无数据</p>
              <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                点击「重新抓取」获取最新热点
              </p>
            </EmptyState>
          ) : (
            <div style={{
              maxHeight: 'calc(100vh - 300px)',
              overflow: 'auto',
            }}>
              {currentItems.map((item, idx) => {
                const meta = PLATFORM_META[activeTab];
                const isTop3 = item.rank && item.rank <= 3;
                return (
                  <a
                    key={item.id || idx}
                    href={item.url || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 14,
                      padding: '12px 20px',
                      borderBottom: '1px solid var(--border)',
                      textDecoration: 'none',
                      color: 'inherit',
                      transition: 'background var(--transition-fast)',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-card-hover)')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                  >
                    {/* 排名 */}
                    <span style={{
                      width: 28,
                      height: 28,
                      borderRadius: 8,
                      background: isTop3 ? `${meta.color}20` : 'var(--bg-primary)',
                      color: isTop3 ? meta.color : 'var(--text-muted)',
                      fontSize: 13,
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                      border: isTop3 ? `1px solid ${meta.color}30` : '1px solid transparent',
                    }}>
                      {item.rank || '-'}
                    </span>

                    {/* 标题 */}
                    <span style={{
                      flex: 1,
                      fontSize: 13,
                      color: 'var(--text-primary)',
                      lineHeight: 1.5,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}>
                      {item.title}
                    </span>

                    {/* 热度 */}
                    {item.heat && (
                      <span style={{
                        fontSize: 11,
                        color: 'var(--text-muted)',
                        whiteSpace: 'nowrap',
                        flexShrink: 0,
                        marginLeft: 8,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                      }}>
                        <i className="fas fa-fire" style={{ fontSize: 9, color: 'var(--accent-orange)' }} />
                        {Number(item.heat) > 9999
                          ? `${(Number(item.heat) / 10000).toFixed(1)}万`
                          : item.heat}
                      </span>
                    )}

                    {/* 作者 */}
                    {item.author && (
                      <span style={{
                        fontSize: 11,
                        color: 'var(--text-muted)',
                        whiteSpace: 'nowrap',
                        flexShrink: 0,
                        maxWidth: 100,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                      }}>
                        <i className="fas fa-user" style={{ fontSize: 9 }} />
                        {item.author}
                      </span>
                    )}
                  </a>
                );
              })}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
