/**
 * HTML 实体解码工具 — 将 &#8217; 等实体还原为真实字符。
 * 使用 textarea + innerHTML 双重回退，兼容所有浏览器环境。
 */

let _ta: HTMLTextAreaElement | null = null;
let _div: HTMLDivElement | null = null;

export function decodeHTMLEntities(text: string): string {
  if (!text) return text;
  // 包含 &# 才需要解码，跳过无实体的字符串
  if (!text.includes('&#')) return text;

  try {
    if (!_ta) {
      _ta = document.createElement('textarea');
    }
    _ta.innerHTML = text;
    return _ta.value;
  } catch {
    try {
      if (!_div) {
        _div = document.createElement('div');
      }
      _div.textContent = text;
      return _div.textContent || text;
    } catch {
      return text;
    }
  }
}
