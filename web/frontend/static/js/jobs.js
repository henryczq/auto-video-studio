function buildJobPublishStatusMap(records) {
    const map = new Map();
    (records || []).forEach(record => {
        const jobId = record.job_id;
        const platform = record.platform;
        if (!jobId || !platform) return;
        if (!map.has(jobId)) {
            map.set(jobId, new Map());
        }
        const jobPlatforms = map.get(jobId);
        const current = jobPlatforms.get(platform);
        if (!current) {
            jobPlatforms.set(platform, record);
            return;
        }
        const currentTime = new Date(current.updated_at || current.created_at || 0).getTime();
        const nextTime = new Date(record.updated_at || record.created_at || 0).getTime();
        if (nextTime >= currentTime) {
            jobPlatforms.set(platform, record);
        }
    });
    return map;
}

function renderJobPublishSummary(jobId, platformsConfig, publishStatusMap) {
    const allPlatforms = Object.entries(platformsConfig?.platforms || {})
        .filter(([, info]) => info.support_video !== false)
        .map(([platformId, info]) => ({
            id: platformId,
            name: info.name || platformId,
        }));

    if (!allPlatforms.length) {
        return '';
    }

    const jobPlatforms = publishStatusMap.get(jobId) || new Map();
    const success = [];
    const running = [];
    const failed = [];
    const pending = [];

    allPlatforms.forEach(platform => {
        const record = jobPlatforms.get(platform.id);
        if (!record) {
            pending.push(platform.name);
            return;
        }
        if (record.status === 'running') {
            running.push(platform.name);
            return;
        }
        if (Number(record.success) === 1) {
            success.push(platform.name);
            return;
        }
        failed.push(platform.name);
    });

    const parts = [];
    if (success.length) {
        parts.push(`<span style="color:#166534;">已发布：${escapeHtml(success.join('、'))}</span>`);
    }
    if (running.length) {
        parts.push(`<span style="color:#1d4ed8;">发布中：${escapeHtml(running.join('、'))}</span>`);
    }
    if (failed.length) {
        parts.push(`<span style="color:#b91c1c;">失败：${escapeHtml(failed.join('、'))}</span>`);
    }
    if (pending.length) {
        parts.push(`<span style="color:#6b7280;">未发布：${escapeHtml(pending.join('、'))}</span>`);
    }

    return `
        <div style="margin-top:6px; font-size:12px; line-height:1.5;">
            ${parts.join(' <span style="color:#cbd5e1;">|</span> ')}
        </div>
    `;
}

