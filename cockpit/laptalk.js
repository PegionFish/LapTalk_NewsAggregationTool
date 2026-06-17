/*
 * LapTalk Cockpit 插件 — 前端逻辑
 *
 * 三个核心模块：
 *   - Service   : 调用 start_platform.sh 的 start/stop/restart/status
 *   - Config    : 通过后端 HTTP API 读写定时调度（GET/PUT /api/fetch/schedule）
 *   - LogView   : 实时 tail 后端日志
 *
 * 调用方式：
 *   - shell 命令 → cockpit.spawn（以当前登录 Cockpit 的用户身份执行）
 *   - 后端 API  → fetch http://localhost:8081（CORS 已全开）
 *   - 日志      → cockpit.spawn(["tail","-n",N,"-f",logPath])
 *
 * 页面卸载时必须 close 所有 spawn channel，否则会泄漏。
 */

'use strict';

/* ════════════════════════════════════════════════
 * 全局配置（由 index.html 的注入脚本提供）
 * ════════════════════════════════════════════════ */
const HOME       = window.LAPTALK_HOME     || "/opt/LapTalk_NewsAggregationTool";
const API_BASE   = window.LAPTALK_API_BASE || "http://localhost:8081";
const LOG_PATH   = window.LAPTALK_LOG_PATH || (HOME + "/logs/backend.log");
const SCRIPT     = window.LAPTALK_SCRIPT   || (HOME + "/start_platform.sh");

/* 所有 spawn 调用的公共选项 */
const SPAWN_OPTS = {
    directory: HOME,
    superuser: "try",     // 不强制 root；非特权也能跑（端口 8081 > 1024）
    err: "message"        // 失败时把 stderr 拼进 err.message
};

/* ════════════════════════════════════════════════
 * 工具函数
 * ════════════════════════════════════════════════ */
const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

/** 简易 toast 通知（3 秒后自动消失） */
function toast(msg, kind) {
    const el = $('#toast');
    el.textContent = msg;
    el.className = 'laptalk-toast' + (kind ? ' laptalk-toast-' + kind : '');
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 3000);
}

/** 把"逗号/空格分隔的数字字符串"解析为 int 数组，校验范围 */
function parseCronList(text, min, max, label) {
    const parts = String(text).split(/[\s,]+/).filter(Boolean);
    if (parts.length === 0) throw new Error(`${label}：至少填一个时间点`);
    const out = [];
    for (const p of parts) {
        const n = Number(p);
        if (!Number.isInteger(n) || n < min || n > max) {
            throw new Error(`${label}："${p}" 不是 ${min}-${max} 的整数`);
        }
        out.push(n);
    }
    return out;
}

/** 把 int 数组渲染回逗号分隔字符串 */
function formatCronList(arr) {
    return (arr || []).join(',');
}

/** 把时间戳渲染成可读字符串 */
function fmtTime(t) {
    if (!t) return '—';
    const d = new Date(t);
    if (isNaN(d.getTime())) return String(t);
    return d.toLocaleString('zh-CN', { hour12: false });
}

/* ════════════════════════════════════════════════
 * 模块 1：Service — 服务启停 / 状态
 *
 *   通过 cockpit.spawn 执行 start_platform.sh 的子命令。
 *   每个 action 返回一个对象 { promise, channel }，
 *   channel.stream() 用于把实时输出回显到页面。
 * ════════════════════════════════════════════════ */
