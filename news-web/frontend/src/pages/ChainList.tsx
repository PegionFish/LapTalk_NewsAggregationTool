import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { LogicChain } from '../types';
import { Card, Button, EmptyState, Loading } from '../components/ui';

export default function ChainList() {
  const [chains, setChains] = useState<LogicChain[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api.listChains()
      .then(res => setChains(res.chains))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleDelete = async (id: number, title: string) => {
    if (!confirm(`删除「${title}」？`)) return;
    await api.deleteChain(id);
    setChains(chains => chains.filter(c => c.id !== id));
  };

  if (loading) {
    return <Loading text="加载逻辑链..." />;
  }

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
            <i className="fas fa-diagram-project" style={{ color: 'var(--accent)' }} />
            逻辑链列表
          </h2>
          <p style={{
            fontSize: 12,
            color: 'var(--text-muted)',
            margin: '4px 0 0 30px',
          }}>
            共 {chains.length} 条逻辑链
          </p>
        </div>
        <Button
          variant="primary"
          icon="fa-plus"
          onClick={() => navigate('/chains/new')}
        >
          新建
        </Button>
      </div>

      {/* 链列表 */}
      {chains.length === 0 ? (
        <EmptyState icon="fa-diagram-project">
          <p>暂无逻辑链</p>
          <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            点击「新建」开始创建你的第一个逻辑链
          </p>
        </EmptyState>
      ) : (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}>
          {chains.map(chain => (
            <Card key={chain.id} className="ui-fade-in">
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
              }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    onClick={() => navigate(`/chains/${chain.id}`)}
                    style={{
                      fontWeight: 600,
                      fontSize: 15,
                      marginBottom: 6,
                      color: 'var(--text-primary)',
                      cursor: 'pointer',
                      transition: 'color 0.15s',
                    }}
                    onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = 'var(--accent)'}
                    onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = 'var(--text-primary)'}
                  >
                    {chain.title}
                  </div>
                  {chain.description && (
                    <div style={{
                      fontSize: 13,
                      color: 'var(--text-secondary)',
                      marginBottom: 10,
                      lineHeight: 1.5,
                    }}>
                      {chain.description}
                    </div>
                  )}
                  <div style={{
                    display: 'flex',
                    gap: 16,
                    fontSize: 12,
                    color: 'var(--text-muted)',
                  }}>
                    <span>
                      <i className="fas fa-diagram-project" style={{ marginRight: 4 }} />
                      {chain.event_count} 个事件
                    </span>
                    <span>
                      <i className="fas fa-clock" style={{ marginRight: 4 }} />
                      {chain.created_at?.slice(0, 16).replace('T', ' ')}
                    </span>
                    <span style={{
                      color: chain.created_by === 'auto' ? 'var(--accent)' : 'var(--accent-tertiary)',
                    }}>
                      <i className={`fas ${chain.created_by === 'auto' ? 'fa-robot' : 'fa-user'}`} style={{ marginRight: 4 }} />
                      {chain.created_by === 'auto' ? 'AI 生成' : '人工创建'}
                    </span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, flexShrink: 0, marginLeft: 16 }}>
                  <Button
                    variant="ghost"
                    size="xs"
                    icon="fa-pen"
                    onClick={(e) => { e.stopPropagation(); navigate(`/chains/${chain.id}/edit`); }}
                  >
                    编辑
                  </Button>
                  <Button
                    variant="ghost"
                    size="xs"
                    icon="fa-trash"
                    onClick={() => handleDelete(chain.id, chain.title)}
                    style={{ color: 'var(--accent-red)' }}
                  >
                    删除
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
