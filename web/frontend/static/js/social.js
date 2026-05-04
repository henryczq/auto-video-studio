// socialPlatformsConfig and related functions are defined in state.js

function renderAccountEntrySelects(platforms) {
    const qrSelect = document.getElementById('social-qr-platform');
    const bridgeSelect = document.getElementById('social-bridge-platform');
    const currentQr = qrSelect?.value || '';
    const currentBridge = bridgeSelect?.value || '';
    const qrPlatformIds = ['douyin', 'kuaishou', 'xiaohongshu', 'bilibili'];
    const webLoginPlatformIds = ['tencent', 'baijiahao', 'tiktok'];

    const qrPlatforms = platforms.filter(([platformId]) =>
        qrPlatformIds.includes(platformId)
    );
    const webLoginPlatforms = platforms.filter(([platformId]) =>
        webLoginPlatformIds.includes(platformId)
    );

    if (qrSelect) {
        qrSelect.innerHTML = qrPlatforms.map(([platformId, info]) =>
            `<option value="${platformId}">${escapeHtml(info.name || platformId)}</option>`
        ).join('');
        if (qrPlatforms.some(([platformId]) => platformId === currentQr)) {
            qrSelect.value = currentQr;
        }
    }

    if (bridgeSelect) {
        bridgeSelect.innerHTML = webLoginPlatforms.length
            ? webLoginPlatforms.map(([platformId, info]) =>
                `<option value="${platformId}">${escapeHtml(info.name || platformId)}（网页登录）</option>`
            ).join('')
            : '<option value="">暂无可用平台</option>';
        if (webLoginPlatforms.some(([platformId]) => platformId === currentBridge)) {
            bridgeSelect.value = currentBridge;
        }
    }
}

function renderSocialCreatorLinks(platforms) {
    const container = document.getElementById('social-creator-links');
    if (!container) return;

    const links = Object.entries(platforms)
        .filter(([, info]) => info.creator_url)
        .map(([, info]) =>
            `<a href="${escapeHtml(info.creator_url)}" target="_blank" class="btn btn-secondary" style="text-decoration: none;">${escapeHtml(info.name)}创作者入口</a>`
        );

    container.innerHTML = links.join('');
}

function cleanLogSummary(text) {
    return String(text || '')
        .replace(/\x1b\[[0-9;]*m/g, '')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 120);
}

function renderLogPlatformFilter(platforms) {
    const select = document.getElementById('log-platform-filter');
    if (!select) return;

    const currentValue = select.value;
    const entries = Object.entries(platforms);
    select.innerHTML = '<option value="">全部</option>' + entries.map(([platformId, info]) =>
        `<option value="${platformId}">${escapeHtml(info.name || platformId)}</option>`
    ).join('');

    if (!currentValue) {
        return;
    }

    if (entries.some(([platformId]) => platformId === currentValue)) {
        select.value = currentValue;
    }
}

function getCliPlatformEntries() {
    return Object.entries(getSocialPlatformsConfig().platforms || {}).filter(([platformId]) => isCliSupported(platformId));
}

function renderSocialPlatformUi(config) {
    setSocialPlatformsConfig(config);
    const platforms = socialPlatformsConfig.platforms || {};
    renderAccountEntrySelects(Object.entries(platforms));
    renderSocialCreatorLinks(platforms);
    renderLogPlatformFilter(platforms);
}

async function loadSocialConfig() {
    try {
        const [cliStatus, accounts, platformsConfig, categories, jobs] = await Promise.all([
            api('GET', '/social/cli-status'),
            api('GET', '/social/accounts'),
            api('GET', '/social/platforms/config'),
            api('GET', '/social/bilibili-categories'),
            api('GET', '/jobs')
        ]);

        renderSocialPlatformUi(platformsConfig);

        console.log('[Social] accounts loaded:', accounts);
        displayCliStatus(cliStatus);
        displayAccounts(accounts);
        loadRecoverableQrLogins();
        window.socialAccounts = accounts;

        const tidSelect = document.getElementById('upload-tid');
        tidSelect.innerHTML = categories.categories.map(c =>
            `<option value="${c.id}">${c.name}</option>`
        ).join('');

        const uploadJobSelect = document.getElementById('upload-job-select');
        window.publishJobs = jobs;
        uploadJobSelect.innerHTML = jobs.map(j =>
            `<option value="${j.id}">${escapeHtml(formatJobDisplayName(j, { includeStatus: true }))}</option>`
        ).join('');
        updateUploadVideoTypeOptions(uploadJobSelect.value);
        if (uploadJobSelect.value) {
            await loadPublishDraft(uploadJobSelect.value);
        }
    } catch (err) {
        console.error('Failed to load social config:', err);
    }
}

window.loadRecoverableQrLogins = async function() {
    console.log('[QR] loading recoverable logins...');
    try {
        const recoverable = await api('GET', '/social/qr-login/recoverable?limit=5');
        console.log('[QR] recoverable items:', recoverable.items);
        displayRecoverableQrLogins(recoverable.items || []);
    } catch (err) {
        console.error('[QR] Failed to load recoverable qr logins:', err);
        displayRecoverableQrLogins([]);
    }
}

function displayRecoverableQrLogins(items) {
    const panel = document.getElementById('qr-recovery-panel');
    const list = document.getElementById('qr-recovery-list');

    if (!items || items.length === 0) {
        panel.style.display = 'none';
        list.innerHTML = '';
        return;
    }

    panel.style.display = 'block';
    list.innerHTML = items.map(item => `
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:8px 0; border-top:1px dashed rgba(154,52,18,0.2);">
            <div>
                <strong>${escapeHtml(getSocialPlatformName(item.platform))}</strong>
                <span style="margin-left:8px;">临时登录: ${escapeHtml(item.temp_account)}</span>
                <span style="margin-left:8px; color:#b45309;">${new Date(item.modified_at).toLocaleString()}</span>
            </div>
            <div style="display:flex; gap:8px;">
                <button class="btn btn-secondary btn-sm" onclick="resumeRecoveredQrLogin('${item.platform}', '${escapeHtml(item.temp_account)}')">继续保存</button>
                <button class="btn btn-danger btn-sm" onclick="deleteRecoverableQrLogin('${item.platform}', '${escapeHtml(item.temp_account)}', '${escapeHtml(item.session_id || '')}')">删除</button>
            </div>
        </div>
    `).join('');
}

function displayCliStatus(status) {
    const container = document.getElementById('cli-status-result');
    if (!status.cli_help_works) {
        container.innerHTML = '<div class="message message-error">social-auto-upload CLI 不可用，请检查配置</div>';
        return;
    }

    const cliEntries = getCliPlatformEntries();
    if (cliEntries.length === 0) {
        container.innerHTML = '<div class="message message-warning">暂无支持 CLI 的平台</div>';
        return;
    }

    const platformIcons = cliEntries.map(([platformId, info]) => {
        const cliName = info.cli_name || platformId;
        const currentStatus = status.platforms[cliName] || 'unavailable';
        return `<span style="margin-right: 10px;">${escapeHtml(info.name || platformId)}: <strong style="color:${currentStatus === 'available' ? 'green' : 'red'}">${currentStatus}</strong></span>`;
    }).join('');

    container.innerHTML = `<div class="message message-success">CLI 可用 ${platformIcons}</div>`;
}

function displayAccounts(accounts) {
    const tbody = document.querySelector('#accounts-table tbody');
    const accountSelect = document.getElementById('upload-account-select');
    const checkAllBtn = document.getElementById('check-all-accounts-btn');

    if (accounts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#999;">暂无账号</td></tr>';
        accountSelect.innerHTML = '<option value="">请先添加账号</option>';
        if (checkAllBtn) checkAllBtn.disabled = true;
        return;
    }

    if (checkAllBtn) {
        checkAllBtn.disabled = !accounts.some(a => isCliSupported(a.platform) || isWebBridgeSupported(a.platform));
    }

    tbody.innerHTML = accounts.map(a => {
        const platformInfo = getSocialPlatformInfo(a.platform);
        const cliSupported = isCliSupported(a.platform);
        const bridgeSupported = isWebBridgeSupported(a.platform);
        
        return `
        <tr>
            <td>${escapeHtml(getSocialPlatformName(a.platform))}${bridgeSupported ? '<br><small style="color:#2563eb;">Web桥接发布</small>' : (!cliSupported ? '<br><small style="color:#999;">Web暂不支持</small>' : '')}</td>
            <td>${escapeHtml(a.account)}</td>
            <td>${escapeHtml(a.label || '-')}</td>
            <td>
                <span class="status-badge status-${a.last_check_status === 'valid' ? 'video_processed' : a.last_check_status === 'invalid' ? 'error' : 'created'}">
                    ${a.last_check_status || 'unknown'}
                </span>
            </td>
            <td>${a.last_check_at ? new Date(a.last_check_at).toLocaleString() : '-'}</td>
            <td>
                ${(cliSupported || bridgeSupported) ? `<button class="btn btn-secondary btn-sm" onclick="checkAccount('${a.id}', this)">检查</button>` : ''}
                ${cliSupported ? `<button class="btn btn-secondary btn-sm" onclick="startAccountQrLogin('${a.id}', this)">扫码登录</button>` : ''}
                ${bridgeSupported ? `<button class="btn btn-secondary btn-sm" onclick="prepareBridgeCookie('${a.id}', this)">网页登录</button>` : ''}
                ${a.platform === 'bilibili' ? `<button class="btn btn-secondary btn-sm" onclick="openLoginTerminal('${a.id}', this)">终端登录</button>` : ''}
                ${cliSupported ? `<button class="btn btn-secondary btn-sm" onclick="showLoginCmd('${a.id}')">登录</button>` : ''}
                ${a.last_check_status === 'valid' ? `<button class="btn btn-success btn-sm" onclick="openCreatorPage('${a.id}', this)">后台</button>` : ''}
                <button class="btn btn-danger btn-sm" onclick="deleteAccount('${a.id}')">删除</button>
            </td>
        </tr>
    `}).join('');

    accountSelect.innerHTML = accounts.map(a =>
        `<option value="${a.id}">${escapeHtml(getSocialPlatformName(a.platform))} - ${escapeHtml(a.account)}</option>`
    ).join('');
}

