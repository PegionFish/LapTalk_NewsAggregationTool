import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { Comment } from '../types';
import { useAuth } from '../contexts/AuthContext';

/**
 * 文章评语面板 — 树形评语 + 点赞 + 回复/编辑/删除。
 * 挂载于 ArticleSearch 右侧详情面板底部。
 */
export default function CommentPanel({ articleId }: { articleId: number }) {
  const { user } = useAuth();
  const [comments, setComments] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState('');
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [replyDraft, setReplyDraft] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getArticleComments(articleId);
      setComments(res.comments || []);
    } catch { setComments([]); }
    setLoading(false);
  }, [articleId]);

  useEffect(() => { load(); }, [load]);

  const handleSubmit = async () => {
    const text = draft.trim();
    if (!text) return;
    setSubmitting(true);
    try {
      await api.addArticleComment(articleId, text);
      setDraft('');
      await load();
    } catch (e) {
      alert('发布失败: ' + (e as Error).message);
    }
    setSubmitting(false);
  };

  const handleReply = async (parentId: number) => {
    const text = replyDraft.trim();
    if (!text) return;
    setSubmitting(true);
    try {
      await api.addArticleComment(articleId, text, parentId);
      setReplyDraft('');
      setReplyTo(null);
      await load();
    } catch (e) {
      alert('回复失败: ' + (e as Error).message);
    }
    setSubmitting(false);
  };

  const handleLike = async (commentId: number) => {
    try {
      const res = await api.toggleCommentLike(commentId);
      // 本地更新，避免整列表重载
      setComments(prev => updateLike(prev, commentId, res.liked, res.count));
    } catch { /* ignore */ }
  };

  const handleDelete = async (commentId: number) => {
    if (!confirm('确定删除这条评语？回复会一并删除。')) return;
    try {
      await api.deleteComment(commentId);
      await load();
    } catch (e) {
      alert('删除失败: ' + (e as Error).message);
    }
  };

  const handleEditSave = async (commentId: number) => {
    const text = editDraft.trim();
    if (!text) return;
    try {
      await api.editComment(commentId, text);
      setEditingId(null);
      await load();
    } catch (e) {
      alert('编辑失败: ' + (e as Error).message);
    }
  };

  const total = countAll(comments);

  return (
    <div>
      {/* 标题 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '8px 0 10px' }}>
        <i className="fas fa-comments" style={{ color: 'var(--accent)', fontSize: 12 }} />
        <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 600 }}>
          审核评语 {total > 0 && <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>· {total}</span>}
        </span>
      </div>

      {/* 输入区 */}
      <div style={{ marginBottom: 12 }}>
        <textarea
          value={draft}
          onChange={e => setDraft(e.target.value)}
          placeholder={user ? '写下你的审核评语...' : '请先登录后再发表评语'}
          disabled={!user || submitting}
          rows={2}
          style={{
            width: '100%',
            padding: '8px 10px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            color: 'var(--text-primary)',
            fontSize: 12,
            lineHeight: 1.6,
            resize: 'vertical',
            fontFamily: 'inherit',
            outline: 'none',
          }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {user ? `以「${user.display_name || user.username}」发布` : '未登录'}
          </span>
          <button
            onClick={handleSubmit}
            disabled={!user || !draft.trim() || submitting}
            style={{
              padding: '4px 12px',
              fontSize: 12,
              borderRadius: 6,
              border: 'none',
              background: user && draft.trim() ? 'var(--accent)' : 'var(--bg-card)',
              color: user && draft.trim() ? '#fff' : 'var(--text-muted)',
              cursor: user && draft.trim() && !submitting ? 'pointer' : 'not-allowed',
            }}
          >
            {submitting ? <i className="fas fa-spinner fa-spin" /> : '发布'}
          </button>
        </div>
      </div>

      {/* 评语列表 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 16, color: 'var(--text-muted)', fontSize: 12 }}>
          <i className="fas fa-spinner fa-spin" /> 加载中...
        </div>
      ) : comments.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 16, color: 'var(--text-muted)', fontSize: 12 }}>
          暂无评语，快来抢沙发
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {comments.map(c => (
            <CommentItem
              key={c.id}
              comment={c}
              depth={0}
              currentUserId={user?.id}
              onLike={handleLike}
              onReply={(id) => { setReplyTo(id); setReplyDraft(''); }}
              onDelete={handleDelete}
              onEdit={(c) => { setEditingId(c.id); setEditDraft(c.content); }}
              replyTo={replyTo}
              replyDraft={replyDraft}
              setReplyDraft={setReplyDraft}
              onReplySubmit={handleReply}
              onCancelReply={() => setReplyTo(null)}
              submitting={submitting}
              editingId={editingId}
              editDraft={editDraft}
              setEditDraft={setEditDraft}
              onEditSave={handleEditSave}
              onCancelEdit={() => setEditingId(null)}
              canReply={!!user}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── 单条评语（递归渲染回复）──────────────────────────────
interface ItemProps {
  comment: Comment;
  depth: number;
  currentUserId?: number;
  onLike: (id: number) => void;
  onReply: (id: number) => void;
  onDelete: (id: number) => void;
  onEdit: (c: Comment) => void;
  replyTo: number | null;
  replyDraft: string;
  setReplyDraft: (v: string) => void;
  onReplySubmit: (id: number) => void;
  onCancelReply: () => void;
  submitting: boolean;
  editingId: number | null;
  editDraft: string;
  setEditDraft: (v: string) => void;
  onEditSave: (id: number) => void;
  onCancelEdit: () => void;
  canReply: boolean;
}

function CommentItem(props: ItemProps) {
  const { comment: c, depth, currentUserId } = props;
  const isMine = currentUserId === c.user_id;
  const indent = Math.min(depth, 3) * 16;

  return (
    <div style={{ marginLeft: indent }}>
      <div style={{
        padding: '8px 10px',
        background: 'var(--bg-card)',
        borderRadius: 8,
        border: '1px solid var(--border)',
      }}>
        {/* 头部 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <i className="fas fa-user-circle" style={{ color: 'var(--accent)', fontSize: 11 }} />
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>
            {c.username}
            {isMine && <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>（我）</span>}
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            {formatTime(c.created_at)}
          </span>
          {c.updated_at !== c.created_at && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>· 已编辑</span>
          )}
        </div>

        {/* 内容 / 编辑框 */}
        {props.editingId === c.id ? (
          <div style={{ marginTop: 4 }}>
            <textarea
              value={props.editDraft}
              onChange={e => props.setEditDraft(e.target.value)}
              rows={2}
              style={textareaStyle}
            />
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <MiniBtn onClick={() => props.onEditSave(c.id)} primary>保存</MiniBtn>
              <MiniBtn onClick={props.onCancelEdit}>取消</MiniBtn>
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 12, lineHeight: 1.6, color: 'var(--text-primary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {c.content}
          </div>
        )}

        {/* 操作栏 */}
        {props.editingId !== c.id && (
          <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 11 }}>
            <ActionBtn
              active={c.liked_by_me}
              onClick={() => props.onLike(c.id)}
              activeIcon="fa-thumbs-up"
              icon="far fa-thumbs-up"
            >
              {c.like_count > 0 ? c.like_count : '赞'}
            </ActionBtn>
            {props.canReply && depth < 3 && (
              <ActionBtn onClick={() => props.onReply(c.id)} icon="far fa-comment">
                回复
              </ActionBtn>
            )}
            {isMine && (
              <>
                <ActionBtn onClick={() => props.onEdit(c)} icon="far fa-edit">编辑</ActionBtn>
                <ActionBtn onClick={() => props.onDelete(c.id)} icon="far fa-trash-alt" danger>删除</ActionBtn>
              </>
            )}
          </div>
        )}

        {/* 回复输入框 */}
        {props.replyTo === c.id && (
          <div style={{ marginTop: 8 }}>
            <textarea
              value={props.replyDraft}
              onChange={e => props.setReplyDraft(e.target.value)}
              placeholder={`回复 @${c.username}...`}
              rows={2}
              style={textareaStyle}
              autoFocus
            />
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <MiniBtn
                onClick={() => props.onReplySubmit(c.id)}
                primary
                disabled={!props.replyDraft.trim() || props.submitting}
              >
                回复
              </MiniBtn>
              <MiniBtn onClick={props.onCancelReply}>取消</MiniBtn>
            </div>
          </div>
        )}
      </div>

      {/* 递归渲染回复 */}
      {c.replies && c.replies.length > 0 && (
        c.replies.map(r => <CommentItem key={r.id} {...props} comment={r} depth={depth + 1} />)
      )}
    </div>
  );
}

