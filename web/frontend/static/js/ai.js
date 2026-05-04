async function loadAiConfig() {
    try {
        aiConfig = await api('GET', '/ai-config');
        console.log('AI config loaded:', aiConfig);
        selectedAiModelId = aiConfig.active_id || (aiConfig.models?.[0]?.id || '');
        renderAiConfig();
    } catch (err) {
        console.error('Failed to load AI config:', err);
        document.getElementById('ai-config-result').innerHTML = '<div class="message message-error">加载AI配置失败: ' + escapeHtml(err.message) + '</div>';
    }
}

function renderAiConfig() {
    const activeSelect = document.getElementById('ai-active-model');
    const models = aiConfig.models || [];
    console.log('Rendering AI config, models:', models);
    console.log('AI config prompt:', aiConfig.prompt ? aiConfig.prompt.substring(0, 50) + '...' : 'EMPTY');
    console.log('AI config tts_segment_prompt:', aiConfig.tts_segment_prompt ? aiConfig.tts_segment_prompt.substring(0, 50) + '...' : 'EMPTY');
    activeSelect.innerHTML = '<option value="">不启用 AI（使用规则兜底）</option>' + models.map(model => `
        <option value="${model.id}">${escapeHtml(model.name || model.model || model.id)}</option>
    `).join('');
    activeSelect.value = aiConfig.active_id || '';
    const promptEl = document.getElementById('ai-prompt');
    const ttsPromptEl = document.getElementById('ai-tts-segment-prompt');
    if (promptEl) {
        promptEl.value = aiConfig.prompt || '';
        console.log('Set ai-prompt value, length:', (aiConfig.prompt || '').length);
    } else {
        console.error('ai-prompt element not found');
    }
    if (ttsPromptEl) {
        ttsPromptEl.value = aiConfig.tts_segment_prompt || '';
        console.log('Set ai-tts-segment-prompt value, length:', (aiConfig.tts_segment_prompt || '').length);
    } else {
        console.error('ai-tts-segment-prompt element not found');
    }
    fillAiModelForm(models.find(model => model.id === selectedAiModelId) || null);
    renderAiModelsTable();
    console.log('AI config rendered, select innerHTML:', activeSelect.innerHTML);
}

function renderAiModelsTable() {
    const tbody = document.querySelector('#ai-models-table tbody');
    const models = aiConfig.models || [];
    if (models.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#999;">暂无 AI 模型配置</td></tr>';
        return;
    }
    tbody.innerHTML = models.map(model => {
        const isActive = model.id === aiConfig.active_id;
        const apiTypeLabels = { compatible: 'Chat Completions', responses: 'Responses API', 'anthropic-messages': 'Anthropic Messages' };
        const apiType = apiTypeLabels[model.api_type] || model.api_type || 'Chat Completions';
        return `<tr>
            <td><input type="radio" name="ai-model-radio" value="${model.id}" ${isActive ? 'checked' : ''}></td>
            <td>${escapeHtml(apiType)}</td>
            <td>${escapeHtml(model.name || '-')}</td>
            <td>${escapeHtml(model.model || '-')}</td>
            <td>${escapeHtml(model.base_url || '-')}</td>
            <td>${model.api_key ? '******' : '-'}</td>
            <td><button class="btn btn-sm btn-secondary" onclick="selectAiModel('${model.id}')">编辑</button></td>
        </tr>`;
    }).join('');
}

function fillAiModelForm(model) {
    if (!model) {
        document.getElementById('ai-name').value = '';
        document.getElementById('ai-model').value = '';
        document.getElementById('ai-base-url').value = '';
        document.getElementById('ai-api-key').value = '';
        document.getElementById('ai-api-type').value = 'compatible';
        return;
    }
    document.getElementById('ai-name').value = model.name || '';
    document.getElementById('ai-model').value = model.model || '';
    document.getElementById('ai-base-url').value = model.base_url || '';
    document.getElementById('ai-api-key').value = model.api_key || '';
    document.getElementById('ai-api-type').value = model.api_type || 'compatible';
}

function currentAiFormModel() {
    return {
        id: selectedAiModelId || 'model_' + Date.now(),
        name: document.getElementById('ai-name').value.trim(),
        model: document.getElementById('ai-model').value.trim(),
        base_url: document.getElementById('ai-base-url').value.trim(),
        api_key: document.getElementById('ai-api-key').value.trim(),
        api_type: document.getElementById('ai-api-type').value,
    };
}

async function saveAiConfig(message = 'AI 配置已保存') {
    const resultEl = document.getElementById('ai-config-result');
    resultEl.innerHTML = '<div class="message message-success">' + message + '</div>';
    setTimeout(() => { resultEl.innerHTML = ''; }, 3000);
}

async function loadAiLogs() {
    try {
        const logs = await api('GET', '/ai-logs');
        const tbody = document.querySelector('#ai-logs-table tbody');
        if (!logs || logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#999;">暂无日志</td></tr>';
            return;
        }
        tbody.innerHTML = logs.slice(0, 50).map(log => `<tr>
            <td>${escapeHtml(log.created_at ? new Date(log.created_at).toLocaleString() : '')}</td>
            <td>${escapeHtml(log.type || '')}</td>
            <td>${escapeHtml(log.status || '')}</td>
            <td>${escapeHtml(log.model || log.model_name || '')}</td>
            <td>${typeof log.duration_ms === 'number' ? (log.duration_ms / 1000).toFixed(2) + 's' : '-'}</td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(log.response_preview || log.error || '')}</td>
            <td><button type="button" class="btn btn-sm btn-secondary" onclick="window.loadAiLogDetail('${log.id}')">详情</button></td>
        </tr>`).join('');
    } catch (err) {
        console.error('Failed to load AI logs:', err);
    }
}

window.loadAiLogDetail = async function(logId) {
    try {
        const log = await api('GET', '/ai-logs/' + logId);
        const detailEl = document.getElementById('ai-log-detail');
        if (!detailEl) {
            throw new Error('AI 日志详情容器不存在');
        }
        detailEl.style.display = 'block';
        updateLogViewerContent(detailEl, JSON.stringify(log, null, 2));
        detailEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (err) {
        console.error('Failed to load AI log detail:', err);
        if (window.notifyError) {
            window.notifyError('加载 AI 日志详情失败: ' + err.message);
        }
    }
};

function selectAiModel(modelId) {
    selectedAiModelId = modelId;
    const model = aiConfig.models.find(m => m.id === modelId);
    fillAiModelForm(model || null);
}
