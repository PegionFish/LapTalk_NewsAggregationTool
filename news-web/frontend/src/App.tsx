import { Component, type ReactNode, useEffect } from 'react';
import { Routes, Route, Navigate, useParams, useSearchParams } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import NavSidebar from './components/NavSidebar';
import Dashboard from './pages/Dashboard';
import Workspace from './pages/Workspace';
import ArticleSearch from './pages/ArticleSearch';
import ChainList from './pages/ChainList';
import Settings from './pages/Settings';
import Login from './pages/Login';
import ArticleReader from './pages/ArticleReader';

// ── Workspace 路由适配器 — 将 /chains/:chainId 转为 Workspace 可识别的 search params ──
function WorkspaceRoute() {
  const { chainId } = useParams<{ chainId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    if (chainId && chainId !== 'new' && !searchParams.get('chain')) {
      setSearchParams({ chain: chainId }, { replace: true });
    }
  }, [chainId]); // eslint-disable-line react-hooks/exhaustive-deps

  return <Workspace key={chainId || 'new'} />;
}

// ── Error Boundary ────────────────────────────────────────
class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean; error: Error | null }> {
  state = { hasError: false, error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', gap: 16 }}>
          <h2 style={{ color: 'var(--accent-red)' }}>页面出现异常</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{this.state.error?.message}</p>
          <button onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload(); }}
            style={{ background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '10px 24px', color: '#000', fontWeight: 'bold', cursor: 'pointer' }}>
            重新加载
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Authenticated App ─────────────────────────────────────
function AuthedApp() {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--text-secondary)' }}>加载中...</div>;
  }

  if (!isAuthenticated) {
    return <Login />;
  }

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <NavSidebar />
      <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          {/* 逻辑链 — /chains 列表, /chains/new 新建工作台, /chains/:id 编辑 */}
          <Route path="/chains" element={<ChainList />} />
          <Route path="/chains/new" element={<WorkspaceRoute />} />
          <Route path="/chains/:chainId" element={<WorkspaceRoute />} />
          {/* 旧路由兼容 */}
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/articles/:id" element={<ArticleReader />} />
          <Route path="/articles" element={<ArticleSearch />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

// ── Root App ──────────────────────────────────────────────
export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <AuthedApp />
      </AuthProvider>
    </ErrorBoundary>
  );
}
