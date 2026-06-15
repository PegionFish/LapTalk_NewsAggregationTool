"""
系统更新 API — 上传更新包、校验、安装、重启。

参考 OpenWRT 升级 UI 设计:
  1. 上传 → 校验 manifest → 展示变更
  2. 确认 → 备份 → 安装 → 重启
"""
import os, json, tarfile, shutil, subprocess, threading, logging
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from config import config

router = APIRouter(prefix="/api/update", tags=["update"])
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = ROOT / 'news-web' / 'backend'
FRONTEND_DIR = ROOT / 'news-web' / 'frontend'
VERSION_FILE = ROOT / 'VERSION'
UPLOAD_DIR = ROOT / 'dist' / 'uploads'
BACKUP_DIR = ROOT / 'backups'

# 更新状态（内存）
_update_state = {
    'phase': 'idle',        # idle | uploaded | validating | installing | restarting | done | error
    'message': '',
    'manifest': None,
    'progress': 0,
    'error': '',
    'backup_path': '',
    'log': [],
}
_update_lock = threading.Lock()


def _add_log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    _update_state['log'].append(f"[{ts}] {msg}")
    if len(_update_state['log']) > 100:
        _update_state['log'] = _update_state['log'][-100:]


def _get_current_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return '0.0.0'


# ══════════════════════════════════════════════════════════════
# 当前版本信息
# ══════════════════════════════════════════════════════════════

@router.get("/current-version")
def get_current_version():
    """获取当前运行版本信息。"""
    version = _get_current_version()
    return {
        'version': version,
        'build_time': _get_build_time(),
        'python_version': _get_python_version(),
        'platform': _get_platform(),
    }


@router.get("/status")
def get_update_status():
    """获取更新状态。"""
    return dict(_update_state)


# ══════════════════════════════════════════════════════════════
# 上传更新包
# ══════════════════════════════════════════════════════════════

@router.post("/upload")
async def upload_update_package(file: UploadFile = File(...)):
    """上传更新包 (.tar.gz)。"""
    if not file.filename or not file.filename.endswith('.tar.gz'):
        raise HTTPException(400, "请上传 .tar.gz 格式的更新包")

    with _update_lock:
        _update_state['phase'] = 'uploaded'
        _update_state['error'] = ''
        _update_state['log'] = []
        _update_state['manifest'] = None

    # 确保上传目录存在
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_path = UPLOAD_DIR / file.filename

    try:
        content = await file.read()
        upload_path.write_bytes(content)
        _add_log(f"上传完成: {file.filename} ({len(content) / 1024:.1f} KB)")
    except Exception as e:
        _update_state['phase'] = 'error'
        _update_state['error'] = f"上传失败: {str(e)}"
        raise HTTPException(500, f"文件保存失败: {str(e)}")

    # 解压并校验 manifest
    try:
        _update_state['phase'] = 'validating'
        manifest = _validate_package(upload_path)
        _update_state['manifest'] = manifest
        _add_log(f"校验通过: v{manifest['version']}, 后端 {len(manifest.get('backend_files', []))} 文件, 前端 {len(manifest.get('frontend_files', []))} 文件")

        return {
            'ok': True,
            'filename': file.filename,
            'manifest': manifest,
            'current_version': _get_current_version(),
        }
    except Exception as e:
        _update_state['phase'] = 'error'
        _update_state['error'] = str(e)
        _add_log(f"校验失败: {str(e)}")
        raise HTTPException(400, f"更新包校验失败: {str(e)}")


# ══════════════════════════════════════════════════════════════
# 应用更新
# ══════════════════════════════════════════════════════════════

class ApplyRequest(BaseModel):
    filename: str
    skip_backup: bool = False


@router.post("/apply")
def apply_update(body: ApplyRequest):
    """应用已上传的更新包 — 备份 + 安装 + 重启。"""
    with _update_lock:
        if _update_state['phase'] in ('installing', 'restarting'):
            raise HTTPException(409, "更新正在进行中")

    upload_path = UPLOAD_DIR / body.filename
    if not upload_path.exists():
        raise HTTPException(404, f"更新包不存在: {body.filename}")

    # 后台执行更新
    threading.Thread(
        target=_do_apply_update,
        args=(upload_path, body.skip_backup),
        daemon=True,
    ).start()

    return {'ok': True, 'message': '更新已开始，请勿关闭页面'}


# ══════════════════════════════════════════════════════════════
# 回滚
# ══════════════════════════════════════════════════════════════

@router.get("/backups")
def list_backups():
    """列出可用备份。"""
    backups = []
    if BACKUP_DIR.exists():
        for d in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if d.is_dir() and d.name.startswith('update-'):
                meta_file = d / 'meta.json'
                meta = {}
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text())
                    except Exception:
                        pass
                backups.append({
                    'name': d.name,
                    'path': str(d),
                    'version': meta.get('version', 'unknown'),
                    'created_at': meta.get('created_at', ''),
                })
    return {'backups': backups}