window.checkAccount = async function(accountId, btn = null) {
    const originalText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '检查中...';
    }
    try {
        const result = await api('POST', `/social/accounts/${accountId}/check`);
        const cleanOutput = (result.output || result.error || '').replace(/\x1b\[[0-9;]*m/g, '');
        if (result.status === 'valid') {
            window.notifySuccess(`账号检查通过: ${cleanOutput}`);
        } else {
            window.notifyWarning(`账号状态: ${result.status}\n${cleanOutput}`);
        }
        loadSocialConfig();
    } catch (err) {
        window.notifyError('检查失败: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
};

window.checkAllAccounts = async function(btn = null) {
    const accounts = (window.socialAccounts || []).filter(a =>
        isCliSupported(a.platform) || isWebBridgeSupported(a.platform)
    );
    const statusEl = document.getElementById('check-all-accounts-status');
    const originalText = btn ? btn.textContent : '';

    if (!accounts.length) {
        window.notifyWarning('暂无可检查的账号');
        return;
    }

    if (btn) {
        btn.disabled = true;
        btn.textContent = '检查中...';
    }
    if (statusEl) {
        statusEl.textContent = `0 / ${accounts.length}`;
    }

    let validCount = 0;
    let invalidCount = 0;
    const failed = [];

    for (let index = 0; index < accounts.length; index += 1) {
        const account = accounts[index];
        if (statusEl) {
            statusEl.textContent = `${index + 1} / ${accounts.length} 正在检查 ${getSocialPlatformName(account.platform)} - ${account.account}`;
        }

        try {
            const result = await api('POST', `/social/accounts/${account.id}/check`);
            if (result.status === 'valid') {
                validCount += 1;
            } else {
                invalidCount += 1;
                failed.push(`${getSocialPlatformName(account.platform)} - ${account.account}: ${result.status}`);
            }
        } catch (err) {
            invalidCount += 1;
            failed.push(`${getSocialPlatformName(account.platform)} - ${account.account}: ${err.message}`);
        }
    }

    if (statusEl) {
        statusEl.textContent = `完成：valid ${validCount}，异常 ${invalidCount}`;
    }
    if (failed.length) {
        window.notifyWarning(`一键检查完成：${validCount} 个有效，${invalidCount} 个异常\n${failed.slice(0, 8).join('\n')}`);
    } else {
        window.notifySuccess(`一键检查完成：${validCount} 个账号全部有效`);
    }

    await loadSocialConfig();

    if (btn) {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

window.openLoginTerminal = async function(accountId, btn = null) {
    const originalText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '打开中...';
    }
    try {
        const result = await api('POST', `/social/accounts/${accountId}/login-terminal`);
        if (result.status === 'skipped' && result.message) {
            window.notifyInfo(result.message);
        } else {
            window.notifyInfo(`已打开 ${result.terminal || '终端'}，请在终端里扫码登录；完成后回到网页点击“检查”。`);
        }
    } catch (err) {
        window.notifyError('打开终端失败: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
};

window.showLoginCmd = async function(accountId) {
    try {
        const result = await api('POST', `/social/accounts/${accountId}/login-command`);
        const account = (await api('GET', '/social/accounts')).find(a => a.id === accountId);

        if (account && account.platform === 'bilibili') {
            window.notifyInfo('Bilibili 登录请在本地终端执行命令');
        } else {
            if (confirm(`执行以下命令进行登录?\n\n${result.command}`)) {
                window.notifyInfo('请在本地终端执行上述命令');
            }
        }
    } catch (err) {
        window.notifyError('获取登录命令失败: ' + err.message);
    }
};

window.deleteAccount = async function(accountId) {
    if (!confirm('确定删除此账号?')) return;
    try {
        await api('DELETE', `/social/accounts/${accountId}`);
        loadSocialConfig();
        window.notifySuccess('账号已删除');
    } catch (err) {
        window.notifyError('删除失败: ' + err.message);
    }
};

window.openCreatorPage = async function(accountId, btn = null) {
    const originalText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '打开中...';
    }
    try {
        const result = await api('POST', `/social/accounts/${accountId}/open-creator`);
        window.notifySuccess(`已打开 ${result.platform} 创作者后台`);
    } catch (err) {
        window.notifyError('打开失败: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
};

window.selectJobFromLog = function(jobId) {
    selectJob(jobId);
    document.querySelector('[data-tab="process"]').click();
};

window.showUploadLogDetail = async function(recordId, target = 'logs') {
    if (target === 'logs') {
        const detailSelect = document.getElementById('log-detail-select');
        if (detailSelect) detailSelect.value = recordId;
    }
    if (target === 'social') {
        const detailSection = document.getElementById('upload-log-detail');
        if (detailSection) detailSection.style.display = 'block';
    }
    await loadUploadLogDetail(recordId, target);
};

async function loadUploadLogs() {
    const platform = document.getElementById('log-platform-filter')?.value || '';
    const status = document.getElementById('log-status-filter')?.value || '';
    const timeFilter = document.getElementById('log-time-filter')?.value || '';

    let days = null;
    if (timeFilter === 'today') days = 1;
    else if (timeFilter === 'week') days = 7;
    else if (timeFilter === 'month') days = 30;

    try {
        const records = await api('GET', `/social/upload-records?platform=${platform}&status=${status}${days ? '&days=' + days : ''}`);
        displayUploadLogs(records);
    } catch (err) {
        console.error('Failed to load upload logs:', err);
    }
}

function displayUploadLogs(records) {
    const tbody = document.querySelector('#upload-logs-table tbody');
    const detailSelect = document.getElementById('log-detail-select');

    if (records.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#999;">暂无发布记录</td></tr>';
        detailSelect.innerHTML = '<option value="">选择一条日志查看详情</option>';
        return;
    }

    tbody.innerHTML = records.map(r => `
        <tr style="${r.status === 'running' ? 'background: #eff6ff;' : (r.success ? '' : 'background: #fff3f3;')}">
            <td>${new Date(r.created_at).toLocaleString()}</td>
            <td>${r.job_id ? `<a href="#" onclick="selectJobFromLog('${r.job_id}')" style="color:#007bff;">${r.job_id.substring(0, 8)}</a>` : '-'}</td>
            <td>${escapeHtml(getSocialPlatformName(r.platform))}</td>
            <td>${escapeHtml(r.account_id || '')}</td>
            <td>${escapeHtml(r.title || '')}</td>
            <td>
                <span class="status-badge status-${r.status === 'running' ? 'processing' : (r.success ? 'video_processed' : 'error')}">
                    ${r.status === 'running' ? '进行中' : (r.success ? '成功' : '失败')}
                </span>
            </td>
            <td style="max-width:280px; color:${r.status === 'running' ? '#2563eb' : (r.success ? '#64748b' : '#b91c1c')};">
                ${escapeHtml(cleanLogSummary(r.error || r.output) || '-')}
            </td>
            <td>${r.url ? `<a href="${escapeHtml(r.url)}" target="_blank" style="color:#007bff;">查看</a>` : '-'}</td>
            <td>
                <button class="btn btn-secondary btn-sm" onclick="showUploadLogDetail('${r.id}', 'logs')">详情</button>
            </td>
        </tr>
    `).join('');

    detailSelect.innerHTML = '<option value="">选择一条日志查看详情</option>' +
        records.map(r =>
            `<option value="${r.id}">[${escapeHtml(getSocialPlatformName(r.platform))}] ${escapeHtml(r.title || r.job_id || r.id)} - ${r.status === 'running' ? '进行中' : (r.success ? '成功' : '失败')}</option>`
        ).join('');

    const currentValue = detailSelect.value;
    if (!currentValue && records[0]?.id) {
        detailSelect.value = records[0].id;
        loadUploadLogDetail(records[0].id, 'logs');
    }
}

async function loadUploadLogDetail(recordId, target = 'logs') {
    try {
        const log = await api('GET', `/social/upload-records/${recordId}`);
        const detailEl = document.getElementById(target === 'social' ? 'upload-log-detail-content' : 'log-detail-content');
        if (detailEl) {
            const clean = (text) => String(text || '').replace(/\x1b\[[0-9;]*m/g, '').trim();
            let content = log.log_content || '';
            if (!content && (log.output || log.error)) {
                content = `Output:\n${log.output || ''}\n\nError:\n${log.error || ''}`;
            }
            if (!content && log.video_path) {
                content = `Video Path:\n${log.video_path}\n\nStatus:\n${log.status || (log.success ? 'success' : 'failed')}`;
            }
            const summary = [
                `任务: ${log.job_id || '-'}`,
                `平台: ${getSocialPlatformName(log.platform || '')}`,
                `账号: ${log.account_id || '-'}`,
                `状态: ${log.status || (log.success ? 'success' : 'failed')}`,
                `文件: ${log.video_path || '-'}`,
                `错误: ${clean(log.error) || '-'}`,
            ].join('\n');
            const cleanedContent = clean(content);
            updateLogViewerContent(detailEl, `${summary}\n\n--- 原始日志 ---\n${cleanedContent || JSON.stringify(log, null, 2)}`);
        }
    } catch (err) {
        console.error('Failed to load log detail:', err);
    }
}

async function loadInlineUploadLog(jobId, platform, headerText = '') {
    const logViewer = document.getElementById('upload-log-viewer');
    if (!logViewer) return false;
    try {
        const result = await api('GET', `/social/jobs/${jobId}/upload-logs/${platform}`);
        const content = (result?.content || '').trim();
        if (content) {
            updateLogViewerContent(logViewer, `${headerText ? headerText + '\n\n' : ''}${content}`);
            logViewer.style.display = 'block';
            return { hasContent: true, content };
        }
        updateLogViewerContent(logViewer, headerText || '日志尚未生成，稍后会自动刷新...');
        logViewer.style.display = 'block';
        return { hasContent: false, content: '' };
    } catch (err) {
        updateLogViewerContent(logViewer, `${headerText ? headerText + '\n\n' : ''}读取日志失败：${err.message}`);
        logViewer.style.display = 'block';
        return { hasContent: false, content: '' };
    }
}

function startInlineUploadLogPolling(jobId, platform) {
    clearTimeout(window.inlineUploadLogTimer);
    let attempts = 0;
    let lastContent = null;
    let stableRounds = 0;
    const poll = async () => {
        attempts += 1;
        const header = `当前页日志预览：${getSocialPlatformName(platform)} 上传日志\n也可以切到“操作日志”标签查看完整记录。`;
        const result = await loadInlineUploadLog(jobId, platform, header);
        const currentContent = result?.content || '';

        if (currentContent && currentContent === lastContent) {
            stableRounds += 1;
        } else {
            stableRounds = 0;
        }
        lastContent = currentContent;

        const shouldContinue = attempts < 60 && (!result?.hasContent || stableRounds < 3);
        if (shouldContinue) {
            window.inlineUploadLogTimer = setTimeout(poll, result?.hasContent ? 1500 : 2000);
        }
    };
    poll();
}

function renderUploadModeOptions(selectedAccounts) {
    const modeSelect = document.getElementById('upload-mode');
    if (!modeSelect) return;

    const currentValue = modeSelect.value || '';
    const accounts = selectedAccounts || [];
    const supportsSchedule = accounts.length ? accounts.some(account => getSocialPlatformInfo(account.platform).need_schedule !== false) : true;
    const supportsDraft = accounts.length > 0 && accounts.every(account => isDraftSupported(account.platform));
    const options = [
        { value: '', label: '立即发布' },
    ];
    if (supportsSchedule) {
        options.push({ value: 'schedule', label: '定时发布' });
    }
    if (supportsDraft) {
        options.push({ value: 'draft', label: '保存草稿' });
    }

    modeSelect.innerHTML = options
        .map(option => `<option value="${option.value}">${escapeHtml(option.label)}</option>`)
        .join('');

    const nextValue = options.some(option => option.value === currentValue) ? currentValue : '';
    modeSelect.value = nextValue;
}

function renderUploadBatchProgress(records, selectedAccounts) {
    const resultDiv = document.getElementById('upload-result');
    if (!resultDiv) return;

    const accountMap = new Map((selectedAccounts || []).map(account => [account.id, account]));
    const stats = {
        queued: 0,
        running: 0,
        success: 0,
        failed: 0,
    };

    const rows = (records || []).map(record => {
        const account = accountMap.get(record.account_id);
        const platformName = getSocialPlatformName(record.platform || account?.platform || '');
        const accountName = account ? account.account : (record.account_id || '');
        const isQueued = record.status === 'queued';
        const isRunning = record.status === 'running';
        const isSuccess = !isQueued && !isRunning && Number(record.success) === 1;
        const isFailed = !isQueued && !isRunning && !isSuccess;
        if (isQueued) stats.queued += 1;
        else if (isRunning) stats.running += 1;
        else if (isSuccess) stats.success += 1;
        else stats.failed += 1;
        const summary = cleanLogSummary(record.error || record.output)
            || (isQueued ? '等待前面的账号发布完成...' : (isRunning ? '正在发布...' : (isSuccess ? '已完成' : '失败')));
        const color = isQueued ? '#64748b' : (isRunning ? '#2563eb' : (isSuccess ? '#15803d' : '#b91c1c'));
        const badgeClass = (isQueued || isRunning) ? 'processing' : (isSuccess ? 'video_processed' : 'error');
        const badgeText = isQueued ? '等待中' : (isRunning ? '进行中' : (isSuccess ? '成功' : '失败'));
        return `
            <div style="display:flex; justify-content:space-between; gap:12px; padding:10px 12px; border:1px solid #e5e7eb; border-radius:8px; background:${isFailed ? '#fff7f7' : (isRunning ? '#eff6ff' : (isQueued ? '#f8fafc' : '#f0fdf4'))};">
                <div style="min-width:0;">
                    <div style="font-weight:600;">${escapeHtml(platformName)} - ${escapeHtml(accountName)}</div>
                    <div style="margin-top:4px; color:${color}; word-break:break-word;">${escapeHtml(summary)}</div>
                </div>
                <div style="white-space:nowrap;">
                    <span class="status-badge status-${badgeClass}">${badgeText}</span>
                </div>
            </div>
        `;
    }).join('');

    const allDone = stats.queued === 0 && stats.running === 0 && (stats.success + stats.failed) > 0;
    const headerClass = allDone
        ? (stats.failed ? 'message message-warning' : 'message message-success')
        : 'message';
    const headerText = allDone
        ? (stats.failed
            ? `发布完成：成功 ${stats.success}，失败 ${stats.failed}`
            : `发布完成：${stats.success} 个账号全部成功`)
        : `发布中：成功 ${stats.success}，失败 ${stats.failed}，进行中 ${stats.running}，等待 ${stats.queued}`;

    resultDiv.innerHTML = `
        <div class="${headerClass}">
            <div style="font-weight:600; margin-bottom:10px;">${escapeHtml(headerText)}</div>
            <div style="display:grid; gap:10px;">${rows}</div>
        </div>
    `;
}

async function pollUploadBatchStatus(jobId, queuedRecords, selectedAccounts) {
    clearTimeout(window.uploadBatchStatusTimer);
    const recordIds = (queuedRecords || []).map(item => item.record_id).filter(Boolean);
    if (!recordIds.length) return;

    let attempts = 0;
    const poll = async () => {
        attempts += 1;
        try {
            const records = await Promise.all(
                recordIds.map(recordId => api('GET', `/social/upload-records/${recordId}`))
            );
            renderUploadBatchProgress(records, selectedAccounts);

            const activeRecord = records.find(record => record.status === 'running')
                || records.find(record => record.status === 'queued')
                || records.find(record => record.platform);
            if (activeRecord?.platform && window.currentInlineUploadLogKey !== `${jobId}:${activeRecord.platform}`) {
                window.currentInlineUploadLogKey = `${jobId}:${activeRecord.platform}`;
                startInlineUploadLogPolling(jobId, activeRecord.platform);
            }

            const hasPending = records.some(record => record.status === 'running' || record.status === 'queued');
            if (typeof loadJobs === 'function') {
                loadJobs();
            }
            loadUploadLogs();

            if (hasPending && attempts < 240) {
                window.uploadBatchStatusTimer = setTimeout(poll, 1500);
                return;
            }

            const failed = records.filter(record => record.status !== 'running' && record.status !== 'queued' && Number(record.success) !== 1);
            if (failed.length) {
                const summary = failed
                    .slice(0, 5)
                    .map(record => {
                        const account = selectedAccounts.find(item => item.id === record.account_id);
                        const name = account ? `${getSocialPlatformName(account.platform)} - ${account.account}` : record.account_id;
                        return `${name}: ${cleanLogSummary(record.error || record.output) || '失败'}`;
                    })
                    .join('\n');
                window.notifyWarning(`发布已结束，存在失败账号：\n${summary}`);
            } else {
                window.notifySuccess(`发布完成，${records.length} 个账号全部成功`);
            }
        } catch (err) {
            const resultDiv = document.getElementById('upload-result');
            if (resultDiv) {
                resultDiv.innerHTML = `<div class="message message-error">状态轮询失败: ${escapeHtml(err.message)}</div>`;
            }
        }
    };

    poll();
}

function updateUploadFormFields() {
    const selectedIds = getSelectedUploadAccountIds();
    
    const descGroup = document.getElementById('upload-desc')?.closest('.form-group');
    const tagsGroup = document.getElementById('upload-tags')?.closest('.form-group');
    const tagsNote = document.getElementById('upload-tags-note');
    const scheduleGroup = document.getElementById('schedule-time-group');
    const tidGroup = document.getElementById('bilibili-tid-group');
    
    if (!selectedIds.length) {
        renderUploadModeOptions([]);
        if (descGroup) descGroup.style.display = 'block';
        if (tagsGroup) tagsGroup.style.display = 'block';
        if (tagsNote) {
            tagsNote.textContent = '不同平台对标签要求不同；如果当前平台不需要标签，填写后也会自动忽略。';
            tagsNote.style.color = '';
        }
        if (scheduleGroup) scheduleGroup.style.display = 'none';
        if (tidGroup) tidGroup.style.display = 'none';
        const btn = document.getElementById('upload-video-btn');
        if (btn) {
            btn.textContent = '检查并发布';
            btn.disabled = false;
        }
        return;
    }
    
    const selectedAccounts = selectedIds
        .map(accountId => window.socialAccounts?.find(a => a.id === accountId))
        .filter(Boolean);
    if (!selectedAccounts.length) return;

    renderUploadModeOptions(selectedAccounts);
    
    const infos = selectedAccounts.map(account => getSocialPlatformInfo(account.platform));
    const noTagsPlatforms = selectedAccounts
        .filter(account => getSocialPlatformInfo(account.platform).need_tags === false)
        .map(account => getSocialPlatformName(account.platform));
    const requiresTags = infos.some(info => info.need_tags !== false);
    
    if (descGroup) descGroup.style.display = infos.some(info => info.need_desc !== false) ? 'block' : 'none';
    if (tagsGroup) tagsGroup.style.display = 'block';
    if (tagsNote) {
        if (!requiresTags && noTagsPlatforms.length) {
            tagsNote.textContent = `当前选中的平台无需输入标签：${noTagsPlatforms.join('、')}。你可以留空，填写后发布时也会自动忽略。`;
            tagsNote.style.color = '#64748b';
        } else if (noTagsPlatforms.length) {
            tagsNote.textContent = `部分平台无需标签：${noTagsPlatforms.join('、')}。这些平台会忽略你填写的标签，其它平台照常使用。`;
            tagsNote.style.color = '#64748b';
        } else {
            tagsNote.textContent = '当前选中的平台会使用这里填写的标签，多个标签请用逗号分隔。';
            tagsNote.style.color = '';
        }
    }
    const modeValue = document.getElementById('upload-mode')?.value || '';
    if (scheduleGroup) {
        scheduleGroup.style.display = (modeValue === 'schedule' && infos.some(info => info.need_schedule !== false)) ? 'flex' : 'none';
    }
    if (tidGroup) tidGroup.style.display = infos.some(info => info.need_tid) ? 'flex' : 'none';
    
    const btn = document.getElementById('upload-video-btn');
    if (btn) {
        const unsupported = selectedAccounts.filter(account => !isWebPublishSupported(account.platform));
        if (!unsupported.length) {
            const hasBridge = selectedAccounts.some(account => isWebBridgeSupported(account.platform));
            btn.textContent = selectedAccounts.length > 1
                ? `批量发布 ${selectedAccounts.length} 个账号`
                : (hasBridge ? '桥接发布' : '检查并发布');
            btn.disabled = false;
        } else {
            btn.textContent = '选中账号包含不支持 Web 发布的平台';
            btn.disabled = true;
        }
    }
}

function validatePublishTextFields(selectedAccounts, desc, tags) {
    const needsDesc = selectedAccounts.some(account => getSocialPlatformInfo(account.platform).need_desc !== false);
    const needsTags = selectedAccounts.some(account => getSocialPlatformInfo(account.platform).need_tags !== false);
    const missing = [];

    if (needsDesc && !String(desc || '').trim()) {
        missing.push('简介');
    }
    if (needsTags && !String(tags || '').trim()) {
        missing.push('标签');
    }
    if (!missing.length) {
        return true;
    }

    const platformNames = selectedAccounts
        .filter(account => {
            const info = getSocialPlatformInfo(account.platform);
            return (missing.includes('简介') && info.need_desc !== false)
                || (missing.includes('标签') && info.need_tags !== false);
        })
        .map(account => getSocialPlatformName(account.platform));
    window.notifyWarning(`请先填写${missing.join('和')}。当前选择的平台会使用这些内容：${[...new Set(platformNames)].join('、')}`);

    const focusId = missing.includes('简介') ? 'upload-desc' : 'upload-tags';
    const focusEl = document.getElementById(focusId);
    if (focusEl) {
        focusEl.focus();
    }
    return false;
}

function validatePublishPlatformFields(selectedAccounts, tid) {
    const needTidAccounts = selectedAccounts.filter(account => getSocialPlatformInfo(account.platform).need_tid);
    if (!needTidAccounts.length || String(tid || '').trim()) {
        return true;
    }

    const platformNames = [...new Set(needTidAccounts.map(account => getSocialPlatformName(account.platform)))];
    window.notifyWarning(`请选择${platformNames.join('、')}分区`);
    const tidEl = document.getElementById('upload-tid');
    if (tidEl) {
        tidEl.focus();
    }
    return false;
}

function updateUploadTitleCount() {
    const input = document.getElementById('upload-title');
    const counter = document.getElementById('upload-title-count');
    if (!input || !counter) return;
    const count = Array.from(input.value || '').length;
    counter.textContent = `${count} 字`;
    if (count >= 30) {
        counter.style.color = '#dc2626';
    } else if (count >= 24) {
        counter.style.color = '#d97706';
    } else {
        counter.style.color = '#64748b';
    }
}

function resolveUploadVideoOptions(job) {
    return [
        {
            value: 'final_replace_audio_subtitled',
            label: 'TTS 与合成 - 带配音+字幕',
            path: job?.final_replace_audio || '',
        },
        {
            value: 'final_subtitles_video',
            label: '视频合成（原声路线）- 原声字幕版',
            path: job?.final_subtitles_video || '',
        },
        {
            value: 'processed',
            label: '视频处理 - 原处理视频',
            path: job?.processed_video || '',
        },
    ];
}

function updateUploadVideoTypeOptions(jobId) {
    const select = document.getElementById('upload-video-type');
    if (!select) return;

    const currentValue = select.value;
    const job = (window.publishJobs || []).find(item => item.id === jobId);
    const options = resolveUploadVideoOptions(job);
    const available = options.filter(item => item.path);

    select.innerHTML = options.map(item => {
        const disabled = item.path ? '' : 'disabled';
        const suffix = item.path ? '' : '（未生成）';
        return `<option value="${item.value}" ${disabled}>${item.label}${suffix}</option>`;
    }).join('');

    if (job?.final_replace_audio) {
        select.value = 'final_replace_audio_subtitled';
    } else if (available.some(item => item.value === currentValue)) {
        select.value = currentValue;
    } else if (job?.final_subtitles_video) {
        select.value = 'final_subtitles_video';
    } else if (available.length) {
        select.value = available[0].value;
    }

    // 更新版本提示标签
    updateVideoTypeBadge(select.value, options);
}

function isTtsUploadVideoType(videoType) {
    return videoType === 'final_replace_audio_subtitled';
}

function getUploadVideoTypeLabel(job, videoType) {
    return resolveUploadVideoOptions(job).find(item => item.value === videoType)?.label || videoType || '未选择';
}

function updateVideoTypeBadge(value, options) {
    const badge = document.getElementById('upload-video-type-badge');
    const select = document.getElementById('upload-video-type');
    const option = options?.find(item => item.value === value);

    if (!option || !option.path) {
        if (badge) badge.style.display = 'none';
        if (select) {
            select.style.background = '';
            select.style.borderColor = '';
        }
        return;
    }

    // TTS版本用橙色高亮提醒
    if (value === 'final_replace_audio_subtitled') {
        if (badge) {
            badge.textContent = '🎙️ TTS配音版';
            badge.style.display = 'inline-block';
            badge.style.background = '#fed7aa';
            badge.style.color = '#c2410c';
            badge.style.border = '1px solid #fb923c';
        }
        if (select) {
            select.style.background = '#fff7ed';
            select.style.borderColor = '#fb923c';
        }
    } else if (value === 'final_subtitles_video') {
        if (badge) {
            badge.textContent = '🔊 原声字幕版';
            badge.style.display = 'inline-block';
            badge.style.background = '#dbeafe';
            badge.style.color = '#1d4ed8';
            badge.style.border = '1px solid #93c5fd';
        }
        if (select) {
            select.style.background = '#eff6ff';
            select.style.borderColor = '#93c5fd';
        }
    } else {
        if (badge) {
            badge.textContent = '📹 原处理视频';
            badge.style.display = 'inline-block';
            badge.style.background = '#f3f4f6';
            badge.style.color = '#374151';
            badge.style.border = '1px solid #d1d5db';
        }
        if (select) {
            select.style.background = '#f9fafb';
            select.style.borderColor = '#d1d5db';
        }
    }
}

function getSelectedUploadVideoPath(job) {
    const videoType = document.getElementById('upload-video-type')?.value;
    if (videoType === 'final_replace_audio_subtitled') return job?.final_replace_audio || '';
    if (videoType === 'final_subtitles_video') return job?.final_subtitles_video || '';
    return job?.processed_video || '';
}

function getJobDownloadFilename(path) {
    const value = (path || '').trim();
    if (!value) return '';
    return value.split('/').pop();
}

function getCurrentPublishJob(jobId = null) {
    const currentJobId = jobId || document.getElementById('upload-job-select')?.value;
    return (window.publishJobs || []).find(item => item.id === currentJobId);
}

function getSelectedUploadAccountIds() {
    const select = document.getElementById('upload-account-select');
    if (!select) return [];
    return Array.from(select.selectedOptions || [])
        .map(option => option.value)
        .filter(Boolean);
}

function setSelectedUploadAccountIds(accountIds) {
    const select = document.getElementById('upload-account-select');
    if (!select) return;
    const selected = new Set((accountIds || []).filter(Boolean));
    Array.from(select.options || []).forEach(option => {
        option.selected = selected.has(option.value);
    });
}

function renderCoverVideoPicker(jobId) {
    const picker = document.getElementById('upload-cover-video-picker');
    if (!picker) return;
    const job = getCurrentPublishJob(jobId);
    const videoPath = getSelectedUploadVideoPath(job);
    const filename = getJobDownloadFilename(videoPath);
    if (!jobId || !filename) {
        picker.innerHTML = '<div class="field-note">当前视频版本还没有可预览的视频文件。</div>';
        return;
    }
    picker.innerHTML = `
        <video id="upload-cover-video" src="${jobFileUrl(jobId, filename)}" controls style="width:100%; max-width:360px; max-height:260px; border-radius:6px; border:1px solid #ddd; background:#111; object-fit:contain;"></video>
        <div class="field-note">拖动视频到想要的画面后，点击“用当前画面截封面”。</div>
    `;
}

function renderUploadThumbnailPreview(jobId, thumbnail) {
    const preview = document.getElementById('upload-thumbnail-preview');
    if (!preview) return;
    const value = (thumbnail || '').trim();
    if (!value) {
        preview.innerHTML = '';
        return;
    }
    if (value.startsWith('/')) {
        preview.innerHTML = '<div class="field-note">已设置绝对路径封面，发布时会自动传递。</div>';
        return;
    }
    const imgUrl = jobFileUrl(jobId, value, Date.now());
    preview.innerHTML = `
        <img src="${imgUrl}" alt="封面预览" style="max-width:150px; max-height:96px; border-radius:6px; border:1px solid #ddd; object-fit:cover; cursor:pointer;" onclick="showThumbnailPreview('${imgUrl}', '${escapeHtml(value)}')">
        <div class="field-note" style="margin-top:4px;">点击图片可放大预览</div>
    `;
}

window.showThumbnailPreview = function(imgUrl, filename) {
    const modalEl = document.getElementById('thumbnail-preview-modal');
    if (!modalEl) {
        const modalHtml = `
            <div id="thumbnail-preview-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:10001; justify-content:center; align-items:center;">
                <div style="position:relative; max-width:90%; max-height:90%;">
                    <img id="thumbnail-preview-modal-img" style="max-width:100%; max-height:90vh; border-radius:8px; box-shadow:0 4px 20px rgba(0,0,0,0.5);">
                    <div id="thumbnail-preview-modal-info" style="text-align:center; color:white; margin-top:12px; font-size:14px;"></div>
                    <button onclick="closeThumbnailPreview()" style="position:absolute; top:-40px; right:0; background:none; border:none; color:white; font-size:28px; cursor:pointer; padding:8px; line-height:1;">&times;</button>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
    }
    const modalImg = document.getElementById('thumbnail-preview-modal-img');
    const modalInfo = document.getElementById('thumbnail-preview-modal-info');
    if (modalImg) modalImg.src = imgUrl;
    if (modalInfo) modalInfo.textContent = filename;
    const modal = document.getElementById('thumbnail-preview-modal');
    if (modal) {
        modal.style.display = 'flex';
        modal.onclick = function(e) {
            if (e.target === modal) closeThumbnailPreview();
        };
    }
};

window.closeThumbnailPreview = function() {
    const modal = document.getElementById('thumbnail-preview-modal');
    if (modal) modal.style.display = 'none';
};

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeThumbnailPreview();
});

function collectPublishDraft() {
    const accountIds = getSelectedUploadAccountIds();
    return {
        video_type: document.getElementById('upload-video-type')?.value || '',
        account_id: accountIds[0] || '',
        account_ids: accountIds,
        title: document.getElementById('upload-title')?.value || '',
        desc: document.getElementById('upload-desc')?.value || '',
        tags: document.getElementById('upload-tags')?.value || '',
        thumbnail: document.getElementById('upload-thumbnail')?.value || '',
        thumbnail_text: document.getElementById('upload-thumbnail-text')?.value || '',
        thumbnail_time: document.getElementById('upload-thumbnail-time')?.value || '',
        thumbnail_font_size: document.getElementById('upload-thumbnail-font-size')?.value || 'medium',
        thumbnail_font_color: document.getElementById('upload-thumbnail-font-color')?.value || '#ffffff',
        mode: document.getElementById('upload-mode')?.value || '',
        schedule: document.getElementById('upload-schedule')?.value || '',
        tid: document.getElementById('upload-tid')?.value || '',
    };
}

function resetPublishDraftForm(jobId = null) {
    const defaults = {
        'upload-title': '',
        'upload-desc': '',
        'upload-tags': '',
        'upload-thumbnail': '',
        'upload-thumbnail-text': '',
        'upload-thumbnail-time': '',
        'upload-thumbnail-font-size': 'medium',
        'upload-thumbnail-font-color': '#ffffff',
        'upload-mode': '',
        'upload-schedule': '',
    };

    Object.entries(defaults).forEach(([elementId, value]) => {
        const el = document.getElementById(elementId);
        if (el) {
            el.value = value;
        }
    });

    updateUploadTitleCount();
    updateUploadFormFields();
    renderCoverVideoPicker(jobId || document.getElementById('upload-job-select')?.value);
    renderUploadThumbnailPreview(jobId || document.getElementById('upload-job-select')?.value, '');
}

function applyPublishDraft(draft) {
    if (!draft || Object.keys(draft).length === 0) {
        resetPublishDraftForm(document.getElementById('upload-job-select')?.value);
        return;
    }
    const fieldMap = {
        video_type: 'upload-video-type',
        title: 'upload-title',
        desc: 'upload-desc',
        tags: 'upload-tags',
        thumbnail: 'upload-thumbnail',
        thumbnail_text: 'upload-thumbnail-text',
        thumbnail_time: 'upload-thumbnail-time',
        thumbnail_font_size: 'upload-thumbnail-font-size',
        thumbnail_font_color: 'upload-thumbnail-font-color',
        mode: 'upload-mode',
        schedule: 'upload-schedule',
        tid: 'upload-tid',
    };
    Object.entries(fieldMap).forEach(([key, elementId]) => {
        const el = document.getElementById(elementId);
        if (el && draft[key] !== undefined && draft[key] !== null) {
            el.value = draft[key];
        }
    });
    setSelectedUploadAccountIds(draft.account_ids || (draft.account_id ? [draft.account_id] : []));
    updateUploadTitleCount();
    updateUploadFormFields();
    const job = getCurrentPublishJob();
    updateVideoTypeBadge(document.getElementById('upload-video-type')?.value, resolveUploadVideoOptions(job));
    renderCoverVideoPicker(document.getElementById('upload-job-select')?.value);
    renderUploadThumbnailPreview(document.getElementById('upload-job-select')?.value, draft.thumbnail || '');
}

function clearPublishVariants() {
    window.latestPublishVariants = null;
    const wrapper = document.getElementById('publish-content-variants');
    const list = document.getElementById('publish-content-variant-list');
    if (wrapper) wrapper.style.display = 'none';
    if (list) list.innerHTML = '';
}

async function loadPublishDraft(jobId) {
    if (!jobId) return;
    clearPublishVariants();
    resetPublishDraftForm(jobId);
    try {
        const draft = await api('GET', `/publish-settings/drafts/${jobId}`);
        applyPublishDraft(draft);
    } catch (err) {
        console.error('Failed to load publish draft:', err);
    } finally {
        renderCoverVideoPicker(jobId);
        loadExistingAICovers(jobId);
    }
}

async function saveCurrentPublishDraft(showMessage = false) {
    const jobId = document.getElementById('upload-job-select')?.value;
    if (!jobId) return;
    const draft = collectPublishDraft();
    await api('POST', `/publish-settings/drafts/${jobId}`, draft);
    if (showMessage) {
        const resultDiv = document.getElementById('upload-result');
        if (resultDiv) {
            resultDiv.innerHTML = '<div class="message message-success">发布内容已保存，下次选择这个任务会自动恢复。</div>';
        }
    }
}

function schedulePublishDraftSave() {
    clearTimeout(window.publishDraftSaveTimer);
    window.publishDraftSaveTimer = setTimeout(() => {
        saveCurrentPublishDraft(false).catch(err => console.error('Failed to auto-save publish draft:', err));
    }, 500);
}

document.addEventListener('DOMContentLoaded', function() {
    const jobSelect = document.getElementById('upload-job-select');
    if (jobSelect) {
        jobSelect.addEventListener('change', async () => {
            updateUploadVideoTypeOptions(jobSelect.value);
            await loadPublishDraft(jobSelect.value);
        });
    }

    const accountSelect = document.getElementById('upload-account-select');
    if (accountSelect) {
        accountSelect.addEventListener('change', () => {
            updateUploadFormFields();
            schedulePublishDraftSave();
        });
    }
    
    const uploadBtn = document.getElementById('upload-video-btn');
    if (uploadBtn) {
        uploadBtn.addEventListener('click', handleUploadClick);
    }

    const previewUploadBtn = document.getElementById('preview-upload-btn');
    if (previewUploadBtn) {
        previewUploadBtn.addEventListener('click', handlePreviewUploadClick);
    }

    const generateBtn = document.getElementById('generate-content-btn');
    if (generateBtn) {
        generateBtn.addEventListener('click', generatePublishContent);
    }

    const saveDraftBtn = document.getElementById('save-publish-draft-btn');
    if (saveDraftBtn) {
        saveDraftBtn.addEventListener('click', async () => {
            const originalText = saveDraftBtn.textContent;
            saveDraftBtn.disabled = true;
            saveDraftBtn.textContent = '保存中...';
            try {
                await saveCurrentPublishDraft(true);
            } catch (err) {
                const resultDiv = document.getElementById('upload-result');
                if (resultDiv) {
                    resultDiv.innerHTML = `<div class="message message-error">发布内容保存失败: ${escapeHtml(err.message)}</div>`;
                }
                window.notifyError('发布内容保存失败: ' + err.message);
            } finally {
                saveDraftBtn.disabled = false;
                saveDraftBtn.textContent = originalText;
            }
        });
    }

    const checkAllAccountsBtn = document.getElementById('check-all-accounts-btn');
    if (checkAllAccountsBtn) {
        checkAllAccountsBtn.addEventListener('click', () => checkAllAccounts(checkAllAccountsBtn));
    }

    const coverBtn = document.getElementById('generate-cover-btn');
    if (coverBtn) {
        coverBtn.addEventListener('click', generateCoverFromSelectedVideo);
    }

    const currentFrameBtn = document.getElementById('use-current-frame-btn');
    if (currentFrameBtn) {
        currentFrameBtn.addEventListener('click', () => {
            const video = document.getElementById('upload-cover-video');
            if (!video) {
                window.notifyWarning('当前视频版本还没有可预览的视频文件');
                return;
            }
            const timeInput = document.getElementById('upload-thumbnail-time');
            if (timeInput) {
                timeInput.value = (video.currentTime || 0).toFixed(3);
            }
            generateCoverFromSelectedVideo();
        });
    }

    const uploadCoverBtn = document.getElementById('upload-cover-file-btn');
    const uploadCoverInput = document.getElementById('upload-thumbnail-file');
    if (uploadCoverBtn && uploadCoverInput) {
        uploadCoverBtn.addEventListener('click', () => uploadCoverInput.click());
        uploadCoverInput.addEventListener('change', uploadCoverFile);
    }

    const textCoverBtn = document.getElementById('generate-text-cover-btn');
    if (textCoverBtn) {
        textCoverBtn.addEventListener('click', generateTextCover);
    }

    const geminiPwBtn = document.getElementById('generate-gemini-pw-btn');
    if (geminiPwBtn) {
        geminiPwBtn.addEventListener('click', () => generateAICoverPlaywright('gemini'));
    }

    const chatgptPwBtn = document.getElementById('generate-chatgpt-pw-btn');
    if (chatgptPwBtn) {
        chatgptPwBtn.addEventListener('click', () => generateAICoverPlaywright('chatgpt'));
    }

    const titleInput = document.getElementById('upload-title');
    if (titleInput) {
        titleInput.addEventListener('input', updateUploadTitleCount);
        titleInput.addEventListener('change', updateUploadTitleCount);
        updateUploadTitleCount();
    }

    [
        'upload-video-type',
        'upload-title',
        'upload-desc',
        'upload-tags',
        'upload-thumbnail',
        'upload-thumbnail-text',
        'upload-thumbnail-time',
        'upload-thumbnail-font-size',
        'upload-thumbnail-font-color',
        'upload-mode',
        'upload-schedule',
        'upload-tid',
    ].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', schedulePublishDraftSave);
            el.addEventListener('change', schedulePublishDraftSave);
            if (id === 'upload-mode') {
                el.addEventListener('change', updateUploadFormFields);
            }
        }
    });

    const videoTypeSelect = document.getElementById('upload-video-type');
    if (videoTypeSelect) {
        videoTypeSelect.addEventListener('change', () => {
            const jobId = document.getElementById('upload-job-select')?.value;
            const job = (window.publishJobs || []).find(item => item.id === jobId);
            const options = resolveUploadVideoOptions(job);
            updateVideoTypeBadge(videoTypeSelect.value, options);
            renderCoverVideoPicker(jobId);
        });
    }
});

window.handleUploadClick = async function() {
    const jobId = document.getElementById('upload-job-select')?.value;
    const videoType = document.getElementById('upload-video-type')?.value;
    const accountIds = getSelectedUploadAccountIds();
    const title = document.getElementById('upload-title')?.value.trim();
    const desc = document.getElementById('upload-desc')?.value.trim();
    const tags = document.getElementById('upload-tags')?.value.trim();
    const thumbnail = document.getElementById('upload-thumbnail')?.value.trim();
    const mode = document.getElementById('upload-mode')?.value;
    const schedule = document.getElementById('upload-schedule')?.value;
    const tid = document.getElementById('upload-tid')?.value;
    
    if (!jobId || !accountIds.length || !title) {
        window.notifyWarning('请填写必填项：任务、账号、标题');
        return;
    }

    const currentJob = getCurrentPublishJob(jobId);
    if (!isTtsUploadVideoType(videoType)) {
        const videoTypeName = getUploadVideoTypeLabel(currentJob, videoType);
        if (!confirm(`当前选择的视频版本不是 TTS 配音版：${videoTypeName}\n\n请确认这是你要发布的版本。是否继续发布？`)) {
            return;
        }
    }

    const selectedAccounts = accountIds
        .map(accountId => window.socialAccounts?.find(a => a.id === accountId))
        .filter(Boolean);
    if (selectedAccounts.length !== accountIds.length) {
        window.notifyError('账号未找到');
        return;
    }

    if (!validatePublishTextFields(selectedAccounts, desc, tags)) {
        return;
    }

    if (!validatePublishPlatformFields(selectedAccounts, tid)) {
        return;
    }

    const unsupported = selectedAccounts.filter(account => !isWebPublishSupported(account.platform));
    if (unsupported.length) {
        const names = unsupported.map(account => `${getSocialPlatformName(account.platform)} - ${account.account}`).join('、');
        window.notifyWarning(`以下账号暂不支持 Web 发布：${names}`);
        return;
    }

    try {
        const records = await api('GET', `/social/jobs/${jobId}/upload-records`);
        const published = (records || []).filter(record =>
            accountIds.includes(record.account_id) &&
            Number(record.success) === 1 &&
            record.status !== 'running'
        );
        if (published.length) {
            const summary = published.slice(0, 8).map(record => {
                const account = selectedAccounts.find(item => item.id === record.account_id);
                const accountName = account ? `${getSocialPlatformName(account.platform)} - ${account.account}` : record.account_id;
                const publishedAt = record.created_at ? new Date(record.created_at).toLocaleString() : '未知时间';
                return `${accountName}（${publishedAt}）`;
            }).join('\n');
            const more = published.length > 8 ? `\n... 还有 ${published.length - 8} 条` : '';
            if (!confirm(`这个任务已经成功发布到以下账号：\n${summary}${more}\n\n是否重新发布这些账号？`)) {
                return;
            }
        }
    } catch (err) {
        if (!confirm(`检查历史发布记录失败：${err.message}\n\n是否继续发布？`)) {
            return;
        }
    }
    
    const btn = document.getElementById('upload-video-btn');
    btn.disabled = true;
    btn.textContent = accountIds.length > 1 ? '批量发布中...' : '发布中...';
    
    const resultDiv = document.getElementById('upload-result');
    const logViewer = document.getElementById('upload-log-viewer');
    if (logViewer) {
        logViewer.style.display = 'block';
        logViewer.textContent = '正在准备上传日志...';
    }
    if (resultDiv) resultDiv.innerHTML = `<div class="message">正在提交 ${accountIds.length} 个账号的发布任务...</div>`;
    
    try {
        await saveCurrentPublishDraft(false);
        const jobs = await api('GET', '/jobs');
        window.publishJobs = jobs;
        const job = jobs.find(j => j.id === jobId);
        
        let videoPath = '';
        if (videoType === 'final_replace_audio_subtitled') videoPath = job?.final_replace_audio;
        else if (videoType === 'final_subtitles_video') videoPath = job?.final_subtitles_video;
        else videoPath = job?.processed_video;
        
        if (!videoPath) {
            const videoTypeName = resolveUploadVideoOptions(job).find(item => item.value === videoType)?.label || videoType;
            throw new Error(`未找到可上传的视频文件：${videoTypeName} 尚未生成`);
        }

        if (thumbnail && !thumbnail.startsWith('/')) {
            const filename = getJobDownloadFilename(thumbnail);
            if (!filename) {
                throw new Error('封面图路径无效，请重新生成或清空封面图');
            }
        }
        
        const payload = {
            job_id: jobId,
            account_ids: accountIds,
            video_path: videoPath,
            title: title,
            desc: desc,
            tags: tags,
            thumbnail: thumbnail,
            publish_mode: mode || '',
            schedule: mode === 'schedule' ? schedule : '',
            tid: tid
        };
        
        const result = await api('POST', `/social/upload/batch`, payload);
        
        if (resultDiv) {
            if (result.status === 'queued') {
                const accountSummary = selectedAccounts.map(account =>
                    `${getSocialPlatformName(account.platform)} - ${account.account}`
                ).join('、');
                resultDiv.innerHTML = `<div class="message message-success">已提交 ${result.count || accountIds.length} 个账号的批量发布，将按选择顺序依次启动：${escapeHtml(accountSummary)}</div>`;
                loadUploadLogs();
                if (typeof loadJobs === 'function') {
                    loadJobs();
                }
                if (result.records?.[0]?.record_id) {
                    showUploadLogDetail(result.records[0].record_id, 'social');
                }
                const firstPlatform = result.records?.[0]?.platform || selectedAccounts[0]?.platform;
                if (firstPlatform) {
                    window.currentInlineUploadLogKey = `${jobId}:${firstPlatform}`;
                    startInlineUploadLogPolling(jobId, firstPlatform);
                }
                pollUploadBatchStatus(jobId, result.records || [], selectedAccounts);
            } else if (result.success) {
                resultDiv.innerHTML = '<div class="message message-success">发布成功！</div>';
                if (typeof loadJobs === 'function') {
                    loadJobs();
                }
                loadUploadLogs();
            } else {
                resultDiv.innerHTML = `<div class="message message-error">发布失败: ${escapeHtml(result.error || '未知错误')}</div>`;
                if (typeof loadJobs === 'function') {
                    loadJobs();
                }
            }
        }
        
    } catch (err) {
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-error">发布失败: ${err.message}</div>`;
        }
    } finally {
        if (btn) {
            btn.disabled = false;
        }
        updateUploadFormFields();
    }
};

window.handlePreviewUploadClick = async function() {
    const jobId = document.getElementById('upload-job-select')?.value;
    const videoType = document.getElementById('upload-video-type')?.value;
    const accountIds = getSelectedUploadAccountIds();
    const title = document.getElementById('upload-title')?.value.trim();
    const desc = document.getElementById('upload-desc')?.value.trim();
    const tags = document.getElementById('upload-tags')?.value.trim();
    const thumbnail = document.getElementById('upload-thumbnail')?.value.trim();
    const tid = document.getElementById('upload-tid')?.value;

    if (!jobId || !accountIds.length || !title) {
        window.notifyWarning('请填写必填项：任务、账号、标题');
        return;
    }

    if (accountIds.length > 1) {
        window.notifyWarning('预上传每次只能选择一个账号');
        return;
    }

    const currentJob = getCurrentPublishJob(jobId);
    if (!isTtsUploadVideoType(videoType)) {
        const videoTypeName = getUploadVideoTypeLabel(currentJob, videoType);
        if (!confirm(`当前选择的视频版本不是 TTS 配音版：${videoTypeName}\n\n请确认这是你要上传的版本。是否继续？`)) {
            return;
        }
    }

    const selectedAccount = window.socialAccounts?.find(a => a.id === accountIds[0]);
    if (!selectedAccount) {
        window.notifyError('账号未找到');
        return;
    }

    if (!validatePublishTextFields([selectedAccount], desc, tags)) {
        return;
    }

    if (!validatePublishPlatformFields([selectedAccount], tid)) {
        return;
    }

    if (!isWebPublishSupported(selectedAccount.platform)) {
        window.notifyWarning(`${getSocialPlatformName(selectedAccount.platform)} 暂不支持 Web 发布`);
        return;
    }

    const btn = document.getElementById('preview-upload-btn');
    const originalText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '上传中...';
    }

    const resultDiv = document.getElementById('upload-result');
    const logViewer = document.getElementById('upload-log-viewer');
    if (logViewer) {
        logViewer.style.display = 'block';
        logViewer.textContent = '正在准备上传日志...';
    }
    if (resultDiv) resultDiv.innerHTML = `<div class="message">正在上传视频到 ${getSocialPlatformName(selectedAccount.platform)}，将保存为草稿...</div>`;

    try {
        await saveCurrentPublishDraft(false);
        const jobs = await api('GET', '/jobs');
        window.publishJobs = jobs;
        const job = jobs.find(j => j.id === jobId);

        let videoPath = '';
        if (videoType === 'final_replace_audio_subtitled') videoPath = job?.final_replace_audio;
        else if (videoType === 'final_subtitles_video') videoPath = job?.final_subtitles_video;
        else videoPath = job?.processed_video;

        if (!videoPath) {
            const videoTypeName = resolveUploadVideoOptions(job).find(item => item.value === videoType)?.label || videoType;
            throw new Error(`未找到可上传的视频文件：${videoTypeName} 尚未生成`);
        }

        if (thumbnail && !thumbnail.startsWith('/')) {
            const filename = getJobDownloadFilename(thumbnail);
            if (!filename) {
                throw new Error('封面图路径无效，请重新生成或清空封面图');
            }
        }

        const payload = {
            account_id: accountIds[0],
            video_path: videoPath,
            title: title,
            desc: desc,
            tags: tags,
            thumbnail: thumbnail,
            tid: tid
        };

        const result = await api('POST', `/social/upload/preview?job_id=${jobId}`, payload);

        if (resultDiv) {
            if (result.status === 'queued') {
                resultDiv.innerHTML = `<div class="message message-success">
                    预上传任务已提交到 ${getSocialPlatformName(selectedAccount.platform)}<br>
                    视频将保存为草稿，你可去平台后台检查效果后再手动发布<br>
                    请等待上传完成后查看下方日志确认结果
                </div>`;
                loadUploadLogs();
                if (typeof loadJobs === 'function') {
                    loadJobs();
                }
                if (result.record_id) {
                    showUploadLogDetail(result.record_id, 'social');
                }
                startInlineUploadLogPolling(jobId, selectedAccount.platform);
            } else {
                resultDiv.innerHTML = `<div class="message message-success">预览上传完成！请在打开的浏览器页面中检查，确认后手动点击发布按钮。</div>`;
            }
        }
        window.notifySuccess('预览上传任务已提交，浏览器将打开发布页面，请检查后手动发布');

    } catch (err) {
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-error">预上传失败: ${escapeHtml(err.message)}</div>`;
        }
        window.notifyError('预上传失败: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
        updateUploadFormFields();
    }
};

window.prepareBridgeCookie = async function(accountId, btn = null) {
    const originalText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '启动中...';
    }
    try {
        const result = await api('POST', `/social/accounts/${accountId}/prepare-cookie`);
        window.notifyInfo(`网页登录已启动。浏览器会打开，请完成登录；登录成功后会自动保存并关闭。日志: ${result.log_file}`);
        pollBridgeLoginStatus(accountId);
    } catch (err) {
        window.notifyError('启动网页登录失败: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
};

async function pollBridgeLoginStatus(accountId, attempts = 0) {
    if (attempts >= 120) {
        window.notifyWarning('网页登录仍未确认完成，如已登录但窗口未关闭，请稍后点“检查”刷新状态');
        loadSocialConfig();
        return;
    }
    try {
        const accounts = await api('GET', '/social/accounts');
        const account = accounts.find(item => item.id === accountId);
        if (account?.last_check_status === 'valid') {
            window.notifySuccess(`${getSocialPlatformName(account.platform)} 网页登录已完成`);
            loadSocialConfig();
            return;
        }
        if (account?.last_check_status === 'invalid' && attempts > 3) {
            window.notifyWarning(`${getSocialPlatformName(account.platform)} 网页登录未完成或已失败，请重新网页登录`);
            loadSocialConfig();
            return;
        }
    } catch (err) {
        console.error('Failed to poll bridge login status:', err);
    }
    setTimeout(() => pollBridgeLoginStatus(accountId, attempts + 1), 3000);
}

window.generateCoverFromSelectedVideo = async function() {
    const jobId = document.getElementById('upload-job-select')?.value;
    const timestamp = document.getElementById('upload-thumbnail-time')?.value.trim();
    const coverText = document.getElementById('upload-thumbnail-text')?.value.trim();
    const fontSize = document.getElementById('upload-thumbnail-font-size')?.value || 'medium';
    const fontColor = document.getElementById('upload-thumbnail-font-color')?.value || '#ffffff';
    const btn = document.getElementById('generate-cover-btn');
    const resultDiv = document.getElementById('upload-result');
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    if (!timestamp) {
        window.notifyWarning('请输入封面时间点，例如 0:03 或 3.5');
        return;
    }

    const job = (window.publishJobs || []).find(item => item.id === jobId) || await api('GET', `/jobs/${jobId}`);
    const videoPath = getSelectedUploadVideoPath(job);
    if (!videoPath) {
        window.notifyWarning('当前视频版本还没有可截取的视频文件');
        return;
    }

    const originalText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '截取中...';
    }
    try {
        const result = await api('POST', `/social/jobs/${jobId}/cover-frame`, {
            video_path: videoPath,
            timestamp,
            title: coverText || '',
            font_size: fontSize,
            font_color: fontColor,
        });
        const thumbnailInput = document.getElementById('upload-thumbnail');
        if (thumbnailInput) {
            thumbnailInput.value = result.thumbnail || '';
        }
        renderUploadThumbnailPreview(jobId, result.thumbnail || '');
        await saveCurrentPublishDraft(false);
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-success">封面已生成：${escapeHtml(result.thumbnail || '')}</div>`;
        }
        window.notifySuccess('封面已从视频截取' + (coverText ? '，已添加文字' : ''));
    } catch (err) {
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-error">截取封面失败: ${escapeHtml(err.message)}</div>`;
        }
        window.notifyError('截取封面失败: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
};

window.uploadCoverFile = async function() {
    const jobId = document.getElementById('upload-job-select')?.value;
    const fileInput = document.getElementById('upload-thumbnail-file');
    const file = fileInput?.files?.[0];
    const resultDiv = document.getElementById('upload-result');
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    if (!file) {
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    try {
        const headers = {};
        const token = getApiToken();
        if (token) headers['X-Token'] = token;
        const res = await fetch(`${API_BASE}/social/jobs/${encodeURIComponent(jobId)}/cover-file`, {
            method: 'POST',
            headers,
            body: formData,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(formatApiErrorDetail(err.detail));
        }
        const result = await res.json();
        const thumbnailInput = document.getElementById('upload-thumbnail');
        if (thumbnailInput) {
            thumbnailInput.value = result.thumbnail || '';
        }
        renderUploadThumbnailPreview(jobId, result.thumbnail || '');
        await saveCurrentPublishDraft(false);
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-success">封面已上传：${escapeHtml(result.thumbnail || '')}</div>`;
        }
        window.notifySuccess('封面文件已上传');
    } catch (err) {
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-error">上传封面失败: ${escapeHtml(err.message)}</div>`;
        }
        window.notifyError('上传封面失败: ' + err.message);
    } finally {
        if (fileInput) {
            fileInput.value = '';
        }
    }
};

window.generateTextCover = async function() {
    const jobId = document.getElementById('upload-job-select')?.value;
    const thumbnail = document.getElementById('upload-thumbnail')?.value.trim();
    const text = document.getElementById('upload-thumbnail-text')?.value.trim();
    const fontSize = document.getElementById('upload-thumbnail-font-size')?.value || 'medium';
    const fontColor = document.getElementById('upload-thumbnail-font-color')?.value || '#ffffff';
    const btn = document.getElementById('generate-text-cover-btn');
    const resultDiv = document.getElementById('upload-result');
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    if (!thumbnail) {
        window.notifyWarning('请先截取或上传一张封面底图');
        return;
    }
    if (!text) {
        window.notifyWarning('请输入要打到封面上的文字');
        return;
    }

    const originalText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '生成中...';
    }
    try {
        const result = await api('POST', `/social/jobs/${jobId}/cover-text`, {
            thumbnail,
            text,
            font_size: fontSize,
            font_color: fontColor,
        });
        const thumbnailInput = document.getElementById('upload-thumbnail');
        if (thumbnailInput) {
            thumbnailInput.value = result.thumbnail || '';
        }
        renderUploadThumbnailPreview(jobId, result.thumbnail || '');
        await saveCurrentPublishDraft(false);
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-success">文字封面已生成：${escapeHtml(result.thumbnail || '')}</div>`;
        }
        window.notifySuccess('文字封面已生成');
    } catch (err) {
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-error">生成文字封面失败: ${escapeHtml(err.message)}</div>`;
        }
        window.notifyError('生成文字封面失败: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
};

window.generatePublishContent = async function() {
    const jobId = document.getElementById('upload-job-select')?.value;
    if (!jobId) {
        window.notifyWarning('请先选择一个任务');
        return;
    }
    
    const btn = document.getElementById('generate-content-btn');
    const resultDiv = document.getElementById('upload-result');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '生成中...';
    if (resultDiv) {
        resultDiv.innerHTML = '<div class="message">正在根据当前任务字幕生成标题、简介和标签...</div>';
    }
    
    try {
        const result = await api('POST', '/publish-settings/generate', { job_id: jobId });

        renderPublishVariants(result);
        applyPublishVariant(result.recommended_style || 'single', result);
        await saveCurrentPublishDraft(false);
        
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-success">
                生成完成！${result.subtitle_source ? `来源：${escapeHtml(result.subtitle_source)}<br>` : ''}
                已生成 ${Object.keys(result.versions || {}).length || 1} 套版本，当前已自动填入：${escapeHtml((result.versions?.[result.recommended_style || 'single']?.label) || '推荐版本')}<br>
                标题：${escapeHtml(result.title || '')}<br>
                标签：${escapeHtml((result.tags || []).join(', '))}
            </div>`;
        }
    } catch (err) {
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-error">生成失败: ${escapeHtml(err.message)}</div>`;
        }
        window.notifyError('生成失败: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

function applyPublishVariant(styleKey, payload = window.latestPublishVariants) {
    if (!payload) return;
    const versions = payload.versions || {};
    const variant = versions[styleKey] || payload;
    if (!variant) return;

    document.getElementById('upload-title').value = variant.title || '';
    document.getElementById('upload-desc').value = variant.description || '';
    document.getElementById('upload-tags').value = (variant.tags || []).join(',');
    updateUploadTitleCount();

    document.querySelectorAll('[data-publish-variant]').forEach(card => {
        const isActive = card.dataset.publishVariant === styleKey;
        card.style.borderColor = isActive ? '#2563eb' : '#cbd5e1';
        card.style.boxShadow = isActive ? '0 0 0 2px rgba(37,99,235,0.15)' : 'none';
    });
}
window.applyPublishVariant = applyPublishVariant;

function renderPublishVariants(payload) {
    window.latestPublishVariants = payload;
    const wrapper = document.getElementById('publish-content-variants');
    const list = document.getElementById('publish-content-variant-list');
    if (!wrapper || !list) return;

    const versions = payload?.versions || {};
    const entries = Object.entries(versions);
    if (!entries.length) {
        wrapper.style.display = 'none';
        list.innerHTML = '';
        return;
    }

    wrapper.style.display = 'block';
    list.innerHTML = entries.map(([styleKey, item]) => `
        <div data-publish-variant="${escapeHtml(styleKey)}" style="border:1px solid #cbd5e1; border-radius:10px; padding:12px; background:#fff;">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px;">
                <strong>${escapeHtml(item.label || styleKey)}</strong>
                <button class="btn btn-secondary btn-sm" type="button" onclick="applyPublishVariant('${escapeHtml(styleKey)}')">使用这版</button>
            </div>
            <div style="font-size:14px; line-height:1.5;">
                <div style="font-weight:600; margin-bottom:6px;">${escapeHtml(item.title || '')}</div>
                <div style="color:#475569; margin-bottom:8px; white-space:pre-wrap;">${escapeHtml(item.description || '')}</div>
                <div style="color:#64748b;">${escapeHtml((item.tags || []).join('，'))}</div>
            </div>
        </div>
    `).join('');

    applyPublishVariant(payload.recommended_style || entries[0][0], payload);
}

// ============== AI 封面图生成功能 ==============

window.generateAICover = async function() {
    const jobId = document.getElementById('upload-job-select')?.value;
    const title = document.getElementById('upload-title')?.value.trim();
    const desc = document.getElementById('upload-desc')?.value.trim();
    const btn = document.getElementById('generate-ai-cover-btn');
    const resultDiv = document.getElementById('upload-result');

    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    if (!title) {
        window.notifyWarning('请先输入视频标题');
        return;
    }

    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'AI 生成中...';

    if (resultDiv) {
        resultDiv.innerHTML = '<div class="message">正在打开浏览器生成 AI 封面...</div><div class="help-panel" style="background:#fff3cd; border-color:#ffc107; margin-top:8px;"><strong>提示：</strong>如果浏览器弹出，请确保已登录 Gemini/ChatGPT。浏览器将会保持打开状态，可以手动保存图片。</div>';
    }

    try {
        const result = await api('POST', `/social/jobs/${jobId}/ai-cover/generate`, {
            title: title,
            description: desc || '',
            platforms: ['gemini', 'chatgpt'],
        });

        renderAICoverImages(jobId, result.images || []);

        const count = result.images?.length || 0;
        if (resultDiv) {
            if (count > 0) {
                resultDiv.innerHTML = `<div class="message message-success">AI 封面已生成 ${count} 张，请选择一张作为封面</div>`;
            } else {
                resultDiv.innerHTML = `<div class="message message-error">AI 封面生成失败。如果需要登录，请在浏览器中登录后再重试。</div>`;
            }
        }

    } catch (err) {
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-error">AI 生成失败: ${escapeHtml(err.message)}</div>`;
        }
        window.notifyError('AI 生成失败: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

window.generateAICoverNodriver = async function(platform) {
    const jobId = document.getElementById('upload-job-select')?.value;
    const title = document.getElementById('upload-title')?.value.trim();
    const desc = document.getElementById('upload-desc')?.value.trim();
    const btn = document.getElementById(platform === 'gemini' ? 'generate-gemini-btn' : 'generate-chatgpt-btn');
    const resultDiv = document.getElementById('upload-result');

    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    if (!title) {
        window.notifyWarning('请先输入视频标题');
        return;
    }

    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = platform === 'gemini' ? 'Gemini 生成中...' : 'ChatGPT 生成中...';

    if (resultDiv) {
        resultDiv.innerHTML = `<div class="message">正在使用 ${platform === 'gemini' ? 'Gemini' : 'ChatGPT'} 生成封面...</div><div class="help-panel" style="background:#e0f2fe; border-color:#38bdf8; color:#0369a1; margin-top:8px;"><strong>提示：</strong>请确保 Chrome 已登录 ${platform === 'gemini' ? 'Gemini' : 'ChatGPT'}。如果未登录，浏览器会保持打开状态供你手动登录。</div>`;
    }

    try {
        const result = await api('POST', `/social/jobs/${jobId}/ai-cover/generate-nodriver`, {
            title: title,
            description: desc || '',
            platforms: [platform],
        });

        renderAICoverImages(jobId, result.images || []);

        const count = result.images?.length || 0;
        if (resultDiv) {
            if (count > 0) {
                resultDiv.innerHTML = `<div class="message message-success">${platform === 'gemini' ? 'Gemini' : 'ChatGPT'} 封面已生成 ${count} 张，请选择一张作为封面</div>`;
            } else {
                resultDiv.innerHTML = `<div class="message message-error">${platform === 'gemini' ? 'Gemini' : 'ChatGPT'} 封面生成失败，请检查 Chrome 是否已登录 ${platform === 'gemini' ? 'Gemini' : 'ChatGPT'}</div>`;
            }
        }

    } catch (err) {
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-error">${platform === 'gemini' ? 'Gemini' : 'ChatGPT'} 生成失败: ${escapeHtml(err.message)}</div>`;
        }
        window.notifyError(`${platform === 'gemini' ? 'Gemini' : 'ChatGPT'} 生成失败: ` + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

window.generateAICoverPlaywright = async function(platform) {
    const jobId = document.getElementById('upload-job-select')?.value;
    const title = document.getElementById('upload-title')?.value.trim();
    const desc = document.getElementById('upload-desc')?.value.trim();
    const btn = document.getElementById(platform === 'gemini' ? 'generate-gemini-pw-btn' : 'generate-chatgpt-pw-btn');
    const resultDiv = document.getElementById('upload-result');

    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    if (!title) {
        window.notifyWarning('请先输入视频标题');
        return;
    }

    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = platform === 'gemini' ? 'Gemini (PW) 生成中...' : 'ChatGPT (PW) 生成中...';

    if (resultDiv) {
        resultDiv.innerHTML = `<div class="message">正在使用 ${platform === 'gemini' ? 'Gemini (Playwright)' : 'ChatGPT (Playwright)'} 生成封面...</div><div class="help-panel" style="background:#f3e8ff; border-color:#c084fc; color:#7e22ce; margin-top:8px;"><strong>提示：</strong>请确保 Chrome 已登录 ${platform === 'gemini' ? 'Gemini' : 'ChatGPT'}。Playwright 版本使用更稳定的元素查找和点击机制。</div>`;
    }

    try {
        const result = await api('POST', `/social/jobs/${jobId}/ai-cover/generate-playwright`, {
            title: title,
            description: desc || '',
            platforms: [platform],
        });

        renderAICoverImages(jobId, result.images || []);

        const count = result.images?.length || 0;
        if (resultDiv) {
            if (count > 0) {
                resultDiv.innerHTML = `<div class="message message-success">${platform === 'gemini' ? 'Gemini (Playwright)' : 'ChatGPT (Playwright)'} 封面已生成 ${count} 张，请选择一张作为封面</div>`;
            } else {
                const errorMsg = result.error ? `<br><small style="color:#666">错误: ${escapeHtml(result.error)}</small>` : '';
                resultDiv.innerHTML = `<div class="message message-error">${platform === 'gemini' ? 'Gemini (Playwright)' : 'ChatGPT (Playwright)'} 封面生成失败，请检查 Chrome 是否已登录 ${platform === 'gemini' ? 'Gemini' : 'ChatGPT'}${errorMsg}</div>`;
            }
        }

    } catch (err) {
        if (resultDiv) {
            resultDiv.innerHTML = `<div class="message message-error">${platform === 'gemini' ? 'Gemini (Playwright)' : 'ChatGPT (Playwright)'} 生成失败: ${escapeHtml(err.message)}</div>`;
        }
        window.notifyError(`${platform === 'gemini' ? 'Gemini (Playwright)' : 'ChatGPT (Playwright)'} 生成失败: ` + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

function renderAICoverImages(jobId, images) {
    const container = document.getElementById('ai-cover-images');
    const section = document.getElementById('ai-cover-section');
    if (!container) return;

    if (section) {
        section.style.display = 'block';
    }

    if (!images || images.length === 0) {
        container.innerHTML = '<div class="field-note">点击"AI 生成封面"按钮开始生成</div>';
        return;
    }

    const token = getApiToken();

    container.innerHTML = `
        <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(160px, 1fr)); gap:12px; margin-top:8px;">
            ${images.map(img => {
                const ts = Date.now();
                const queryParams = token ? `?token=${encodeURIComponent(token)}&t=${ts}` : `?t=${ts}`;
                return `
                <div class="ai-cover-item"
                     style="border:2px solid transparent; border-radius:8px; overflow:hidden; cursor:pointer; transition:all 0.2s;"
                     data-filename="${escapeHtml(img.filename)}"
                     onclick="selectAICover('${jobId}', '${escapeHtml(img.filename)}', this)">
                    <img src="${API_BASE}/social/jobs/${encodeURIComponent(jobId)}/ai-cover/download/${encodeURIComponent(img.filename)}${queryParams}"
                         alt="${escapeHtml(img.platform)}"
                         style="width:100%; aspect-ratio:3/4; object-fit:cover;"
                         onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 133%22><rect fill=%22%23f0f0f0%22 width=%22100%22 height=%22133%22/><text x=%2250%22 y=%2266%22 text-anchor=%22middle%22 fill=%22%23999%22 font-size=%2212%22>图片加载失败</text></svg>'">
                    <div style="padding:6px; text-align:center; background:#f8fafc;">
                        <span style="display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; background:${img.platform === 'gemini' ? '#e0f2fe' : '#10a37f'}; color:${img.platform === 'gemini' ? '#0369a1' : '#fff'};">
                            ${img.platform === 'gemini' ? 'Gemini' : 'ChatGPT'}
                        </span>
                    </div>
                </div>
            `}).join('')}
        </div>
        <div class="field-note" style="margin-top:8px;">点击选择一张图片作为视频封面</div>
    `;
}

window.selectAICover = async function(jobId, filename, element) {
    try {
        const result = await api('POST', `/social/jobs/${jobId}/ai-cover/select`, {
            filename: filename,
        });

        document.querySelectorAll('.ai-cover-item').forEach(item => {
            item.style.borderColor = 'transparent';
        });
        if (element) {
            element.style.borderColor = '#2563eb';
        }

        const thumbnailInput = document.getElementById('upload-thumbnail');
        if (thumbnailInput) {
            thumbnailInput.value = result.thumbnail || '';
        }

        renderUploadThumbnailPreview(jobId, result.thumbnail || '');
        await saveCurrentPublishDraft(false);

        window.notifySuccess('已选择该图片作为封面');

    } catch (err) {
        window.notifyError('选择封面失败: ' + err.message);
    }
};

window.loadExistingAICovers = async function(jobId) {
    const section = document.getElementById('ai-cover-section');
    if (!section) return;

    try {
        const result = await api('GET', `/social/jobs/${jobId}/ai-cover/images`);
        if (result.images && result.images.length > 0) {
            renderAICoverImages(jobId, result.images);
        } else {
            const container = document.getElementById('ai-cover-images');
            if (container) {
                container.innerHTML = '<div class="field-note">点击"AI 生成封面"按钮开始生成</div>';
            }
        }
    } catch (err) {
        console.error('Failed to load existing AI covers:', err);
    }
};
