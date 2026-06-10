export interface Article {
  id: number;
  title: string;
  source: string;
  url: string;
  published: string;
  fetched: string;
  score: number;
  label: string;
  verified: number;
  keywords: string[];
  human_tags: string[];
  category?: string;
  content_status: string;  // 缓存状态: pending | fetched | translated | failed
  content_fetched_at?: string;  // 内容抓取时间
  ai_analyzed?: boolean;  // AI 是否已完成内容分析
  human_processed?: boolean;  // 是否已人工处理（保护评分/关键词不被AI覆写）
  event?: { id: number; title: string } | null;
}

export interface Event {
  id: number;
  title: string;
  first_seen: string;
  last_seen: string;
  article_count: number;
  status: string;
}

export interface EventDetail extends Event {
  articles: Article[];
  relations: {
    outgoing: Relation[];
    incoming: Relation[];
  };
}

export interface Relation {
  id: number;
  target_id?: number;
  source_id?: number;
  relation: string;
  target_title?: string;
  source_title?: string;
  target_first?: string;
  target_last?: string;
}

export interface LogicChain {
  id: number;
  title: string;
  description: string;
  created_at: string;
  updated_at: string;
  created_by: string;
  event_count?: number;
}

export interface ChainDetail extends LogicChain {
  events: ChainEvent[];
  sub_chains: { id: number; title: string; position: number }[];
}

export interface ChainEvent {
  id: number;
  title: string;
  first_seen: string;
  last_seen: string;
  article_count: number;
  position: number;
  note: string;
}

export interface ArticleContent {
  url: string;
  content: string;
  translation: string;
  lang: string;
  status: string;
  source: 'local' | 'remote';
}

export interface Stats {
  articles: number;
  events: number;
  active_events: number;
  human_verified: number;
  by_category: Record<string, number>;
  cache_cached: number;      // 已缓存 HTML (local_path 有效)
  cache_text: number;        // 文本已提取 (text_content)
  cache_translated: number;  // 翻译已完成
  cache_pending: number;     // 待下载
  cache_failed: number;      // 下载失败
}

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  limit: number;
  articles?: T[];
  events?: T[];
}