@router.post("/rollback")
def rollback_update(body: dict):
    """回滚到指定备份。"""
    backup_name = body.get('backup_name', '')
    if not backup_name:
        raise HTTPException(400, "请指定备份名称")

    backup_path = BACKUP_DIR / backup_name
    if not backup_path.exists():
        raise HTTPException(404, f"备份不存在: {backup_name}")

    threading.Thread(
        target=_do_rollback,
        args=(backup_path,),
        daemon=True,
    ).start()

    return {'ok': True, 'message': '回滚已开始'}


# ══════════════════════════════════════════════════════════════
# 内部逻辑
# ══════════════════════════════════════════════════════════════

def _validate_package(tar_path: Path) -> dict:
    """校验更新包，返回 manifest。"""
    if not tar_path.exists():
        raise FileNotFoundError(f"更新包不存在: {tar_path}")

    try:
        with tarfile.open(str(tar_path), 'r:gz') as tar:
            # 查找 manifest.json
            manifest_member = None
            for member in tar.getmembers():
                if member.name.endswith('manifest.json'):
                    manifest_member = member
                    break

            if not manifest_member:
                raise ValueError("更新包缺少 manifest.json")

            manifest_file = tar.extractfile(manifest_member)
            if not manifest_file:
                raise ValueError("无法读取 manifest.json")

            manifest = json.loads(manifest_file.read().decode('utf-8'))

            # 校验必要字段
            required = ['version', 'build_time', 'backend_files']
            for field in required:
                if field not in manifest:
                    raise ValueError(f"manifest.json 缺少字段: {field}")

            # 检查关键文件是否存在
            member_names = {m.name for m in tar.getmembers()}
            critical_files = ['scripts/install.sh', 'scripts/restart.sh']
            for cf in critical_files:
                found = any(cf in name for name in member_names)
                if not found:
                    raise ValueError(f"更新包缺少关键文件: {cf}")

            return manifest
    except tarfile.TarError as e:
        raise ValueError(f"更新包格式错误: {str(e)}")


def _do_apply_update(tar_path: Path, skip_backup: bool):
    """后台执行更新。"""
    global _update_state

    with _update_lock:
        _update_state['phase'] = 'installing'
        _update_state['progress'] = 0
        _update_state['error'] = ''

    try:
        # 1. 备份
        if not skip_backup:
            _add_log("创建备份...")
            backup_path = _create_backup()
            _update_state['backup_path'] = str(backup_path)
            _update_state['progress'] = 20
            _add_log(f"备份完成: {backup_path}")
        else:
            _add_log("跳过备份")

        # 2. 解压
        _add_log("解压更新包...")
        _update_state['progress'] = 30
        temp_dir = ROOT / 'dist' / '_update_temp'
        if temp_dir.exists():
            shutil.rmtree(str(temp_dir))

        with tarfile.open(str(tar_path), 'r:gz') as tar:
            tar.extractall(str(temp_dir))

        # 找到解压后的根目录
        pkg_dir = None
        for d in temp_dir.iterdir():
            if d.is_dir() and 'laptalk-update' in d.name:
                pkg_dir = d
                break
        if not pkg_dir:
            pkg_dir = temp_dir

        # 3. 更新后端
        _add_log("更新后端文件...")
        _update_state['progress'] = 50
        backend_src = pkg_dir / 'backend'
        if backend_src.exists():
            # 更新 Python 文件
            for item in backend_src.iterdir():
                if item.is_file() and item.suffix == '.py':
                    shutil.copy2(str(item), str(BACKEND_DIR / item.name))
                elif item.is_dir() and item.name in ('api', 'auth', 'db', 'pipeline', 'utils'):
                    dest = BACKEND_DIR / item.name
                    dest.mkdir(exist_ok=True)
                    for sub in item.rglob('*'):
                        if sub.is_file():
                            sub_dest = dest / sub.relative_to(item)
                            sub_dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(sub), str(sub_dest))

        # 4. 更新前端
        _add_log("更新前端文件...")
        _update_state['progress'] = 70
        frontend_src = pkg_dir / 'frontend' / 'dist'
        if frontend_src.exists():
            frontend_dest = FRONTEND_DIR / 'dist'
            if frontend_dest.exists():
                shutil.rmtree(str(frontend_dest))
            shutil.copytree(str(frontend_src), str(frontend_dest))

        # 5. 更新版本文件
        manifest_path = pkg_dir / 'manifest.json'
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            VERSION_FILE.write_text(manifest.get('version', _get_current_version()))

        # 6. 清理
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        _update_state['progress'] = 90

        # 7. 重启
        _add_log("准备重启服务...")
        _update_state['phase'] = 'restarting'
        _update_state['progress'] = 95

        # 执行重启
        _restart_service()

        _update_state['phase'] = 'done'
        _update_state['progress'] = 100
        _add_log("更新完成，服务已重启")

    except Exception as e:
        _update_state['phase'] = 'error'
        _update_state['error'] = str(e)
        _add_log(f"更新失败: {str(e)}")
        logger.exception(f"Update failed: {e}")


