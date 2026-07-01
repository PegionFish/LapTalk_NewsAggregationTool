"""
统一任务状态 API — 一个端点返回所有任务的进度状态。

任务类型列表基于 task_state 判断运行状态。
"""
from fastapi import APIRouter
from utils.task_state import task_state

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# 所有已知任务类型
TASK_TYPES = [
    'pipeline', 'article', 'event',
    'ai_filter', 'translate', 'clean', 'analyze',
    'keywords', 'classify', 'score',
    'recluster', 'summarize_events', 'build_chains', 'rank_events',
    'cache_fetch', 'batch_retry', 'hotlist_fetch', 'update',
]


@router.get("/status")
def get_all_tasks_status():
    """返回所有任务的进度状态。使用 task_state 判断运行状态。"""
    all_states = task_state.get_all_states()

    result = {}
    running_count = 0
    running_types = []
    for task_type in TASK_TYPES:
        state = all_states.get(task_type, {
            'status': 'idle', 'total': 0, 'done': 0, 'failed': 0,
            'current': '', 'log': [], 'error': '', 'extra': {},
        })
        is_running = state.get('status') == 'running'
        if is_running:
            running_count += 1
            running_types.append(task_type)
        result[task_type] = {
            'running': is_running,
            'status': state.get('status', 'idle'),
            'total': state.get('total', 0),
            'done': state.get('done', 0),
            'failed': state.get('failed', 0),
            'current': state.get('current', ''),
            'error': state.get('error', ''),
            'log': state.get('log', [])[-20:],
            'extra': state.get('extra', {}),
        }

    return {
        'tasks': result,
        'running_count': running_count,
        'running_types': running_types,
    }


@router.get("/active")
def get_active_tasks():
    """仅返回当前活跃任务（轻量查询）。"""
    all_states = task_state.get_all_states()
    active = {k: v for k, v in all_states.items() if v.get('status') == 'running'}
    return {
        'active': {k: {'started_at': v.get('created_at', '')} for k, v in active.items()},
        'count': len(active),
        'types': list(active.keys()),
    }


@router.get("/{task_type}")
def get_task_status(task_type: str):
    """获取单个任务状态。"""
    state = task_state.get_state(task_type)
    is_running = state.get('status') == 'running'
    return {
        'running': is_running,
        **state,
    }
