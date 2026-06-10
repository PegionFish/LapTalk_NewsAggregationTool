import { useEffect, useState } from 'react';
import { getAuthHeaders } from '../../contexts/AuthContext';

interface UserInfo {
  id: number; username: string; display_name: string; role: string;
  created_at: string; last_login: string | null;
}

export default function AdminSettings() {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch('/api/auth/me', { headers: getAuthHeaders() })
      .then(r => r.json()).then(d => {
        if (d.user?.role === 'admin') { setIsAdmin(true); loadUsers(); }
      }).catch(() => {}).finally(() => setLoaded(true));
  }, []);

  const loadUsers = () => {
    fetch('/api/auth/users', { headers: getAuthHeaders() })
      .then(r => r.json()).then(d => setUsers(d.users || [])).catch(() => {});
  };

  const handleRoleChange = async (userId: number, role: string) => {
    await fetch(`/api/auth/users/${userId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ role }),
    });
    loadUsers();
  };

  const handleDeleteUser = async (userId: number) => {
    if (!confirm('确认删除该用户？此操作不可撤销。')) return;
    await fetch(`/api/auth/users/${userId}`, { method: 'DELETE', headers: getAuthHeaders() });
    loadUsers();
  };

  if (!loaded) return null;

  return (
    <div className="settings-container">
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-users-cog" /> 用户管理</h3>
          <p className="card-description">管理员可查看、修改角色、删除用户。仅 admin 角色可见此面板。</p>
        </div>
        <div className="card-body">
          {!isAdmin ? (
            <div className="empty-state">
              <i className="fas fa-lock" />
              <p>仅管理员可管理用户。当前账户角色不具备管理权限。</p>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>用户名</th>
                  <th>显示名</th>
                  <th>角色</th>
                  <th>创建时间</th>
                  <th>最后登录</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <tr key={u.id}>
                    <td><strong>{u.username}</strong></td>
                    <td>{u.display_name || '-'}</td>
                    <td>
                      <select className="form-select-sm" value={u.role}
                        onChange={e => handleRoleChange(u.id, e.target.value)}>
                        <option value="admin">admin</option>
                        <option value="user">user</option>
                        <option value="viewer">viewer</option>
                      </select>
                    </td>
                    <td className="text-secondary">{u.created_at?.slice(0, 10)}</td>
                    <td className="text-secondary">{u.last_login?.slice(0, 16).replace('T', ' ') || '从未登录'}</td>
                    <td>
                      <button className="btn btn-danger-sm" onClick={() => handleDeleteUser(u.id)}>
                        <i className="fas fa-trash-alt" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-info-circle" /> 角色说明</h3>
        </div>
        <div className="card-body">
          <div className="info-list">
            <div className="info-item"><i className="fas fa-crown" style={{ color: 'var(--accent)' }} /> <strong>admin</strong> — 全部权限：修改配置、管理用户、触发管道</div>
            <div className="info-item"><i className="fas fa-user" style={{ color: 'var(--text-secondary)' }} /> <strong>user</strong> — 标准权限：浏览文章、构建逻辑链、审核标注</div>
            <div className="info-item"><i className="fas fa-eye" style={{ color: 'var(--text-muted)' }} /> <strong>viewer</strong> — 只读权限：浏览文章和逻辑链，不可修改</div>
          </div>
        </div>
      </div>
    </div>
  );
}