const Service = {
    /**
     * 执行脚本子命令，实时回显 stdout/stderr。
     * @param {string} cmd  start|stop|restart|status
     * @param {(chunk:string)=>void} onChunk  收到输出时的回调
     * @returns {Promise<string>}  完整 stdout
     */
    run(cmd, onChunk) {
        return new Promise((resolve, reject) => {
            const ch = cockpit.spawn(["bash", SCRIPT, cmd], SPAWN_OPTS);
            ch.stream((data, stream) => {
                // stream === "output" | "stderr"（err:"message" 模式）
                if (onChunk) onChunk(data, stream);
            });
            ch.then(
                (stdout) => { ch.close(); resolve(stdout); },
                (err)    => { ch.close(); reject(err); }
            );
        });
    },

    /** 直接通过 netstat/端口判断后端是否在跑 */
    async isRunning() {
        try {
            const r = await fetch(`${API_BASE}/api/health`, { cache: 'no-store' });
            return r.ok;
        } catch {
            return false;
        }
    },

    /** 读取后端 PID（从 pid 文件） */
    async readPid() {
        try {
            const f = cockpit.file(`${HOME}/pids/backend.pid`);
            const content = await f.read();
            f.close();
            return (content || '').trim() || null;
        } catch {
            return null;
        }
    }
};

/* ════════════════════════════════════════════════
 * 模块 2：Config — 定时调度读写（走 HTTP API）
 *
 *   后端的 PUT /api/fetch/schedule 修改后会自动 reload_scheduler()，
 *   所以保存即热生效，无需重启后端。
 * ════════════════════════════════════════════════ */
const Config = {
    async getSchedule() {
        const r = await fetch(`${API_BASE}/api/fetch/schedule`, { cache: 'no-store' });
        if (!r.ok) throw new Error(`读取调度失败 (${r.status})`);
        return r.json();
    },

    /**
     * @param payload 形如
     *   { enabled, hours, minutes, ai_enabled, ai_hours, ai_minutes }
     *   全部字段都可选，只下发需要改的。
     */
    async saveSchedule(payload) {
        const r = await fetch(`${API_BASE}/api/fetch/schedule`, {
            method:  'PUT',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(payload)
        });
        if (!r.ok) {
            let detail = '';
            try { detail = (await r.json()).detail || ''; } catch {}
            throw new Error(`保存调度失败 (${r.status}) ${detail}`);
        }
        return r.json();
    }
};

/* ════════════════════════════════════════════════
 * 模块 3：LogView — 实时 tail backend.log
 *
 *   cockpit.spawn(["tail","-n",N,"-f",path]) 会保持 channel 打开，
 *   新日志持续推过来。stop() 时必须 close，否则 channel 泄漏。
 * ════════════════════════════════════════════════ */
const LogView = {
    _channel: null,

    start(lines) {
        this.stop();
        const view = $('#log-view');
        view.textContent = '';
        this._append(view, `──── 开始跟踪 ${LOG_PATH}（最近 ${lines} 行）────\n`);

        const ch = cockpit.spawn(
            ["tail", "-n", String(lines), "-f", LOG_PATH],
            { superuser: "try", err: "message", pty: false }
        );
        this._channel = ch;

        ch.stream((data) => this._append(view, data));
        ch.catch((err) => {
            this._append(view, `\n[ERR] tail 退出: ${err.message || err.problem || err}\n`);
        }).finally(() => {
            // tail -f 正常情况下不会主动退出；退出即说明 channel 已关闭
            this._channel = null;
            this._updateButtons(false);
        });

        this._updateButtons(true);
    },

    stop() {
        if (this._channel) {
            this._channel.close();
            this._channel = null;
            this._updateButtons(false);
            const view = $('#log-view');
            this._append(view, `\n──── 已停止跟踪 ────\n`);
        }
    },

    clear() {
        $('#log-view').textContent = '';
    },

    _append(view, text) {
        view.textContent += text;
        if ($('#log-autoscroll').checked) {
            view.scrollTop = view.scrollHeight;
        }
    },

    _updateButtons(running) {
        $('#btn-log-start').disabled = running;
        $('#btn-log-stop').disabled  = !running;
    }
};

/* ════════════════════════════════════════════════
 * UI 控制器 — 把上面三个模块绑定到 DOM
 * ════════════════════════════════════════════════ */