async function loadJobs() {
    console.log('[loadJobs] starting');
    const [jobs, platformsConfig, uploadRecords] = await Promise.all([
        api('GET', '/jobs'),
        api('GET', '/social/platforms/config').catch(() => ({ platforms: {} })),
        api('GET', '/social/upload-records').catch(() => []),
    ]);
    console.log('[loadJobs] got', jobs.length, 'jobs');
    const container = document.getElementById('job-list');
    const jobSelect = document.getElementById('caption-job-select');
    const filter = document.getElementById('job-filter')?.value || 'all';
    const publishStatusMap = buildJobPublishStatusMap(uploadRecords);

    const isCompleted = (job) => {
        const status = job.status || '';
        return status.includes('composed') ||
               status.includes('tts_completed') ||
               status.includes('video_processed') ||
               status === 'completed';
    };

    const isProcessing = (job) => {
        const status = job.status || '';
        return status.includes('processing') ||
               status.includes('video_processing') ||
               status.includes('tts_processing') ||
               status.includes('composing');
    };

    const isError = (job) => {
        return job.status === 'error' ||
               job.tts_error ||
               job.process_error ||
               job.compose_error;
    };

    const isPending = (job) => {
        return job.status === 'created' ||
               job.status === 'pending' ||
               (!isCompleted(job) && !isProcessing(job) && !isError(job));
    };

    let filteredJobs = jobs;
    if (filter === 'completed') {
        filteredJobs = jobs.filter(isCompleted);
    } else if (filter === 'processing') {
        filteredJobs = jobs.filter(isProcessing);
    } else if (filter === 'pending') {
        filteredJobs = jobs.filter(isPending);
    } else if (filter === 'error') {
        filteredJobs = jobs.filter(isError);
    }

    if (filteredJobs.length === 0) {
        container.innerHTML = `<p style="color: #666;">暂无符合条件的任务</p>`;
        jobSelect.innerHTML = '<option value="">请先上传视频</option>';
        return;
    }

    container.innerHTML = filteredJobs.map(job => {
        const hasError = isError(job);
        const staleInfo = getStaleInfo(job);
        const jobLabel = formatJobDisplayName(job);
        const publishSummary = renderJobPublishSummary(job.id, platformsConfig, publishStatusMap);
        return `
        <div class="job-item" data-job-id="${job.id}" style="${hasError ? 'border-left: 3px solid #dc3545;' : ''}">
            <div class="job-info">
                <div class="job-name">${escapeHtml(jobLabel)}</div>
                <div class="job-status">
                    <span class="status-badge status-${job.status}">${job.status}</span>
                    ${staleInfo ? `<span class="dirty-indicator" title="派生文件过期">⚠️</span>` : ''}
                    ${job.video_filename ? `<span style="color:#666;">${escapeHtml(job.video_filename)}</span>` : ''}
                    ${job.created_at ? new Date(job.created_at).toLocaleString() : ''}
                </div>
                ${publishSummary}
            </div>
            <div class="action-buttons">
                <button class="btn btn-secondary btn-sm" onclick="selectJob('${job.id}')">选择</button>
                <button class="btn btn-secondary btn-sm" onclick="renameJob('${job.id}')">改名</button>
                <button class="btn btn-success btn-sm" onclick="runFullPipeline('${job.id}', this)">一键生成</button>
                <button class="btn btn-warning btn-sm" onclick="openPublishModal('${job.id}')">发布</button>
                <button class="btn btn-danger btn-sm" onclick="deleteJob('${job.id}', this)">删除</button>
            </div>
        </div>
    `}).join('');

    const currentValue = jobSelect.value;
    jobSelect.innerHTML = jobs.map(j =>
        `<option value="${j.id}">${escapeHtml(formatJobDisplayName(j))}</option>`
    ).join('');
    if (jobs.some(j => j.id === currentValue)) {
        jobSelect.value = currentValue;
    }
}

window.renameJob = async function(jobId) {
    const jobs = await api('GET', '/jobs');
    const job = jobs.find(item => item.id === jobId);
    const currentName = job?.name || '';
    const nextName = prompt('请输入任务名称：', currentName);
    if (nextName === null) {
        return;
    }
    try {
        await api('PATCH', `/jobs/${jobId}`, { name: nextName.trim() });
        await loadJobs();
        if (typeof loadSocialConfig === 'function') {
            loadSocialConfig();
        }
        if (typeof loadTrimJobs === 'function') {
            loadTrimJobs();
        }
        if (typeof loadComposeJobs === 'function') {
            loadComposeJobs();
        }
        window.notifySuccess(nextName.trim() ? '任务名称已更新' : '任务名称已清空');
    } catch (err) {
        window.notifyError('改名失败: ' + err.message);
    }
};

async function refreshCurrentJobViews(updateLogs = true) {
    if (!currentJobId) {
        return;
    }
    try {
        const job = await api('GET', `/jobs/${currentJobId}`);
        displayProcessResult(job);
        displayTtsResult(job);
        if (typeof refreshProcessLog === 'function') {
            await refreshProcessLog(currentJobId);
        }
        if (updateLogs) {
            await loadLogs(currentJobId);
        }
    } catch (err) {
        console.error('Failed to refresh current job:', err);
    }
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForJobState(jobId, predicate, options = {}) {
    const {
        timeoutMs = 30 * 60 * 1000,
        intervalMs = 3000,
        onUpdate = null,
        errorMessage = '等待任务完成超时'
    } = options;

    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
        const job = await api('GET', `/jobs/${jobId}`);
        if (typeof onUpdate === 'function') {
            onUpdate(job);
        }
        if (job.status === 'error' || job.process_error || job.tts_error || job.compose_error) {
            throw new Error(job.process_error || job.tts_error || job.compose_error || `任务执行失败：${job.status}`);
        }
        if (predicate(job)) {
            return job;
        }
        await sleep(intervalMs);
    }
    throw new Error(errorMessage);
}

