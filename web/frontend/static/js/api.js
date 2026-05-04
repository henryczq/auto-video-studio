function formatApiErrorDetail(detail) {
    if (!detail) return 'Request failed';
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        return detail.map(item => {
            if (typeof item === 'string') return item;
            if (item && typeof item === 'object') {
                const location = Array.isArray(item.loc) ? item.loc.join(' -> ') : '';
                const message = item.msg || JSON.stringify(item);
                return location ? `${location}: ${message}` : message;
            }
            return String(item);
        }).join('; ');
    }
    if (typeof detail === 'object') {
        return detail.message || JSON.stringify(detail);
    }
    return String(detail);
}

async function api(method, path, body = null) {
    const options = { method, headers: {} };
    if (body) {
        options.body = JSON.stringify(body);
        options.headers['Content-Type'] = 'application/json';
    }
    const token = getApiToken();
    if (token) {
        options.headers['X-Token'] = token;
    }
    const res = await fetch(API_BASE + path, options);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(formatApiErrorDetail(err.detail));
    }
    return res.json();
}

function jobFileUrl(jobId, filename, version = null) {
    const token = getApiToken();
    const params = new URLSearchParams();
    if (token) {
        params.set('token', token);
    }
    if (version !== null && version !== undefined && version !== '') {
        params.set('_', String(version));
    }
    return `${API_BASE}/jobs/${encodeURIComponent(jobId)}/download/${encodeURIComponent(filename)}?${params.toString()}`;
}

function getJobMediaVersion(job) {
    if (!job) return '';
    return job.updated_at || job.created_at || '';
}

function formatJobDisplayName(job, options = {}) {
    if (!job) return '';
    const { includeId = true, includeStatus = false } = options;
    const primary = job.name || job.video_filename || job.id;
    const parts = [primary];
    if (includeId && primary !== job.id) {
        parts.push(job.id);
    }
    let label = parts.join(' - ');
    if (includeStatus && job.status) {
        label += ` [${job.status}]`;
    }
    return label;
}

function showTokenInput() {
    const token = prompt('请输入访问令牌 (AUTO_CUT_TOKEN):');
    if (token) {
        setApiToken(token);
        window.location.reload();
    }
}

function formatTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