const UI = {
    /** 初始化：绑定事件、首次拉取状态 */
    async init() {
        this._bindService();
        this._bindSchedule();
        this._bindLog();

        // 首次刷新
        await this.refreshService();
        await this.refreshSchedule();
        await this.refreshStats();

        // 定时轮询状态（不打扰用户操作）
        this._pollTimer = setInterval(() => {
            this.refreshService({ silent: true });
            this.refreshStats({ silent: true });
        }, 15000);

        // 页面卸载时清理 channel
        window.addEventListener('beforeunload', () => {
            clearInterval(this._pollTimer);
            LogView.stop();
        });
    },

    /* ── 服务控制 ─────────────────────────────── */
    _bindService() {
        const output = $('#svc-output');

        const withConfirm = (label, fn) => async () => {
            if (!confirm(`${label}？`)) return;
            output.textContent = '';
            $('#svc-output-wrap').open = true;
            toast(`${label}中…`, 'info');
            try {
                await fn((data) => { output.textContent += data; });
                toast(`${label}完成`, 'success');
            } catch (err) {
                output.textContent += `\n[ERR] ${err.message || err}\n`;
                toast(`${label}失败`, 'error');
            }
            await this.refreshService();
        };

        $('#btn-start').onclick   = withConfirm('启动 LapTalk',  (cb) => Service.run('start',   cb));
        $('#btn-stop').onclick    = withConfirm('停止 LapTalk',  (cb) => Service.run('stop',    cb));
        $('#btn-restart').onclick = withConfirm('重启 LapTalk',  (cb) => Service.run('restart', cb));
        $('#btn-refresh').onclick = () => this.refreshService();
    },

    /** 刷新服务状态指示灯 */
    async refreshService(opts = {}) {
        const silent = opts.silent;
        const indicator = $('#svc-indicator');
        const text = $('#svc-status-text');
        const pidEl = $('#svc-pid');

        if (!silent) text.textContent = '检测中…';
        indicator.className = 'laptalk-dot laptalk-dot-unknown';

        const [running, pid] = await Promise.all([Service.isRunning(), Service.readPid()]);

        if (running) {
            indicator.className = 'laptalk-dot laptalk-dot-ok';
            text.textContent = '运行中';
        } else {
            indicator.className = 'laptalk-dot laptalk-dot-down';
            text.textContent = '未启动';
        }
        pidEl.textContent = pid ? `PID: ${pid}` : '';

        // 连接横幅
        const banner = $('#conn-banner');
        banner.textContent = running ? '已连接后端' : '后端未连接';
        banner.className = 'laptalk-banner' + (running ? ' laptalk-banner-ok' : ' laptalk-banner-warn');
    },

    /* ── 定时调度 ─────────────────────────────── */
    _bindSchedule() {
        $('#btn-reload-schedule').onclick = () => this.refreshSchedule();
        $('#btn-save-schedule').onclick   = () => this.saveSchedule();
    },

    async refreshSchedule() {
        let data;
        try {
            data = await Config.getSchedule();
        } catch (err) {
            toast(`读取调度失败：${err.message}`, 'error');
            return;
        }
        // 数据采集
        $('#pipe-enabled').checked = !!data.enabled;
        const first = (data.schedule && data.schedule[0]) || {};
        // schedule 是 [{hour,minute}, ...]，需把 hours/minutes 拆开
        const pipeH = (data.schedule || []).map(s => s.hour);
        const pipeM = (data.schedule || []).map(s => s.minute);
        $('#pipe-hours').value   = formatCronList(pipeH);
        $('#pipe-minutes').value = formatCronList(pipeM);
        $('#pipe-last-run').textContent     = fmtTime(data.last_run);
        $('#pipe-last-status').textContent  = data.last_status || '—';

        // AI 全流程
        $('#ai-enabled').checked = !!data.ai_enabled;
        const aiH = (data.ai_schedule || []).map(s => s.hour);
        const aiM = (data.ai_schedule || []).map(s => s.minute);
        $('#ai-hours').value   = formatCronList(aiH);
        $('#ai-minutes').value = formatCronList(aiM);
        $('#ai-last-run').textContent    = fmtTime(data.ai_last_run);
        $('#ai-last-status').textContent = data.ai_last_status || '—';
    },

    async saveSchedule() {
        let payload, pipeH, pipeM, aiH, aiM;
        try {
            pipeH = parseCronList($('#pipe-hours').value,   0, 23, '数据采集·小时');
            pipeM = parseCronList($('#pipe-minutes').value, 0, 59, '数据采集·分钟');
            aiH   = parseCronList($('#ai-hours').value,     0, 23, 'AI 流程·小时');
            aiM   = parseCronList($('#ai-minutes').value,   0, 59, 'AI 流程·分钟');

            payload = {
                enabled:    $('#pipe-enabled').checked,
                hours:      pipeH,
                minutes:    pipeM,
                ai_enabled: $('#ai-enabled').checked,
                ai_hours:   aiH,
                ai_minutes: aiM
            };
        } catch (err) {
            toast(err.message, 'error');
            return;
        }

        $('#btn-save-schedule').disabled = true;
        try {
            await Config.saveSchedule(payload);
            toast('已保存，调度器已自动重载', 'success');
            await this.refreshSchedule();
        } catch (err) {
            toast(`保存失败：${err.message}`, 'error');
        } finally {
            $('#btn-save-schedule').disabled = false;
        }
    },

    /* ── 系统状态 ─────────────────────────────── */
    async refreshStats(opts = {}) {
        const silent = opts.silent;
        const setIf = (sel, val) => { const el = $(sel); if (el) el.textContent = val; };

        // 并行拉三个端点，任一失败不影响其它
        const results = await Promise.allSettled([
            fetch(`${API_BASE}/api/stats`,              { cache: 'no-store' }).then(r => r.json()),
            fetch(`${API_BASE}/api/fetch/schedule`,     { cache: 'no-store' }).then(r => r.json()),
            fetch(`${API_BASE}/api/pipeline/status`,    { cache: 'no-store' }).then(r => r.json())
        ]);

        // stats
        if (results[0].status === 'fulfilled') {
            const s = results[0].value;
            setIf('#stat-articles',      s.articles ?? s.total_articles ?? '—');
            setIf('#stat-events',        s.events ?? '—');
            setIf('#stat-active-events', s.active_events ?? '—');
        } else if (!silent) {
            setIf('#stat-articles', '—');
        }

        // schedule → scheduler_running
        if (results[1].status === 'fulfilled') {
            const sc = results[1].value;
            setIf('#stat-scheduler', sc.scheduler_running ? '运行中 ✓' : '已停止');
        }

        // pipeline 当前状态
        if (results[2].status === 'fulfilled') {
            const p = results[2].value;
            setIf('#pipe-state', p.running ? '采集中…' : '空闲');
            setIf('#pipe-step',  p.current_step || (p.steps ? `${p.steps.length} 步` : '—'));
        }

        // 链接
        $('#link-home').href = `${API_BASE}/`;
        $('#link-docs').href = `${API_BASE}/docs`;
    },

    /* ── 实时日志 ─────────────────────────────── */
    _bindLog() {
        $('#btn-log-start').onclick = () => {
            const n = parseInt($('#log-lines').value, 10) || 500;
            LogView.start(n);
            toast(`开始跟踪日志（最近 ${n} 行）`, 'info');
        };
        $('#btn-log-stop').onclick  = () => LogView.stop();
        $('#btn-log-clear').onclick = () => LogView.clear();
    }
};

/* ════════════════════════════════════════════════
 * 启动
 * ════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
    // cockpit.js 存在性自检（防止 manifest 配错导致脚本 404）
    if (typeof cockpit === 'undefined') {
        document.body.innerHTML =
            '<div style="padding:2em;color:#c00;font-family:sans-serif">' +
            '错误：cockpit.js 未加载。请检查该插件是否安装到 /usr/local/share/cockpit/laptalk/，' +
            '且 index.html 中 <code>&lt;script src="../base1/cockpit.js"&gt;</code> 路径正确。</div>';
        return;
    }
    UI.init().catch(err => toast(`初始化失败：${err.message}`, 'error'));
});