async function selectJob(jobId) {
    if (jobId === currentJobId) return;
    if (window.captionEditorState?.hasUnsavedChanges) {
        if (!confirm('字幕编辑器有未保存的修改，切换任务会丢失这些修改。确定要切换吗？')) {
            return;
        }
    }
    currentJobId = jobId;
    document.getElementById('process-job-id').value = jobId;
    document.getElementById('caption-job-select').value = jobId;
    document.getElementById('tts-job-id').value = jobId;
    const trimSelect = document.getElementById('trim-job-select');
    const composeSelect = document.getElementById('compose-job-select');
    if (trimSelect) {
        trimSelect.value = jobId;
    }
    if (composeSelect) {
        composeSelect.value = jobId;
    }
    await loadCaptions(jobId, 'auto');
    loadSavedTtsSegments(jobId);
    if (typeof loadTrimInfo === 'function') {
        loadTrimInfo(jobId);
    }
    if (typeof loadComposeInfo === 'function') {
        loadComposeInfo(jobId);
    }
    loadLogs(jobId);
    try {
        const job = await api('GET', `/jobs/${jobId}`);
        displayProcessResult(job);
        displayTtsResult(job);
        if (typeof refreshProcessLog === 'function') {
            await refreshProcessLog(jobId);
        }
    } catch (err) {
        console.error('Failed to load selected job:', err);
    }
    document.querySelector('[data-tab="process"]').click();
}

