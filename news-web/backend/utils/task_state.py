"""
任务状态持久化管理器 — DB 存储 + 内存缓存，支持刷新后恢复。

所有 AI/管道批量任务的状态统一存储到 SQLite，前端刷新后可恢复。
"""
import json, sqlite3, threading, logging
from datetime import datetime

logger = logging.getLogger(__name__)

LOG_MAX = 80


def _conn(db_path: str):
    return sqlite3.connect(db_path)


def ensure_task_states_table(db_path: str):
    """幂等创建 task_states 表。"""
    conn = _conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_states (
            task_type TEXT PRIMARY KEY,
            status TEXT DEFAULT 'idle',
            total INTEGER DEFAULT 0,
            done INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            current TEXT DEFAULT '',
            log TEXT DEFAULT '[]',
            extra TEXT DEFAULT '{}',
            error TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()


class TaskStateManager:
    """线程安全的任务状态管理器。"""

    def __init__(self, db_path: str = ''):
        self._db_path = db_path
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._loaded = False

    def set_db_path(self, path: str):
        self._db_path = path
        self._loaded = False

    def _ensure_db(self):
        if not self._loaded and self._db_path:
            ensure_task_states_table(self._db_path)
            self._load_from_db()
            self._loaded = True

    def _load_from_db(self):
        """从 DB 加载到内存缓存。"""
        try:
            conn = _conn(self._db_path)
            rows = conn.execute("SELECT * FROM task_states").fetchall()
            cols = [d[0] for d in conn.execute("PRAGMA table_info(task_states)").fetchall()]
            conn.close()
            for row in rows:
                d = dict(zip([c[1] for c in conn.execute("PRAGMA table_info(task_states)").fetchall()], row))
                task_type = d.pop('task_type', '')
                if task_type:
                    d['log'] = json.loads(d.get('log', '[]'))
                    d['extra'] = json.loads(d.get('extra', '{}'))
                    self._cache[task_type] = d
        except Exception as e:
            logger.warning(f"Failed to load task_states from DB: {e}")

    def _save_to_db(self, task_type: str, state: dict):
        """写入单条状态到 DB。"""
        if not self._db_path:
            return
        try:
            conn = _conn(self._db_path)
            log_json = json.dumps(state.get('log', []), ensure_ascii=False)
            extra_json = json.dumps(state.get('extra', {}), ensure_ascii=False)
            now = datetime.now().isoformat(timespec='seconds')
            conn.execute("""
                INSERT OR REPLACE INTO task_states
                    (task_type, status, total, done, failed, current, log, extra, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_type,
                state.get('status', 'idle'),
                state.get('total', 0),
                state.get('done', 0),
                state.get('failed', 0),
                state.get('current', ''),
                log_json,
                extra_json,
                state.get('error', ''),
                state.get('created_at', now),
                now,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to save task_state to DB: {e}")

    def init_state(self, task_type: str, total: int = 0, **extra) -> dict:
        """初始化任务状态并持久化。"""
        self._ensure_db()
        state = {
            'status': 'running',
            'total': total,
            'done': 0,
            'failed': 0,
            'current': '',
            'log': [],
            'error': '',
            'created_at': datetime.now().isoformat(timespec='seconds'),
            'extra': extra,
        }
        state['log'].append(f"[{state['created_at']}] Task started")
        with self._lock:
            self._cache[task_type] = state
            self._save_to_db(task_type, state)
        return state

    def update(self, task_type: str, **kwargs):
        """更新任务状态字段并持久化。"""
        self._ensure_db()
        with self._lock:
            if task_type not in self._cache:
                self._cache[task_type] = {'log': [], 'extra': {}}
            state = self._cache[task_type]
            for k, v in kwargs.items():
                if k == 'log_msg':
                    ts = datetime.now().strftime('%H:%M:%S')
                    state.setdefault('log', []).append(f"[{ts}] {v}")
                    if len(state['log']) > LOG_MAX:
                        state['log'] = state['log'][-LOG_MAX:]
                elif k == 'extra':
                    state.setdefault('extra', {}).update(v)
                else:
                    state[k] = v
            self._save_to_db(task_type, state)

    def finish(self, task_type: str, success: bool = True, error: str = ''):
        """标记任务完成并持久化。"""
        ts = datetime.now().isoformat(timespec='seconds')
        status = 'done' if success else 'failed'
        self.update(task_type, status=status, error=error, current='')
        self.update(task_type, log_msg=f"Task {status}" + (f": {error[:100]}" if error else ""))

    def get_state(self, task_type: str) -> dict:
        """获取任务状态（内存优先）。"""
        self._ensure_db()
        with self._lock:
            if task_type in self._cache:
                return dict(self._cache[task_type])
        return {
            'status': 'idle',
            'total': 0,
            'done': 0,
            'failed': 0,
            'current': '',
            'log': [],
            'error': '',
            'extra': {},
        }

    def get_all_states(self) -> dict[str, dict]:
        """获取所有任务状态。"""
        self._ensure_db()
        with self._lock:
            return {k: dict(v) for k, v in self._cache.items()}

    def clear(self, task_type: str):
        """清除任务状态。"""
        with self._lock:
            self._cache.pop(task_type, None)
        if self._db_path:
            try:
                conn = _conn(self._db_path)
                conn.execute("DELETE FROM task_states WHERE task_type=?", (task_type,))
                conn.commit()
                conn.close()
            except Exception:
                pass


# 全局单例
task_state = TaskStateManager()