// ── 子组件 ──────────────────────────────────────────────

const textareaStyle: React.CSSProperties = {
  width: '100%',
  padding: '6px 8px',
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontSize: 12,
  lineHeight: 1.5,
  resize: 'vertical',
  fontFamily: 'inherit',
  outline: 'none',
};

function ActionBtn({ children, onClick, icon, active, activeIcon, danger }: {
  children: React.ReactNode;
  onClick: () => void;
  icon?: string;
  active?: boolean;
  activeIcon?: string;
  danger?: boolean;
}) {
  const color = danger ? 'var(--accent-red)' : active ? 'var(--accent)' : 'var(--text-muted)';
  return (
    <button
      onClick={onClick}
      style={{
        background: 'none',
        border: 'none',
        color,
        cursor: 'pointer',
        fontSize: 11,
        padding: 0,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 3,
      }}
      onMouseEnter={e => { e.currentTarget.style.opacity = '0.8'; }}
      onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
    >
      <i className={active && activeIcon ? `fas ${activeIcon}` : (icon || 'far fa-comment')} />
      {children}
    </button>
  );
}

function MiniBtn({ children, onClick, primary, disabled }: {
  children: React.ReactNode;
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '2px 10px',
        fontSize: 11,
        borderRadius: 4,
        border: 'none',
        background: primary && !disabled ? 'var(--accent)' : 'var(--bg-primary)',
        color: primary && !disabled ? '#fff' : 'var(--text-secondary)',
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      {children}
    </button>
  );
}

// ── 工具函数 ────────────────────────────────────────────

function countAll(list: Comment[]): number {
  return list.reduce((sum, c) => sum + 1 + (c.replies ? countAll(c.replies) : 0), 0);
}

function updateLike(list: Comment[], id: number, liked: boolean, count: number): Comment[] {
  return list.map(c => {
    if (c.id === id) return { ...c, liked_by_me: liked, like_count: count };
    if (c.replies) return { ...c, replies: updateLike(c.replies, id, liked, count) };
    return c;
  });
}

function formatTime(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diff = (now.getTime() - d.getTime()) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  if (diff < 2592000) return `${Math.floor(diff / 86400)}天前`;
  return iso.slice(0, 10);
}
