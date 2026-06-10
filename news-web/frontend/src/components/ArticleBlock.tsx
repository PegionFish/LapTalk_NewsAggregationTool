import type { Article } from '../types';
import { useNavigate } from 'react-router-dom';

interface Props {
  article: Article;
  onSelect?: (article: Article) => void;
}

export default function ArticleBlock({ article, onSelect }: Props) {
  const navigate = useNavigate();
  const readerUrl = `/articles/${article.id}`;

  return (
    <div
      draggable
      onClick={() => { if (onSelect) { onSelect(article); } else { navigate(readerUrl); } }}
      title="点击阅读全文（本地缓存优先）"
      onDragStart={(e) => {
        e.dataTransfer.setData('application/json', JSON.stringify({ type: 'article', article }));
      }}
      style={{
        background: 'var(--bg-card)', padding: '6px 10px', borderRadius: 6, fontSize: 12,
        cursor: 'pointer', borderLeft: '3px solid var(--accent)',
        marginBottom: 4,
      }}
    >
      <div style={{ fontWeight: 'bold', fontSize: 12, marginBottom: 2 }}>{article.title.slice(0, 60)}</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: 10 }}>
        <span>{article.source}</span>
        <span>{article.fetched?.slice(5, 10)}</span>
      </div>
    </div>
  );
}
