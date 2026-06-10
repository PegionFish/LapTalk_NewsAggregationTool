import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { LogicChain } from '../types';

export default function ChainList() {
  const [chains, setChains] = useState<LogicChain[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api.listChains().then(res => setChains(res.chains)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const handleDelete = async (id: number, title: string) => {
    if (!confirm(`删除「${title}」？`)) return;
    await api.deleteChain(id);
    setChains(chains => chains.filter(c => c.id !== id));
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>📋 逻辑链列表</h2>
        <button onClick={() => navigate('/chains/new')}
          style={{ background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '8px 16px', color: '#000', fontWeight: 'bold', fontSize: 13, cursor: 'pointer' }}>
          ＋ 新建
        </button>
      </div>

      {loading && <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: 40 }}>加载中...</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {chains.map(chain => (
          <div key={chain.id} style={{ background: 'var(--bg-secondary)', borderRadius: 10, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
              <div>
                <div style={{ fontWeight: 'bold', fontSize: 14, marginBottom: 4 }}>{chain.title}</div>
                {chain.description && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>{chain.description}</div>}
                <div style={{ display: 'flex', gap: 12, fontSize: 11, color: 'var(--text-secondary)' }}>
                  <span>{chain.event_count} 个事件</span>
                  <span>创建于 {chain.created_at?.slice(0, 16).replace('T', ' ')}</span>
                  {chain.updated_at && chain.updated_at !== chain.created_at && (
                    <span>更新于 {chain.updated_at?.slice(0, 16).replace('T', ' ')}</span>
                  )}
                  <span>{chain.created_by === 'auto' ? 'AI 生成' : '人工创建'}</span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button onClick={() => navigate(`/chains/${chain.id}`)}
                  style={{ background: 'var(--bg-card)', border: 'none', borderRadius: 4, padding: '6px 12px', color: 'var(--accent)', fontSize: 11, cursor: 'pointer' }}>编辑</button>
                <button onClick={() => handleDelete(chain.id, chain.title)}
                  style={{ background: 'var(--bg-card)', border: 'none', borderRadius: 4, padding: '6px 12px', color: 'var(--accent-red)', fontSize: 11, cursor: 'pointer' }}>删除</button>
              </div>
            </div>
          </div>
        ))}
        {!loading && chains.length === 0 && <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: 40 }}>暂无逻辑链</div>}
      </div>
    </div>
  );
}
