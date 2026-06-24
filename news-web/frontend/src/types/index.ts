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
  content_status: string;  // 缓存状态: pending | fetched | translated | failed | dead
  content_fetched_at?: string;  // 内容抓取时间
  content_lang: string;   // 源语言: en / zh / ''
  ai_analyzed: boolean;   // AI 是否已完成内容分析
  human_processed: boolean; // 是否已人工处理
  has_translation: boolean; // 是否已有译文
  topic_category?: string; // 主题分类: 硬件/AI/游戏/移动/发布/其他
  local_path?: string;     // 缓存文件路径（含错误标记 [ERR:...]）
  retry_count?: number;    // 重试次数（死链判定用）
  event?: { id: number; title: string } | null;
}

export interface Comment {
  id: number;
  article_id: number;
  user_id: number;
  username: string;
  parent_id: number | null;
  content: string;
  rating: number | null;  // 0-100 百分制评分，null 表示未评分
  created_at: string;
  updated_at: string;
  like_count: number;
  liked_by_me: boolean;
  replies?: Comment[];
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
  by_source: Record<string, number>;  // 按实际媒体来源分布
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

export interface HotlistItem {
  id: number;
  title: string;
  url: string;
  source: string;
  rank: number;
  heat: string;
  author: string;
  fetched_at: string;
  priority_label: string;
  platform?: string;
}

export interface HotlistPlatform {
  count: number;
  items: HotlistItem[];
  date?: string;
}

export interface HotlistsSummary {
  date: string;
  platforms: Record<string, number>;
  total: number;
}

// ── 数据采集监控 ──────────────────────────────────────

export interface FetchOverview {
  rss: {
    total_sources: number;
    healthy: number;
    degraded: number;
    failing: number;
    last_run: string | null;
    articles_today: number;
    articles_yesterday: number;
  };
  hotlist: {
    total_sources: number;
    healthy: number;
    degraded: number;
    failing: number;
    last_run: string | null;
    articles_today: number;
    articles_yesterday: number;
  };
  cache: {
    total_articles: number;
    cached: number;
    pending: number;
    failed: number;
    cached_pct: number;
  };
}

export interface FetchSource {
  name: string;
  type: 'rss' | 'hotlist' | 'bilibili';
  health: 'healthy' | 'degraded' | 'failing';
  last_fetch: string | null;
  last_status: string;
  last_error: string;
  total_articles: number;
  cached_articles: number;
  failed_articles: number;
  success_rate_5: number;
}

export interface FetchLog {
  id?: number;
  source_name: string;
  source_type: string;
  articles_fetched: number;
  articles_new: number;
  status: string;
  error_msg: string;
  duration_ms: number;
  started_at: string;
  finished_at?: string;
  run_type: string;
}

export interface FetchArticleItem {
  id: number;
  title: string;
  url: string;
  source: string;
  content_status: string;
  local_path: string;
  content_fetched_at: string | null;
  content_lang: string;
  has_translation: boolean;
}

export interface FailedArticle {
  id: number;
  title: string;
  url: string;
  source: string;
  error: string;
  content_fetched_at: string | null;
}

export interface BatchRetryState {
  running: boolean;
  total: number;
  done: number;
  failed: number;
  skipped?: number;
  current: string;
  log: string[];
  started_at?: string;
  elapsed_seconds?: number;
  cancelled?: boolean;
}

// ── 调度管理 ──────────────────────────────────────────

export interface ScheduleSlot {
  hour: number;
  minute: number;
}

export interface ScheduleInfo {
  enabled: boolean;
  schedule: ScheduleSlot[];
  scheduler_running: boolean;
  last_run: string | null;
  last_status: string | null;
}

// ── 系统更新 ──────────────────────────────────────────

export interface UpdateVersion {
  version: string;
  build_time: string;
  python_version: string;
  platform: string;
}

export interface UpdateManifest {
  version: string;
  build_time: string;
  python_version?: string;
  backend_files: string[];
  frontend_files: string[];
}

export interface UpdateStatus {
  phase: string;
  message: string;
  manifest: UpdateManifest | null;
  progress: number;
  error: string;
  backup_path: string;
  log: string[];
}

export interface BackupInfo {
  name: string;
  path: string;
  version: string;
  created_at: string;
}

// ── 热搜/趋势（trending_items 表 — 微博/知乎/抖音/头条/B站等）──

export interface TrendingItem {
  id: number;
  title: string;
  platform: string;
  trend_type: string;
  url: string;
  rank: number;
  heat_score: number | null;
  video_desc: string;
  author: string;
  play_count: number | null;
  danmaku_count: number | null;
  cover_url: string;
  fetched_at: string;
  published_date: string;
  metadata: Record<string, unknown>;
  text_content: string;
}

export interface TrendingPlatform {
  platform: string;
  total: number;
  types: Record<string, number>;
  last_fetch: string;
}

// ── AI 入口级配置 ──────────────────────────────────────────

export interface AiEndpointConfig {
  enabled: boolean;
  base_url?: string;
  api_key?: string;
  model?: string;
  enable_thinking?: boolean;
  thinking_budget?: number;
  deep_thinking_max_tokens?: number;
  json_response_format?: boolean;
  target_lang?: string;
  max_tokens?: number;
  test_status?: string;
  test_reason?: string;
}

export interface AiEndpointTestResult {
  endpoint_key: string;
  ok: boolean | null;
  model?: string;
  response?: string;
  error?: string;
  reason?: string;
  skipped?: boolean;
  elapsed_ms?: number;
}

export interface AiEndpointTestResponse {
  ok: boolean;
  summary: {
    total: number;
    passed: number;
    failed: number;
    skipped: number;
  };
  results: AiEndpointTestResult[];
}

export interface AiSettingsResponse {
  ai_endpoints: Record<string, AiEndpointConfig>;
}
