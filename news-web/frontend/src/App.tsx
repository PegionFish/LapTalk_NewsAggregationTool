import { Component, type ReactNode } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import NavSidebar from './components/NavSidebar';
import Dashboard from './pages/Dashboard';
import Workspace from './pages/Workspace';
import ArticleSearch from './pages/ArticleSearch';
import ChainList from './pages/ChainList';
import Settings from './pages/Settings';
import Login from './pages/Login';

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
      <main style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/articles" element={<ArticleSearch />} />
          <Route path="/chains" element={<ChainList />} />
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
