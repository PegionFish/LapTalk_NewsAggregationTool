import { useEffect, useRef } from 'react';
import { api } from '../api/client';

const COLLECTED_KEY = 'fingerprint_collected';

/**
 * 收集浏览器真实指纹，发送到后端供 Playwright 隐身使用。
 * 仅在应用启动时执行一次。
 */
export default function useBrowserFingerprint() {
  const sentRef = useRef(false);

  useEffect(() => {
    if (sentRef.current) return;
    sentRef.current = true;

    const fp = {
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      language: navigator.language,
      languages: navigator.languages as string[],
      deviceMemory: (navigator as any).deviceMemory ?? null,
      hardwareConcurrency: navigator.hardwareConcurrency || 8,
      screenWidth: screen.width,
      screenHeight: screen.height,
      colorDepth: screen.colorDepth,
      pixelRatio: window.devicePixelRatio || 1,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      cookiesEnabled: navigator.cookieEnabled,
    };

    api.setBrowserFingerprint(fp).then(r => {
      if (r.ok) {
        sessionStorage.setItem(COLLECTED_KEY, '1');
      }
    }).catch(() => {
      // 静默失败，不影响应用运行
    });
  }, []);
}
