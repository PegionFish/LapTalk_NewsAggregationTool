import { useCallback } from 'react';
import type { Article } from '../types';

interface Props {
  article: Article;
  onSelect?: (article: Article) => void;
}

export default function ArticleBlock({ article, onSelect }: Props) {
  const handleClick = useCallback(() => {
    if (onSelect) {
      onSelect(article);
    } else if (article.url) {
      window.open(article.url, '_blank', 'noopener');
    }
  }, [article, onSelect]);

  return (
    <div
      draggable
      onClick={handleClick}
      title="点击打开原文"
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
