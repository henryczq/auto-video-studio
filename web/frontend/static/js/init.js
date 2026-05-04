function bindEventListeners() {
    document.getElementById('ai-api-type').addEventListener('change', (e) => {
        const apiType = e.target.value;
        const promptTextarea = document.getElementById('ai-prompt');
        if (apiType === 'anthropic-messages') {
            if (!promptTextarea.value.includes('claude')) {
                promptTextarea.value = 'You are an AI assistant. Please help correct the following transcription errors...';
            }
        }
    });

    document.getElementById('ai-active-model').addEventListener('change', async (e) => {
        const modelId = e.target.value;
        aiConfig.active_id = modelId || '';
        if (!modelId) {
            try {
                await api('POST', '/ai-config', aiConfig);
                renderAiConfig();
            } catch (err) {
                console.error('Failed to clear active model:', err);
            }
            return;
        }

        const model = aiConfig.models.find(m => m.id === modelId);
        if (model) {
            selectedAiModelId = modelId;
            fillAiModelForm(model);
            try {
                await api('POST', '/ai-config', aiConfig);
                renderAiConfig();
                console.log('Active model updated');
            } catch (err) {
                console.error('Failed to update active model:', err);
            }
        }
    });

    document.getElementById('ai-models-table').addEventListener('click', (e) => {
        if (e.target.type === 'radio') {
            const modelId = e.target.value;
            selectAiModel(modelId);
        }
    });

    document.getElementById('ai-new-model-btn').addEventListener('click', () => {
        selectedAiModelId = 'model_' + Date.now();
        fillAiModelForm(null);
        document.getElementById('ai-name').focus();
    });

    document.getElementById('ai-save-model-btn').addEventListener('click', async () => {
        const formModel = currentAiFormModel();
        if (!formModel.name || !formModel.model || !formModel.base_url) {
            window.notifyWarning('请填写完整的模型配置（名称、模型、Base URL）');
            return;
        }
        if (!formModel.api_key) {
            if (!confirm('API Key 为空，确定要保存吗？')) return;
        }
        const existingIndex = aiConfig.models.findIndex(m => m.id === selectedAiModelId);
        if (existingIndex >= 0) {
            aiConfig.models[existingIndex] = formModel;
        } else {
            aiConfig.models.push(formModel);
        }
        aiConfig.active_id = selectedAiModelId;
        try {
            await api('POST', '/ai-config', aiConfig);
            await saveAiConfig('模型已保存');
            renderAiConfig();
        } catch (err) {
            window.notifyError('保存失败: ' + err.message);
        }
    });

    document.getElementById('ai-test-model-btn').addEventListener('click', async () => {
        const formModel = currentAiFormModel();
        if (!formModel.model || !formModel.base_url) {
            window.notifyWarning('请先选择或填写模型配置');
            return;
        }
        const btn = document.getElementById('ai-test-model-btn');
        btn.disabled = true;
        btn.textContent = '测试中...';
        try {
            const result = await api('POST', '/ai-config/test', formModel);
            window.notifySuccess('测试成功');
        } catch (err) {
            window.notifyError('测试失败: ' + err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = '测试当前模型';
        }
    });

    document.getElementById('ai-delete-model-btn').addEventListener('click', async () => {
        if (!selectedAiModelId) {
            window.notifyWarning('请先选择要删除的模型');
            return;
        }
        if (!confirm('确定删除当前模型？')) return;
        aiConfig.models = aiConfig.models.filter(m => m.id !== selectedAiModelId);
        if (aiConfig.active_id === selectedAiModelId) {
            aiConfig.active_id = aiConfig.models[0]?.id || '';
        }
        selectedAiModelId = '';
        try {
            await api('POST', '/ai-config', aiConfig);
            await saveAiConfig('模型已删除');
            renderAiConfig();
        } catch (err) {
            window.notifyError('删除失败: ' + err.message);
        }
    });

    document.getElementById('ai-save-config-btn').addEventListener('click', async () => {
        aiConfig.prompt = document.getElementById('ai-prompt').value;
        aiConfig.tts_segment_prompt = document.getElementById('ai-tts-segment-prompt').value;
        try {
            await api('POST', '/ai-config', aiConfig);
            await saveAiConfig('AI 配置已保存');
        } catch (err) {
            window.notifyError('保存失败: ' + err.message);
        }
    });

    document.getElementById('ai-refresh-logs-btn').addEventListener('click', loadAiLogs);

    document.getElementById('log-detail-select').addEventListener('change', async (e) => {
        const recordId = e.target.value;
        if (!recordId) return;
        await loadUploadLogDetail(recordId, 'logs');
    });

    document.getElementById('refresh-logs-btn').addEventListener('click', loadUploadLogs);

    document.getElementById('job-filter')?.addEventListener('change', loadJobs);

    document.getElementById('upload-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById('video-file');
        const file = fileInput.files[0];
        if (!file) return;
        const uploadBtn = document.getElementById('upload-job-btn');
        const resultDiv = document.getElementById('upload-job-result');
        const clipStart = document.getElementById('job-clip-start').value.trim();
        const clipEnd = document.getElementById('job-clip-end').value.trim();
        const hasClipRange = !!(clipStart || clipEnd);
        const originalBtnText = uploadBtn?.textContent || '上传并创建任务';

        const formData = new FormData();
        formData.append('video', file);
        formData.append('name', document.getElementById('job-name').value.trim());
        formData.append('clip_start', clipStart);
        formData.append('clip_end', clipEnd);

        if (uploadBtn) {
            uploadBtn.disabled = true;
            uploadBtn.textContent = hasClipRange ? '上传并裁剪中...' : '上传中...';
        }
        if (resultDiv) {
            resultDiv.innerHTML = hasClipRange
                ? `
                    <div class="progress-panel">
                        <strong>正在上传并裁剪视频</strong>
                        <div style="margin-top:6px; font-size:13px;">已提交文件，后台会先按你填写的时间范围裁出任务输入视频，再创建任务。这个阶段完成前页面不会立刻跳转。</div>
                        <div class="progress-bar"></div>
                    </div>
                `
                : `
                    <div class="progress-panel">
                        <strong>正在上传视频</strong>
                        <div style="margin-top:6px; font-size:13px;">文件上传完成后会立刻创建任务，并自动切换到该任务。</div>
                        <div class="progress-bar"></div>
                    </div>
                `;
        }

        try {
            const res = await fetch(API_BASE + '/jobs', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data?.detail || data?.error || '上传失败');
            }
            window.notifySuccess('任务已创建: ' + data.job_id);
            if (resultDiv) {
                const clipInfo = data.source_start || data.source_end
                    ? `<div style="margin-top:6px; font-size:13px;">上传裁剪范围：<code>${escapeHtml(data.source_start || '0')}</code> - <code>${escapeHtml(data.source_end || '')}</code></div>`
                    : '';
                resultDiv.innerHTML = `
                    <div class="message message-success">
                        <strong>任务已创建</strong>
                        <div style="margin-top:6px; font-size:13px;">任务 ID：<code>${escapeHtml(data.job_id)}</code></div>
                        ${clipInfo}
                    </div>
                `;
            }
            fileInput.value = '';
            document.getElementById('job-name').value = '';
            document.getElementById('job-clip-start').value = '';
            document.getElementById('job-clip-end').value = '';
            await loadJobs();
            await selectJob(data.job_id);
        } catch (err) {
            if (resultDiv) {
                resultDiv.innerHTML = `<div class="message message-error"><strong>上传失败</strong><div style="margin-top:6px; font-size:13px;">${escapeHtml(err.message)}</div></div>`;
            }
            window.notifyError('上传失败: ' + err.message);
        } finally {
            if (uploadBtn) {
                uploadBtn.disabled = false;
                uploadBtn.textContent = originalBtnText;
            }
        }
    });

    document.getElementById('save-cut-marks-btn')?.addEventListener('click', async () => {
        const jobId = document.getElementById('caption-job-select')?.value;
        if (!jobId) {
            window.notifyWarning('请先选择一个任务');
            return;
        }
        await saveCutMarks(jobId);
    });

    document.getElementById('clear-cut-marks-btn')?.addEventListener('click', async () => {
        const jobId = document.getElementById('caption-job-select')?.value;
        if (!jobId) {
            window.notifyWarning('请先选择一个任务');
            return;
        }
        await clearCutMarks(jobId);
    });
}

async function init() {
    console.log('[Init] starting, token:', getApiToken() ? 'present' : 'empty');
    bindEventListeners();
    await loadConfig();
    await loadAiConfig();
    await loadAiLogs();
    await loadJobs();
    await loadTrimJobs();
    await loadComposeJobs();
    if (typeof loadTerms === 'function') {
        await loadTerms();
    } else {
        console.warn('[Init] loadTerms not loaded yet, skipping');
    }
    await loadSocialConfig();
    await loadUploadLogs();
    await loadPublishSettings();
    syncTtsModelDir();
    updateTtsProviderUI();
    updateTtsModeUI();
    updateTtsParallelModeUI();
    setupBeforeUnloadProtection();
    setInterval(() => {
        if (currentJobId && typeof refreshCurrentJobViews === 'function') {
            refreshCurrentJobViews(true);
        }
    }, 5000);
    console.log('[Init] complete');
}

window.addEventListener('DOMContentLoaded', init);
