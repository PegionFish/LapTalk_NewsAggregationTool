import { NavLink } from 'react-router-dom';

const NAV_ITEMS = [
  { path: '/', label: '仪表盘', icon: '📊' },
  { path: '/workspace', label: '逻辑链工作台', icon: '🖱' },
  { path: '/articles', label: '文章检索', icon: '📄' },
  { path: '/chains', label: '逻辑链列表', icon: '📋' },
  { path: '/settings', label: '设置', icon: '⚙' },
];

export default function NavSidebar() {
  return (
    <nav style={{
      width: 200, height: '100vh', background: 'var(--bg-secondary)',
      borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', padding: '12px 0'
    }}>
      <div style={{ padding: '12px 16px', fontSize: 16, fontWeight: 'bold', color: 'var(--accent)', marginBottom: 8 }}>
        新闻知识聚合
      </div>
      {NAV_ITEMS.map(item => (
        <NavLink
          key={item.path}
          to={item.path}
          end={item.path === '/'}
          style={({ isActive }) => ({
            display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px',
            fontSize: 14, color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
            background: isActive ? 'rgba(79,195,247,0.1)' : 'transparent',
            borderLeft: isActive ? '3px solid var(--accent)' : '3px solid transparent',
            textDecoration: 'none',
          })}
        >
          <span>{item.icon}</span>
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
