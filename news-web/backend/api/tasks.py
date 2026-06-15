"""
统一任务状态 API — 一个端点返回所有任务的锁状态和进度。

前端只需轮询这一个端点即可获取所有任务的真实状态。
"""
from fastapi import APIRouter
from utils.task_lock import task_lock, TASK_LEVELS
from utils.task_state import task_state

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/status")
def get_all_tasks_status():
    """返回所有任务的锁状态、进度和日志。"""
    active = task_lock.get_active()
    all_states = task_state.get_all_states()

    result = {}
    for task_type, level in TASK_LEVELS.items():
        state = all_states.get(task_type, {
            'status': 'idle', 'total': 0, 'done': 0, 'failed': 0,
            'current': '', 'log': [], 'error': '', 'extra': {},
        })
        is_running = task_type in active
        result[task_type] = {
            'running': is_running,
            'status': state.get('status', 'idle'),
            'total': state.get('total', 0),
            'done': state.get('done', 0),
            'failed': state.get('failed', 0),
            'current': state.get('current', ''),
            'error': state.get('error', ''),
            'log': state.get('log', [])[-20:],  # 最后 20 条
            'extra': state.get('extra', {}),
            'level': level,
        }

    return {
        'tasks': result,
        'running_count': len(active),
        'running_types': list(active.keys()),
    }


@router.get("/active")
def get_active_tasks():
    """仅返回当前活跃任务（轻量查询）。"""
    active = task_lock.get_active()
    return {
        'active': active,
        'count': len(active),
        'types': list(active.keys()),
    }


@router.get("/{task_type}")
def get_task_status(task_type: str):
    """获取单个任务状态。"""
    state = task_state.get_state(task_type)
    is_running = task_type in task_lock.get_active()
    return {
        'running': is_running,
        **state,
    }
