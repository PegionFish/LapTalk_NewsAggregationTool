import type { Article, Event, EventDetail, LogicChain, ChainDetail, ChainEvent, Stats, PaginatedResponse } from '../types';

const BASE = '/api';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => fetchJSON<{ status: string }>('/health'),

  getStats: () => fetchJSON<Stats>('/stats'),

  searchArticles: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v) qs.set(k, String(v)); });
    return fetchJSON<PaginatedResponse<Article>>(`/articles?${qs}`);
  },

  getArticle: (id: number) => fetchJSON<Article>(`/articles/${id}`),

  updateArticle: (id: number, data: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>(`/articles/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  getArticleContent: async (id: number) => {
    const res = await fetch(`${BASE}/articles/${id}/content`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json() as Promise<{ url: string; content: string; translation: string; lang: string; status: string; source: string; ai_summary?: string; ai_analyzed?: boolean; human_processed?: boolean }>;
  },

  analyzeArticle: (id: number) =>
    fetchJSON<{ ok: boolean; cached: boolean; analysis: string }>(`/articles/${id}/analyze`, { method: 'POST' }),

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
    pipeline_schedule_enabled?: boolean;
    translation_enabled?: boolean; translation_base_url?: string;
    translation_api_key?: string; translation_model?: string;
    translation_target_lang?: string; content_cache_path?: string;
  }>('/settings'),

  updateSettings: (data: Record<string, string | boolean>) =>
    fetchJSON<{ db_path: string; user_agent: string }>('/settings', { method: 'PUT', body: JSON.stringify(data) }),

  triggerPipeline: () => fetchJSON<{ status: string }>('/pipeline/run', { method: 'POST' }),

  getPipelineStatus: () => fetchJSON<{ running: boolean; last_run: string | null; last_status: string | null; current_step: string | null; steps: { name: string; status: string; duration_ms: number }[] }>('/pipeline/status'),

  // 批量 AI 处理
  startBatchTranslate: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-translate', { method: 'POST' }),
  getBatchTranslateStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string }>('/pipeline/batch-translate/status'),

  startBatchAnalyze: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/batch-analyze', { method: 'POST' }),
  getBatchAnalyzeStatus: () => fetchJSON<{ running: boolean; total: number; done: number; failed: number; current: string }>('/pipeline/batch-analyze/status'),

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
};
