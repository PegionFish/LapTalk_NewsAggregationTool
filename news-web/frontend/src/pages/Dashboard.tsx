import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Stats } from '../types';
import DashboardCards from '../components/DashboardCards';

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getStats().then(setStats).catch(() => setStats(null)).finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>📊 仪表盘</h2>
      <DashboardCards stats={stats} loading={loading} />

      {stats && (
        <div style={{ marginTop: 24, background: 'var(--bg-secondary)', borderRadius: 10, padding: 20 }}>
          <h3 style={{ fontSize: 15, marginBottom: 12 }}>来源分布</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {Object.entries(stats.by_category).map(([cat, count]) => (
              <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                <span style={{ width: 100, color: 'var(--text-secondary)' }}>{cat}</span>
                <div style={{ flex: 1, background: 'var(--bg-card)', borderRadius: 4, height: 16, overflow: 'hidden' }}>
                  <div style={{
                    width: `${(count / stats.articles) * 100}%`, height: '100%',
                    background: 'var(--accent)', borderRadius: 4, minWidth: 4
                  }} />
                </div>
                <span style={{ width: 40, textAlign: 'right' }}>{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