def _create_backup() -> Path:
    """创建当前文件备份。"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    backup_path = BACKUP_DIR / f'update-{timestamp}'
    backup_path.mkdir(parents=True, exist_ok=True)

    # 备份后端
    backend_backup = backup_path / 'backend'
    backend_backup.mkdir()
    for item in BACKEND_DIR.iterdir():
        if item.is_file() and item.suffix == '.py':
            shutil.copy2(str(item), str(backend_backup / item.name))
        elif item.is_dir() and item.name in ('api', 'auth', 'db', 'pipeline', 'utils'):
            shutil.copytree(str(item), str(backend_backup / item.name))

    # 备份前端
    frontend_backup = backup_path / 'frontend'
    frontend_backup.mkdir()
    dist = FRONTEND_DIR / 'dist'
    if dist.exists():
        shutil.copytree(str(dist), str(frontend_backup / 'dist'))

    # 写入元数据
    meta = {
        'version': _get_current_version(),
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'files': sum(1 for _ in backup_path.rglob('*') if _.is_file()),
    }
    (backup_path / 'meta.json').write_text(json.dumps(meta, indent=2))

    return backup_path


def _restart_service():
    """重启后端服务。"""
    import time
    pid_dir = ROOT / 'pids'
    pid_file = pid_dir / 'backend.pid'

    # 尝试停止旧进程
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            os.kill(old_pid, 15)  # SIGTERM
            time.sleep(2)
            try:
                os.kill(old_pid, 9)  # SIGKILL if still alive
            except OSError:
                pass
        except (ValueError, OSError):
            pass
        pid_file.unlink(missing_ok=True)

    # 通过端口查找残留进程
    try:
        import subprocess
        result = subprocess.run(
            ['netstat', '-ano'], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if ':8081 ' in line and 'LISTENING' in line:
                pid = line.split()[-1]
                try:
                    os.kill(int(pid), 9)
                except (ValueError, OSError):
                    pass
    except Exception:
        pass

    # 启动新进程
    pid_dir.mkdir(exist_ok=True)
    backend_dir = BACKEND_DIR
    log_dir = ROOT / 'logs'
    log_dir.mkdir(exist_ok=True)

    proc = subprocess.Popen(
        ['python', 'main.py'],
        cwd=str(backend_dir),
        stdout=open(log_dir / 'backend.log', 'a'),
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    pid_file.write_text(str(proc.pid))
    _add_log(f"新进程已启动 (PID: {proc.pid})")


def _do_rollback(backup_path: Path):
    """回滚到指定备份。"""
    global _update_state

    with _update_lock:
        _update_state['phase'] = 'installing'
        _update_state['progress'] = 0
        _update_state['error'] = ''

    try:
        _add_log(f"开始回滚到: {backup_path.name}")

        # 回滚后端
        backend_src = backup_path / 'backend'
        if backend_src.exists():
            _add_log("恢复后端文件...")
            for item in backend_src.iterdir():
                if item.is_file() and item.suffix == '.py':
                    shutil.copy2(str(item), str(BACKEND_DIR / item.name))
                elif item.is_dir() and item.name in ('api', 'auth', 'db', 'pipeline', 'utils'):
                    dest = BACKEND_DIR / item.name
                    if dest.exists():
                        shutil.rmtree(str(dest))
                    shutil.copytree(str(item), str(dest))

        # 回滚前端
        frontend_src = backup_path / 'frontend' / 'dist'
        if frontend_src.exists():
            _add_log("恢复前端文件...")
            frontend_dest = FRONTEND_DIR / 'dist'
            if frontend_dest.exists():
                shutil.rmtree(str(frontend_dest))
            shutil.copytree(str(frontend_src), str(frontend_dest))

        _update_state['progress'] = 90
        _add_log("准备重启服务...")
        _update_state['phase'] = 'restarting'

        _restart_service()

        _update_state['phase'] = 'done'
        _update_state['progress'] = 100
        _add_log("回滚完成，服务已重启")

    except Exception as e:
        _update_state['phase'] = 'error'
        _update_state['error'] = str(e)
        _add_log(f"回滚失败: {str(e)}")


# ── 工具函数 ──────────────────────────────────────────────

def _get_build_time() -> str:
    if VERSION_FILE.exists():
        mtime = VERSION_FILE.stat().st_mtime
        return datetime.fromtimestamp(mtime).isoformat(timespec='seconds')
    return ''


def _get_python_version() -> str:
    return sys.version.split()[0]


def _get_platform() -> str:
    import platform
    return f"{platform.system()} {platform.release()}"


import sys
