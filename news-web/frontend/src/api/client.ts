import type { Article, Event, EventDetail, LogicChain, ChainDetail, ChainEvent, Stats, PaginatedResponse, Comment } from '../types';
import { getAuthHeaders } from '../contexts/AuthContext';

const BASE = '/api';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders(), ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => fetchJSON<{ status: string }>('/health'),

  getStats: () => fetchJSON<Stats>('/stats'),

  searchArticles: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v) qs.set(k, String(v)); });
    return fetchJSON<PaginatedResponse<Article>>(`/news?${qs}`);
  },

  getArticle: (id: number) => fetchJSON<Article>(`/news/${id}`),

  updateArticle: (id: number, data: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>(`/news/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  getArticleContent: async (id: number) => {
    const res = await fetch(`${BASE}/news/${id}/content`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json() as Promise<{ url: string; content: string; translation: string; lang: string; status: string; source: string; ai_summary?: string; ai_analyzed?: boolean; human_processed?: boolean; has_pdf?: boolean }>;
  },

  cacheArticleHtml: (id: number, html: string) =>
    fetchJSON<{ ok: boolean; local_path: string }>(`/news/${id}/cache-html`, {
      method: 'POST', body: JSON.stringify({ html }),
    }),

  getArticlePdfUrl: (id: number) => `/api/news/${id}/pdf`,

  cacheArticlePdf: (id: number, pdfBase64: string) =>
    fetchJSON<{ ok: boolean; pdf_path: string }>(`/news/${id}/cache-pdf`, {
      method: 'POST', body: JSON.stringify({ pdf_base64: pdfBase64 }),
    }),

  // ── 浏览器指纹 ──────────────────────────────────────────
  setBrowserFingerprint: (fp: {
    userAgent: string; platform: string; language: string; languages: string[];
    deviceMemory: number | null; hardwareConcurrency: number;
    screenWidth: number; screenHeight: number; colorDepth: number;
    pixelRatio: number; timezone: string; cookiesEnabled: boolean;
  }) => fetchJSON<{ ok: boolean }>('/browser/fingerprint', {
    method: 'POST', body: JSON.stringify(fp),
  }),

  getBrowserFingerprint: () =>
    fetchJSON<{ ok: boolean; fingerprint: Record<string, unknown> }>('/browser/fingerprint'),

  retryPlaywrightCapture: (articleId: number) =>
    fetchJSON<{ ok: boolean; source?: string; error?: string }>(
      `/browser/retry-playwright/${articleId}`, { method: 'POST' }
    ),

  analyzeArticle: (id: number) =>
    fetchJSON<{ ok: boolean; cached: boolean; analysis: string }>(`/news/${id}/analyze`, { method: 'POST' }),

  // ── AI 内容清洗 ──────────────────────────────────────
  getCleanedContent: (id: number) =>
    fetchJSON<{ cleaned: string; cached: boolean; source: string }>(`/news/${id}/cleaned-content`),

  // ── 主题分类 ──────────────────────────────────────────
  getTopicCategories: () =>
    fetchJSON<{ categories: Record<string, number> }>('/news/categories'),

  populateTopicCategories: () =>
    fetchJSON<{ ok: boolean; updated: number; categories: Record<string, number> }>(
      '/news/categories/populate', { method: 'POST' }
    ),

  // ── 低分新闻清理 ──────────────────────────────────────
  previewCleanup: (threshold: number) =>
    fetchJSON<{ count: number; threshold: number }>(`/news/cleanup/preview?threshold=${threshold}`),

  executeCleanup: (threshold: number) =>
    fetchJSON<{ deleted: number; threshold: number; would_delete: number }>(
      '/news/cleanup', { method: 'POST', body: JSON.stringify({ threshold }) }
    ),

  // ── 文章评语 + 点赞 ──────────────────────────────────
  getArticleComments: (articleId: number) =>
    fetchJSON<{ comments: Comment[] }>(`/news/${articleId}/comments`),

  addArticleComment: (articleId: number, content: string, parentId?: number, rating?: number) =>
    fetchJSON<Comment>(`/news/${articleId}/comments`, {
      method: 'POST',
      body: JSON.stringify({ content, parent_id: parentId ?? null, rating: rating ?? null }),
    }),

  editComment: (id: number, content: string, rating?: number) =>
    fetchJSON<{ ok: boolean }>(`/comments/${id}`, {
      method: 'PATCH', body: JSON.stringify({ content, rating: rating ?? null }),
    }),

  deleteComment: (id: number) =>
    fetchJSON<{ ok: boolean }>(`/comments/${id}`, { method: 'DELETE' }),

  toggleCommentLike: (id: number) =>
    fetchJSON<{ liked: boolean; count: number }>(`/comments/${id}/like`, { method: 'POST' }),

  listEvents: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v) qs.set(k, String(v)); });
    return fetchJSON<PaginatedResponse<Event>>(`/events?${qs}`);
  },

  getEvent: (id: number) => fetchJSON<EventDetail>(`/events/${id}`),

  updateEvent: (id: number, data: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>(`/events/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  mergeEvents: (id: number, targetId: number) =>
    fetchJSON<{ ok: boolean }>(`/events/${id}/merge`, { method: 'POST', body: JSON.stringify({ target_event_id: targetId }) }),

  splitEvent: (id: number, articleIds: number[], newTitle?: string) =>
    fetchJSON<{ ok: boolean; new_event_id: number }>(`/events/${id}/split`, {
      method: 'POST', body: JSON.stringify({ article_ids: articleIds, new_event_title: newTitle })
    }),

  listChains: () => fetchJSON<{ chains: LogicChain[] }>('/chains'),

  getChain: (id: number) => fetchJSON<ChainDetail>(`/chains/${id}`),

  getChainTimeline: (id: number) => fetchJSON<{ chain_id: number; chain_title: string; timeline: ChainEvent[]; total_events: number }>(`/chains/${id}/timeline`),

  createChain: (data: { title: string; description?: string; event_ids?: number[] }) =>
    fetchJSON<{ id: number; title: string }>('/chains', { method: 'POST', body: JSON.stringify(data) }),

  updateChain: (id: number, data: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>(`/chains/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  deleteChain: (id: number) =>
    fetchJSON<{ ok: boolean }>(`/chains/${id}`, { method: 'DELETE' }),

  spliceChains: (id: number, childIds: number[]) =>
    fetchJSON<{ ok: boolean }>(`/chains/${id}/splice`, { method: 'POST', body: JSON.stringify({ child_chain_ids: childIds }) }),

  splitChain: (id: number, atEventId: number, newTitle?: string) =>
    fetchJSON<{ ok: boolean; new_chain_id: number }>(`/chains/${id}/split`, {
      method: 'POST', body: JSON.stringify({ at_event_id: atEventId, new_title: newTitle || '' })
    }),

  reorderChain: (id: number, eventIds: number[]) =>
    fetchJSON<{ ok: boolean }>(`/chains/${id}/reorder`, { method: 'POST', body: JSON.stringify({ event_ids: eventIds }) }),

  getSuggestedRelations: () => fetchJSON<{ suggestions: unknown[] }>('/relations/suggested'),

  confirmRelation: (id: number) =>
    fetchJSON<{ ok: boolean }>(`/relations/${id}/confirm`, { method: 'POST' }),

  rejectRelation: (id: number) =>
    fetchJSON<{ ok: boolean }>(`/relations/${id}`, { method: 'DELETE' }),

  getRelationsBetween: (eventIds: number[]) => {
    const qs = eventIds.join(',');
    return fetchJSON<{ relations: { id: number; from_event_id: number; to_event_id: number; relation: string; from_title: string; to_title: string; created_by: string }[] }>(`/relations/between?event_ids=${qs}`);
  },

  createRelation: (from: number, to: number, relation: string) =>
    fetchJSON<{ ok: boolean }>('/relations', { method: 'POST', body: JSON.stringify({ from_event_id: from, to_event_id: to, relation }) }),

  getSettings: () => fetchJSON<{
    db_path: string; user_agent: string;
    openai_base_url?: string; openai_api_key?: string; openai_model?: string;
    ai_enable_thinking?: boolean; ai_thinking_budget?: number;
    ai_deep_thinking_max_tokens?: number; ai_json_response_format?: boolean;
    pipeline_schedule_enabled?: boolean;
    translation_enabled?: boolean; translation_base_url?: string;
    translation_api_key?: string; translation_model?: string;
    translation_target_lang?: string; content_cache_path?: string;
    proxy_enabled?: boolean; proxy_url?: string;
  }>('/settings'),

  updateSettings: (data: Record<string, string | number | boolean>) =>
    fetchJSON<{ db_path: string; user_agent: string }>('/settings', { method: 'PUT', body: JSON.stringify(data) }),

  triggerPipeline: () => fetchJSON<{ status: string }>('/pipeline/run', { method: 'POST' }),

  getPipelineStatus: () => fetchJSON<{ running: boolean; last_run: string | null; last_status: string | null; current_step: string | null; steps: { name: string; status: string; duration_ms: number }[] }>('/pipeline/status'),

  // 批量 AI 处理
  startBatchTranslate: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-translate', { method: 'POST' }),
  getBatchTranslateStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string }>('/pipeline/batch-translate/status'),
  cancelBatchTranslate: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/batch-translate/cancel', { method: 'POST' }),
  forceResetBatchTranslate: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/batch-translate/force-reset', { method: 'POST' }),

  startBatchAnalyze: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-analyze', { method: 'POST' }),
  getBatchAnalyzeStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string }>('/pipeline/batch-analyze/status'),
  cancelBatchAnalyze: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/batch-analyze/cancel', { method: 'POST' }),
  forceResetBatchAnalyze: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/batch-analyze/force-reset', { method: 'POST' }),

  startBatchClean: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-clean', { method: 'POST' }),
  getBatchCleanStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string; log: string[] }>('/pipeline/batch-clean/status'),
  cancelBatchClean: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/batch-clean/cancel', { method: 'POST' }),
  forceResetBatchClean: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/batch-clean/force-reset', { method: 'POST' }),

  startBuildChains: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/build-chains', { method: 'POST' }),
  getBuildChainsStatus: () => fetchJSON<{ running: boolean; total_groups: number; chains_created: number; current: string }>('/pipeline/build-chains/status'),

  // AI 接管批量端点
  startBatchKeywords: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-keywords', { method: 'POST' }),
  getBatchKeywordsStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string; log: string[] }>('/pipeline/batch-keywords/status'),
  startBatchClassify: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-classify', { method: 'POST' }),
  getBatchClassifyStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string; log: string[] }>('/pipeline/batch-classify/status'),
  startBatchScore: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-score', { method: 'POST' }),
  getBatchScoreStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string; log: string[] }>('/pipeline/batch-score/status'),
  startBatchRankEvents: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/batch-rank-events', { method: 'POST' }),
  getBatchRankEventsStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string; log: string[] }>('/pipeline/batch-rank-events/status'),
  startBatchRecluster: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-recluster', { method: 'POST' }),
  getBatchReclusterStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string; log: string[] }>('/pipeline/batch-recluster/status'),
  startBatchSummarizeEvents: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-summarize-events', { method: 'POST' }),
  getBatchSummarizeEventsStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string; log: string[] }>('/pipeline/batch-summarize-events/status'),

  startBatchAiFull: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/batch-ai-full', { method: 'POST' }),
  getBatchAiFullStatus: () => fetchJSON<{ running: boolean; total: number; done: number; current: string; log: string[] }>('/pipeline/batch-ai-full/status'),
  cancelBatchAiFull: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/batch-ai-full/cancel', { method: 'POST' }),
  forceResetBatchAiFull: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/batch-ai-full/force-reset', { method: 'POST' }),

  startBatchAiFilter: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-ai-filter', { method: 'POST' }),
  getBatchAiFilterStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string; log: string[] }>('/pipeline/batch-ai-filter/status'),

  getNotifications: (params: { limit?: number; unread_only?: boolean } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.unread_only) qs.set('unread_only', 'true');
    return fetchJSON<{ notifications: { id: number; type: string; title: string; body: string; entity_type: string; entity_id: number; read: boolean; created_at: string }[]; unread_count: number }>(`/notifications?${qs}`);
  },

  markNotifRead: (id: number) =>
    fetchJSON<{ ok: boolean }>(`/notifications/${id}/read`, { method: 'POST' }),

  markAllNotifsRead: () =>
    fetchJSON<{ ok: boolean }>('/notifications/read-all', { method: 'POST' }),

  getNotifPrefs: () =>
    fetchJSON<{ email: string; digest_enabled: boolean; review_reminders: boolean; event_updates: boolean }>('/notifications/prefs'),

  updateNotifPrefs: (data: Record<string, string | boolean>) =>
    fetchJSON<{ ok: boolean }>('/notifications/prefs', { method: 'PUT', body: JSON.stringify(data) }),

  // AI API 连通性测试
  testAi: () => fetchJSON<{ ok: boolean; response?: string; error?: string; model?: string }>('/settings/test-ai', { method: 'POST' }),

  testTranslation: () => fetchJSON<{ ok: boolean; original?: string; translation?: string; error?: string; model?: string }>('/settings/test-translation', { method: 'POST' }),

  testProxy: () => fetchJSON<{ ok: boolean; message?: string; error?: string; elapsed_ms?: number; proxy_url?: string }>('/settings/test-proxy', { method: 'POST' }),

  // ── 实时热点 ──────────────────────────────────────────
  getHotlists: (params?: { date?: string; platform?: string }) => {
    const qs = new URLSearchParams();
    if (params?.date) qs.set('date', params.date);
    if (params?.platform) qs.set('platform', params.platform);
    const query = qs.toString();
    return fetchJSON<Record<string, { count: number; items: import('../types').HotlistItem[]; date?: string }>>(
      `/hotlists${query ? `?${query}` : ''}`
    );
  },
  getHotlistsSummary: (date?: string) => {
    const qs = date ? `?date=${encodeURIComponent(date)}` : '';
    return fetchJSON<import('../types').HotlistsSummary>(`/hotlists/summary${qs}`);
  },
  getHotlistsTop: (limit = 50, date?: string) => {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (date) qs.set('date', date);
    return fetchJSON<{ total: number; items: import('../types').HotlistItem[] }>(`/hotlists/top?${qs}`);
  },
  getHotlistsLive: () =>
    fetchJSON<{ status: string; data: Record<string, { count: number; items: import('../types').HotlistItem[] }> | null }>('/hotlists/live'),
  startLiveFetch: () =>
    fetchJSON<{ ok: boolean; message?: string }>('/hotlists/live/fetch', { method: 'POST' }),

  // ── 热搜趋势 API（独立表 trending_items — 微博/知乎/抖音/头条/B站）──
  fetchTrending: (params: {
    platform?: string; trend_type?: string; date_from?: string; date_to?: string;
    q?: string; page?: number; limit?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.platform) qs.set('platform', params.platform);
    if (params.trend_type) qs.set('trend_type', params.trend_type);
    if (params.date_from) qs.set('date_from', params.date_from);
    if (params.date_to) qs.set('date_to', params.date_to);
    if (params.q) qs.set('q', params.q);
    if (params.page) qs.set('page', String(params.page));
    if (params.limit) qs.set('limit', String(params.limit));
    const query = qs.toString();
    return fetchJSON<{ items: import('../types').TrendingItem[]; total: number; page: number; limit: number }>(
      `/trending${query ? `?${query}` : ''}`
    );
  },

  fetchTrendingItem: (id: number) =>
    fetchJSON<import('../types').TrendingItem>(`/trending/${id}`),

  fetchTrendingPlatforms: () =>
    fetchJSON<{ platforms: import('../types').TrendingPlatform[] }>('/trending/platforms'),

  // ── 数据采集监控 ────────────────────────────────────
  getFetchOverview: () =>
    fetchJSON<import('../types').FetchOverview>('/fetch/overview'),

  getFetchSources: (sourceType?: string) => {
    const qs = sourceType ? `?source_type=${encodeURIComponent(sourceType)}` : '';
    return fetchJSON<{ sources: import('../types').FetchSource[] }>(`/fetch/sources${qs}`);
  },

  getFetchSourceHistory: (name: string, days = 7) =>
    fetchJSON<{ source: string; days: number; history: import('../types').FetchLog[] }>(
      `/fetch/sources/${encodeURIComponent(name)}/history?days=${days}`
    ),

  retryFetchSource: (name: string) =>
    fetchJSON<{ ok: boolean; message: string }>(
      `/fetch/sources/${encodeURIComponent(name)}/retry`, { method: 'POST' }
    ),

  getFetchSourceArticles: (name: string, params: { page?: number; limit?: number; status?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.page) qs.set('page', String(params.page));
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.status) qs.set('status', params.status);
    const query = qs.toString();
    return fetchJSON<{ total: number; page: number; limit: number; source: string; articles: import('../types').FetchArticleItem[] }>(
      `/fetch/sources/${encodeURIComponent(name)}/articles${query ? `?${query}` : ''}`
    );
  },

  retryArticleCache: (id: number) =>
    fetchJSON<{ ok: boolean; message: string }>(`/fetch/articles/${id}/retry-cache`, { method: 'POST' }),

  retryArticlesBatch: (idsOrOptions: number[] | { retry_all: boolean }) =>
    fetchJSON<{ ok: boolean; total: number; message: string }>(
      '/fetch/articles/batch-retry', {
        method: 'POST',
        body: JSON.stringify(
          Array.isArray(idsOrOptions) ? { ids: idsOrOptions } : idsOrOptions
        )
      }
    ),

  getBatchRetryStatus: () =>
    fetchJSON<import('../types').BatchRetryState>('/fetch/articles/batch-retry/status'),

  cancelBatchRetry: () =>
    fetchJSON<{ ok: boolean; message: string }>('/fetch/articles/batch-retry/cancel', { method: 'POST' }),

  recoverDeadLinks: (idsOrOptions: number[] | { retry_all: boolean }) =>
    fetchJSON<{ ok: boolean; total: number; message: string }>(
      '/news/recover-dead', {
        method: 'POST',
        body: JSON.stringify(
          Array.isArray(idsOrOptions) ? { ids: idsOrOptions } : idsOrOptions
        )
      }
    ),

  getRecoverDeadStatus: () =>
    fetchJSON<import('../types').BatchRetryState>('/news/recover-dead/status'),

  getFailedArticles: (page = 1, limit = 50) =>
    fetchJSON<{ total: number; page: number; limit: number; articles: import('../types').FailedArticle[] }>(
      `/fetch/articles/failed?page=${page}&limit=${limit}`
    ),

  getFetchLogs: (limit = 50) =>
    fetchJSON<{ logs: import('../types').FetchLog[] }>(`/fetch/logs?limit=${limit}`),

  // ── 调度管理 ──────────────────────────────────────────
  getSchedule: () =>
    fetchJSON<import('../types').ScheduleInfo>('/fetch/schedule'),

  updateSchedule: (data: { enabled?: boolean; hours?: number[]; minutes?: number[] }) =>
    fetchJSON<import('../types').ScheduleInfo>('/fetch/schedule', { method: 'PUT', body: JSON.stringify(data) }),

  toggleSchedule: (enabled: boolean) =>
    fetchJSON<{ ok: boolean; enabled: boolean; message: string }>('/fetch/schedule/toggle', {
      method: 'POST', body: JSON.stringify({ enabled })
    }),

  getScheduleLogs: (limit = 50) =>
    fetchJSON<{ logs: string[] }>(`/fetch/schedule/logs?limit=${limit}`),

  // ── 缓存管理 ──────────────────────────────────────────
  getCacheStatus: () =>
    fetchJSON<{
      checked_at: string; cache_dir: string;
      summary: { total_articles: number; with_url: number; cached_db: number; cached_disk: number;
        missing_disk: number; orphan_files: number; with_text: number; with_translation: number;
        pending_download: number; failed_download: number; en_articles: number; };
      recent: { id: number; title: string; source: string; fetched_at: string }[];
      missing_on_disk: number[]; orphan_files: number[];
      uncached_articles: { id: number; title: string; source: string }[];
      uncached_count: number;
    }>('/cache/status'),

  startCacheFetch: () =>
    fetchJSON<{ ok: boolean; message?: string }>('/cache/fetch/start', { method: 'POST' }),

  getCacheFetchStatus: () =>
    fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string; log: string[] }>('/cache/fetch/status'),

  // ── 系统更新 ──────────────────────────────────────────
  getUpdateVersion: () =>
    fetchJSON<{ version: string; build_time: string; python_version: string; platform: string }>('/update/current-version'),

  getUpdateStatus: () =>
    fetchJSON<{ phase: string; message: string; manifest: any; progress: number; error: string; backup_path: string; log: string[] }>('/update/status'),

  uploadUpdatePackage: async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE}/update/upload`, { method: 'POST', body: formData });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    return res.json() as Promise<{ ok: boolean; filename: string; manifest: any; current_version: string }>;
  },

  applyUpdate: (filename: string, skipBackup = false) =>
    fetchJSON<{ ok: boolean; message: string }>('/update/apply', {
      method: 'POST', body: JSON.stringify({ filename, skip_backup: skipBackup })
    }),

  rollbackUpdate: (backupName: string) =>
    fetchJSON<{ ok: boolean; message: string }>('/update/rollback', {
      method: 'POST', body: JSON.stringify({ backup_name: backupName })
    }),

  listBackups: () =>
    fetchJSON<{ backups: { name: string; path: string; version: string; created_at: string }[] }>('/update/backups'),

  // ── 统一任务状态 ──────────────────────────────────────
  getAllTasksStatus: () =>
    fetchJSON<{ tasks: Record<string, { running: boolean; status: string; total: number; done: number; failed: number; current: string; error: string; log: string[]; extra: Record<string, unknown>; level: number }>; running_count: number; running_types: string[] }>('/tasks/status'),

  getActiveTasks: () =>
    fetchJSON<{ active: Record<string, { started_at: string; task_id: string }>; count: number; types: string[] }>('/tasks/active'),

  getTaskStatus: (taskType: string) =>
    fetchJSON<{ running: boolean; status: string; total: number; done: number; failed: number; current: string; log: string[] }>(`/tasks/${taskType}`),
};
