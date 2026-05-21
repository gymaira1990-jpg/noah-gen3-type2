// NOAH-PRIME · 统一状态中心 (StateManager)
// 5秒轮询 /api/status/snapshot，渲染系统状态卡

const StateCenter = {
    data: {},

    async fetch() {
        try {
            const r = await fetch('/api/status/snapshot');
            if (!r.ok) throw new Error('status ' + r.status);
            this.data = await r.json();
            this.render();
        } catch(e) {
            document.getElementById('status-bar').innerHTML =
                '⚙ 状态中心离线';
        }
    },

    render() {
        const d = this.data;
        const bar = document.getElementById('status-bar');
        if (!bar) return;

        const projects = (d.active_projects || [])
            .map(p => p.summary || p.ticket_id || '?').join(', ') || '待命';
        const queue = d.queue || {};
        const sys = d.system || {};

        bar.innerHTML =
            '⚙ ' + projects + ' | ' +
            '⏳ 排队:' + (queue.in_memory || 0) + ' | ' +
            '🖥 CPU:' + (sys.cpu_percent || '?') + '% ' +
            'MEM:' + (sys.memory_percent || '?') + '% ' +
            (d.tokens ? '| 💰 Token:' + d.tokens : '') +
            ' | ' + (d.calls || 0) + '次调用';
    },

    start() {
        this.fetch();
        setInterval(() => this.fetch(), 5000);
    }
};

document.addEventListener('DOMContentLoaded', () => {
    // 注入状态栏(如不存在)
    if (!document.getElementById('status-bar')) {
        const bar = document.createElement('div');
        bar.id = 'status-bar';
        bar.style.cssText = 'position:fixed;bottom:0;left:0;right:0;'
            + 'background:#1a1a2e;color:#e0e0e0;padding:6px 16px;'
            + 'font-size:12px;font-family:monospace;z-index:9999;'
            + 'border-top:1px solid #333;';
        document.body.appendChild(bar);
    }
    StateCenter.start();
});
