import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

export type ToastType = 'success' | 'error' | 'info';

export interface Toast {
  id: number;
  message: string;
  type: ToastType;
  closing: boolean;
}

interface ToastContextValue {
  showToast: (message: string, type?: ToastType) => void;
  toasts: Toast[];
  closeToast: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue>({} as ToastContextValue);

let nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const closeToast = useCallback((id: number) => {
    setToasts(prev => prev.map(t => t.id === id ? { ...t, closing: true } : t));
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 300);
  }, []);

  const showToast = useCallback((message: string, type: ToastType = 'success') => {
    const id = nextId++;
    setToasts(prev => [...prev, { id, message, type, closing: false }]);
    setTimeout(() => closeToast(id), 3500);
  }, [closeToast]);

  return (
    <ToastContext.Provider value={{ showToast, toasts, closeToast }}>
      {children}
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
