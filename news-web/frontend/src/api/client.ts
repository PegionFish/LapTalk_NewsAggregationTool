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
    return res.text();
  },

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

  createRelation: (from: number, to: number, relation: string) =>
    fetchJSON<{ ok: boolean }>('/relations', { method: 'POST', body: JSON.stringify({ from_event_id: from, to_event_id: to, relation }) }),

  getSettings: () => fetchJSON<{ db_path: string; user_agent: string; openai_base_url?: string; openai_api_key?: string; openai_model?: string; pipeline_schedule_enabled?: boolean }>('/settings'),

  updateSettings: (data: Record<string, string | boolean>) =>
    fetchJSON<{ db_path: string; user_agent: string }>('/settings', { method: 'PUT', body: JSON.stringify(data) }),

  triggerPipeline: () => fetchJSON<{ status: string }>('/pipeline/run', { method: 'POST' }),

  getPipelineStatus: () => fetchJSON<{ running: boolean; last_run: string | null; last_status: string | null; current_step: string | null; steps: { name: string; status: string; duration_ms: number }[] }>('/pipeline/status'),
};