window.deleteJob = async function(jobId, btn = null) {
    if (!confirm('确定删除这个任务吗？')) {
        return;
    }
    const deleteFiles = confirm('是否同时删除上传录像、处理结果、字幕、配音和最终视频文件？\n\n选择"取消"则只从任务列表移除，文件会保留在 videos/web_jobs 目录。');
    const originalText = btn ? btn.textContent : '';

    if (btn) {
        btn.disabled = true;
        btn.textContent = '删除中...';
    }

    try {
        await api('DELETE', `/jobs/${jobId}?delete_files=${deleteFiles ? 'true' : 'false'}`);
        if (currentJobId === jobId) {
            currentJobId = null;
            document.getElementById('process-job-id').value = '';
            document.getElementById('tts-job-id').value = '';
            document.getElementById('process-result').innerHTML = '';
            document.getElementById('tts-result').innerHTML = '';
            document.getElementById('captions-editor').innerHTML = '';
        }
        await loadJobs();
        window.notifySuccess(deleteFiles ? '任务和相关文件已删除' : '任务已从列表移除，文件已保留');
    } catch (err) {
        window.notifyError('删除失败: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
}

window.runFullPipeline = async function(jobId, btn) {
    if (!confirm('确定要执行一键生成吗？这将按顺序执行：视频处理 → 生成 TTS → 合成最终视频。')) return;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '处理中...';

    try {
        currentJobId = jobId;
        document.getElementById('process-job-id').value = jobId;
        const params = getProcessRequest();
        setPipelineProgress('正在处理视频...');
        await api('POST', `/jobs/${jobId}/process-video`, params);
        await waitForJobState(jobId, job => !!job.processed_video && job.status === 'video_processed', {
            errorMessage: '等待视频处理完成超时',
            onUpdate: (job) => {
                displayProcessResult(job);
            }
        });
        await refreshCurrentJobViews(true);
        setPipelineProgress('视频处理完成，正在应用词库并保存当前字幕...');
        await api('POST', `/jobs/${jobId}/apply-terms`, { stage: 'working' });
        const workingCaptions = await api('GET', `/jobs/${jobId}/captions?stage=working`);
        await api('POST', `/jobs/${jobId}/captions/final`, { captions: workingCaptions });
        await refreshCurrentJobViews(true);
        setPipelineProgress('当前字幕已保存，正在生成 TTS...');
        await api('POST', `/jobs/${jobId}/generate-tts`, getTtsRequest());
        await waitForJobState(jobId, job => !!job.voiceover, {
            errorMessage: '等待 TTS 生成完成超时',
            onUpdate: (job) => {
                displayTtsResult(job);
            }
        });
        await refreshCurrentJobViews(true);
        setPipelineProgress('TTS 生成完成，正在合成替换配音版...');
        await api('POST', `/jobs/${jobId}/compose`, { mode: 'replace_audio' });
        await waitForJobState(jobId, job => !!job.final_replace_audio, {
            errorMessage: '等待替换配音版合成完成超时',
            onUpdate: (job) => {
                displayTtsResult(job);
            }
        });
        await refreshCurrentJobViews(true);
        setPipelineProgress('替换配音版完成，正在合成仅字幕版...');
        await api('POST', `/jobs/${jobId}/compose`, { mode: 'subtitles_only' });
        await waitForJobState(jobId, job => !!job.final_subtitles_only, {
            errorMessage: '等待仅字幕版合成完成超时',
            onUpdate: (job) => {
                displayTtsResult(job);
            }
        });
        await refreshCurrentJobViews(true);
        setPipelineProgress('完成！');
        window.notifySuccess('一键生成完成！');
        await loadJobs();
    } catch (err) {
        window.notifyError('处理失败: ' + err.message);
        setPipelineProgress('');
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

window.refreshCurrentJobViews = refreshCurrentJobViews;

window.getStaleInfo = function(job) {
    if (!job) return null;
    const stale = [];
    const captionsVersion = job.captions_version || 0;
    if (captionsVersion > 0) {
        if ((job.trim_version || 0) < captionsVersion) stale.push('裁剪');
        if ((job.tts_version || 0) < captionsVersion) stale.push('TTS');
        if ((job.compose_version || 0) < captionsVersion) stale.push('合成');
    }
    return stale.length > 0 ? stale.join(', ') : null;
};

// 发布弹框相关
let currentPublishJobId = null;
let currentPublishPlatforms = [];
let availablePublishPlatforms = [];

window.openPublishModal = async function(jobId) {
    currentPublishJobId = jobId;

    // 获取任务信息
    const job = await api('GET', `/jobs/${jobId}`);
    const jobLabel = formatJobDisplayName(job);

    // 获取平台配置
    const platformsConfig = await api('GET', '/social/platforms/config').catch(() => ({ platforms: {} }));

    // 构建平台列表
    availablePublishPlatforms = Object.entries(platformsConfig.platforms || {})
        .filter(([, info]) => info.support_video !== false)
        .map(([id, info]) => ({ id, name: info.name || id }));

    // 设置任务名称
    document.getElementById('publish-modal-job-name').textContent = jobLabel;

    // 设置平台选择下拉框
    const platformSelect = document.getElementById('publish-modal-platform-select');
    platformSelect.innerHTML = '<option value="">请选择平台</option>' +
        availablePublishPlatforms.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');

    // 获取已保存的发布内容（使用社媒发布页面的API）
    let savedContent = null;
    try {
        const publishData = await api('GET', `/publish-settings/drafts/${jobId}`);
        if (publishData && Object.keys(publishData).length > 0) {
            savedContent = publishData;
        }
    } catch (e) {
        // 读取失败，使用默认值
    }

    // 如果有保存的内容，读取过来
    if (savedContent) {
        document.getElementById('publish-modal-title').value = savedContent.title || savedContent.name || jobLabel;
        document.getElementById('publish-modal-desc').value = savedContent.description || savedContent.desc || '';
        document.getElementById('publish-modal-tags').value = savedContent.tags || '';
        if (savedContent.platform) {
            platformSelect.value = savedContent.platform;
        }
    } else {
        // 设置默认标题
        document.getElementById('publish-modal-title').value = jobLabel;
        document.getElementById('publish-modal-desc').value = '';
        document.getElementById('publish-modal-tags').value = '';
    }

    // 显示弹框
    document.getElementById('publish-modal').style.display = 'block';
};

window.closePublishModal = function() {
    document.getElementById('publish-modal').style.display = 'none';
    currentPublishJobId = null;
    currentPublishPlatforms = [];
};

window.publishFromModal = async function() {
    if (!currentPublishJobId) return;

    // 获取选中的平台
    const selectedPlatform = document.getElementById('publish-modal-platform-select').value;

    if (!selectedPlatform) {
        window.notifyError('请选择发布平台');
        return;
    }

    const title = document.getElementById('publish-modal-title').value.trim();
    const desc = document.getElementById('publish-modal-desc').value.trim();
    const tags = document.getElementById('publish-modal-tags').value.trim();
    const videoType = document.getElementById('publish-modal-video-type').value;

    const confirmBtn = document.getElementById('publish-modal-confirm-btn');
    confirmBtn.disabled = true;
    confirmBtn.textContent = '发布中...';

    try {
        // 保存发布内容到任务（使用社媒发布页面的API）
        await api('POST', `/publish-settings/drafts/${currentPublishJobId}`, {
            platform: selectedPlatform,
            title: title,
            description: desc,
            tags: tags,
            video_type: videoType
        }).catch(() => {});

        // 切换到社交发布tab
        document.querySelector('[data-tab="social"]').click();

        // 设置任务
        const jobSelect = document.getElementById('upload-job-select');
        if (jobSelect) {
            jobSelect.value = currentPublishJobId;
            jobSelect.dispatchEvent(new Event('change'));
        }

        // 设置视频类型
        const videoTypeSelect = document.getElementById('upload-video-type');
        if (videoTypeSelect) {
            videoTypeSelect.value = videoType;
            videoTypeSelect.dispatchEvent(new Event('change'));
        }

        // 等待一下让UI更新
        await new Promise(r => setTimeout(r, 300));

        // 设置标题和简介
        const titleInput = document.getElementById('upload-title');
        const descInput = document.getElementById('upload-desc');
        const tagsInput = document.getElementById('upload-tags');

        if (titleInput) titleInput.value = title;
        if (descInput) descInput.value = desc;
        if (tagsInput) tagsInput.value = tags;

        // 获取对应平台的账号
        const accounts = await api('GET', '/social/accounts').catch(() => []);
        const accountSelect = document.getElementById('upload-account-select');
        if (accountSelect) {
            // 清空并选中对应平台的账号
            const options = accountSelect.querySelectorAll('option');
            options.forEach(opt => {
                const acc = accounts.find(a => a.id == opt.value);
                opt.selected = acc && acc.platform === selectedPlatform;
            });
        }

        // 关闭弹框
        closePublishModal();

        window.notifySuccess(`已准备好发布内容，请确认账号后点击"检查并发布"`);

    } catch (err) {
        window.notifyError('准备发布内容失败: ' + err.message);
    } finally {
        confirmBtn.disabled = false;
        confirmBtn.textContent = '发布';
    }
};

// 绑定弹框事件
document.addEventListener('DOMContentLoaded', function() {
    const cancelBtn = document.getElementById('publish-modal-cancel-btn');
    const confirmBtn = document.getElementById('publish-modal-confirm-btn');

    if (cancelBtn) {
        cancelBtn.addEventListener('click', closePublishModal);
    }
    if (confirmBtn) {
        confirmBtn.addEventListener('click', publishFromModal);
    }

    // 点击弹框外部关闭
    const modal = document.getElementById('publish-modal');
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                closePublishModal();
            }
        });
    }
});

