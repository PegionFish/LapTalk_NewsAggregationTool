import { useMemo } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const ALL_ITEMS = [
  { path: '/', label: '仪表盘', icon: 'fa-chart-pie', adminOnly: false },
  { path: '/workspace', label: '逻辑链工作台', icon: 'fa-diagram-project', adminOnly: false },
  { path: '/articles', label: '文章检索', icon: 'fa-newspaper', adminOnly: false },
  { path: '/chains', label: '逻辑链列表', icon: 'fa-list-check', adminOnly: false },
  { path: '/settings', label: '设置', icon: 'fa-sliders', adminOnly: true },
];

export default function NavSidebar() {
  const { user, logout } = useAuth();
  const isAdmin = user?.role === 'admin';
  const navItems = useMemo(() => ALL_ITEMS.filter(item => !item.adminOnly || isAdmin), [isAdmin]);

  return (
    <nav style={{
      width: 200, minWidth: 200, height: '100vh', background: 'var(--bg-secondary)',
      borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', padding: '12px 0',
      overflow: 'hidden',
    }}>
      {/* 品牌 */}
      <div style={{
        padding: '12px 16px', fontSize: 15, fontWeight: 700, color: 'var(--accent)',
        marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <i className="fas fa-newspaper" style={{ fontSize: 16, background: 'var(--gradient-primary)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }} />
        新闻知识聚合
      </div>

      {/* 用户信息 */}
      <div style={{
        padding: '8px 16px', fontSize: 12, color: 'var(--text-secondary)',
        borderBottom: '1px solid var(--border)', marginBottom: 4,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          <i className="fas fa-circle" style={{ fontSize: 6, color: 'var(--accent-tertiary)', marginRight: 6, verticalAlign: 'middle' }} />
          {user?.display_name || user?.username}
        </span>
        <span style={{
          color: 'var(--accent)', fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
          background: 'rgba(0,212,255,0.1)', padding: '1px 6px', borderRadius: 3,
        }}>
          {user?.role || 'user'}
        </span>
      </div>

      {/* 导航项 */}
      {navItems.map(item => (
        <NavLink
          key={item.path}
          to={item.path}
          end={item.path === '/'}
          style={({ isActive }) => ({
            display: 'flex', alignItems: 'center', gap: 10, padding: '9px 16px', margin: '2px 8px',
            fontSize: 13, color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
            background: isActive ? 'rgba(0,212,255,0.08)' : 'transparent',
            borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
            borderRadius: '0 4px 4px 0',
            textDecoration: 'none', transition: 'var(--transition-fast)',
            fontWeight: isActive ? 600 : 400,
          })}
        >
          <i className={`fas ${item.icon}`} style={{ width: 18, textAlign: 'center', fontSize: 13 }} />
          <span>{item.label}</span>
        </NavLink>
      ))}

      {/* 登出 */}
      <div style={{ marginTop: 'auto', padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
        <button onClick={logout} style={{
          width: '100%', background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)',
          borderRadius: 6, padding: '7px 12px', color: 'var(--text-secondary)', fontSize: 12,
          cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
          transition: 'var(--transition-fast)',
        }}>
          <i className="fas fa-sign-out-alt" style={{ fontSize: 12 }} />
          退出登录
        </button>
      </div>
    </nav>
  );
}
