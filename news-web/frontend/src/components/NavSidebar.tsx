import { useMemo } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Button } from './ui';

const ALL_ITEMS = [
  { path: '/', label: '仪表盘', icon: 'fa-chart-pie', adminOnly: false },
  { path: '/articles', label: '文章检索', icon: 'fa-newspaper', adminOnly: false },
  { path: '/hotlists', label: '实时热点', icon: 'fa-fire', adminOnly: false },
  { path: '/fetch', label: '数据采集', icon: 'fa-satellite-dish', adminOnly: false },
  { path: '/chains', label: '逻辑链', icon: 'fa-diagram-project', adminOnly: false },
  { path: '/settings', label: '设置', icon: 'fa-sliders', adminOnly: true },
];

export default function NavSidebar() {
  const { user, logout } = useAuth();
  const isAdmin = user?.role === 'admin';
  const navItems = useMemo(() => ALL_ITEMS.filter(item => !item.adminOnly || isAdmin), [isAdmin]);

  return (
    <nav style={{
      width: 220,
      minWidth: 220,
      height: '100vh',
      background: 'var(--bg-secondary)',
      borderRight: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      padding: '16px 0',
      overflow: 'hidden',
    }}>
      {/* 品牌 */}
      <div style={{
        padding: '12px 20px 16px',
        fontSize: 16,
        fontWeight: 700,
        color: 'var(--accent)',
        marginBottom: 8,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        letterSpacing: '-0.3px',
      }}>
        <i className="fas fa-newspaper" style={{
          fontSize: 18,
          background: 'var(--gradient-primary)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
        }} />
        新闻知识聚合
      </div>

      {/* 用户信息 */}
      <div style={{
        padding: '10px 20px',
        fontSize: 12,
        color: 'var(--text-secondary)',
        borderBottom: '1px solid var(--border)',
        marginBottom: 8,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <span style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <i className="fas fa-circle" style={{
            fontSize: 6,
            color: 'var(--accent-tertiary)',
          }} />
          {user?.display_name || user?.username}
        </span>
        <span style={{
          color: 'var(--accent)',
          fontSize: 10,
          fontWeight: 600,
          textTransform: 'uppercase',
          background: 'rgba(0, 212, 255, 0.1)',
          padding: '2px 8px',
          borderRadius: 4,
          letterSpacing: '0.5px',
        }}>
          {user?.role || 'user'}
        </span>
      </div>

      {/* 导航项 */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {navItems.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '10px 20px',
              margin: '2px 10px',
              fontSize: 13,
              color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
              background: isActive ? 'rgba(0, 212, 255, 0.08)' : 'transparent',
              borderLeft: isActive ? '3px solid var(--accent)' : '3px solid transparent',
              borderRadius: '0 6px 6px 0',
              textDecoration: 'none',
              transition: 'all var(--transition-fast)',
              fontWeight: isActive ? 600 : 400,
            })}
            onMouseEnter={e => {
              if (!e.currentTarget.classList.contains('active')) {
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.03)';
                e.currentTarget.style.color = 'var(--text-primary)';
              }
            }}
            onMouseLeave={e => {
              if (!e.currentTarget.classList.contains('active')) {
                e.currentTarget.style.background = 'transparent';
                e.currentTarget.style.color = 'var(--text-secondary)';
              }
            }}
          >
            <i className={`fas ${item.icon}`} style={{
              width: 20,
              textAlign: 'center',
              fontSize: 14,
            }} />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </div>

      {/* 登出 */}
      <div style={{
        marginTop: 'auto',
        padding: '12px 20px',
        borderTop: '1px solid var(--border)',
      }}>
        <Button
          variant="ghost"
          size="sm"
          icon="fa-sign-out-alt"
          onClick={logout}
          style={{ width: '100%', justifyContent: 'flex-start' }}
        >
          退出登录
        </Button>
      </div>
    </nav>
  );
}
