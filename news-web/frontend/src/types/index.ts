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

export interface Stats {
  articles: number;
  events: number;
  active_events: number;
  human_verified: number;
  by_category: Record<string, number>;
}

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  limit: number;
  articles?: T[];
  events?: T[];
}
