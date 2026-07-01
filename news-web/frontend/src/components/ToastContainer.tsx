import { useToast } from '../contexts/ToastContext';

const ICONS: Record<string, string> = {
  success: '✅',
  error: '❌',
  info: 'ℹ️',
};

const COLORS: Record<string, string> = {
  success: 'var(--accent-tertiary)',
  error: 'var(--accent-red)',
  info: 'var(--accent)',
};

export default function ToastContainer() {
  const { toasts, closeToast } = useToast();

  if (toasts.length === 0) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 20,
      right: 20,
      zIndex: 9999,
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      pointerEvents: 'none',
    }}>
      {toasts.map(toast => (
        <div
          key={toast.id}
          style={{
            pointerEvents: 'auto',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '12px 16px',
            background: 'rgba(30, 30, 30, 0.92)',
            backdropFilter: 'blur(8px)',
            border: `1px solid ${COLORS[toast.type]}33`,
            borderRadius: 8,
            color: '#fff',
            fontSize: 13,
            fontWeight: 500,
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            animation: toast.closing ? 'toastSlideOut 0.3s ease forwards' : 'toastSlideIn 0.3s ease',
            maxWidth: 360,
          }}
        >
          <span style={{ fontSize: 15, flexShrink: 0 }}>{ICONS[toast.type]}</span>
          <span style={{ flex: 1 }}>{toast.message}</span>
          <button
            onClick={() => closeToast(toast.id)}
            style={{
              background: 'none',
              border: 'none',
              color: 'rgba(255,255,255,0.5)',
              cursor: 'pointer',
              fontSize: 16,
              padding: '0 2px',
              lineHeight: 1,
              flexShrink: 0,
            }}
            onMouseEnter={e => (e.currentTarget.style.color = '#fff')}
            onMouseLeave={e => (e.currentTarget.style.color = 'rgba(255,255,255,0.5)')}
          >
            ×
          </button>
        </div>
      ))}
      <style>{`
        @keyframes toastSlideIn {
          from { opacity: 0; transform: translateX(100%); }
          to { opacity: 1; transform: translateX(0); }
        }
        @keyframes toastSlideOut {
          from { opacity: 1; transform: translateX(0); }
          to { opacity: 0; transform: translateX(100%); }
        }
      `}</style>
    </div>
  );
}
