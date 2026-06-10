import type { Dispatch, SetStateAction } from 'react';

interface Props {
  cachePath: string; setCachePath: Dispatch<SetStateAction<string>>;
}

export default function CacheSettings({ cachePath, setCachePath }: Props) {
  return (
    <div className="settings-container">
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-archive" /> 内容缓存</h3>
          <p className="card-description">下载的文章 HTML 文件和提取的文本存放目录 — 留空则为数据库同级的 content/ 目录</p>
        </div>
        <div className="card-body">
          <div className="form-group">
            <label className="form-label"><i className="fas fa-folder" /> 缓存目录</label>
            <input className="form-control" value={cachePath} onChange={e => setCachePath(e.target.value)}
              placeholder="留空自动推导 (backend/data/content)" />
            <div className="form-text">
              <i className="fas fa-info-circle" /> 每个文章保存为 <code>{'{id}'}.html</code>。提取后的文本存储在数据库 text_content 列。
            </div>
          </div>
        </div>
      </div>

      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-info-circle" /> 缓存策略</h3>
        </div>
        <div className="card-body">
          <div className="info-list">
            <div className="info-item"><i className="fas fa-layer-group" /> 三级读取：DB 文本缓存 → 磁盘 HTML → 代理获取</div>
            <div className="info-item"><i className="fas fa-download" /> 管道步骤 3 自动下载新文章内容</div>
            <div className="info-item"><i className="fas fa-language" /> 英文文章自动检测并触发翻译（如翻译已启用）</div>
            <div className="info-item"><i className="fas fa-check-circle" /> 原文和译文独立存储，对照阅读不覆盖</div>
          </div>
        </div>
      </div>
    </div>
  );
}
