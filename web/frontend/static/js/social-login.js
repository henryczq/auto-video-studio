document.getElementById('qr-add-account-btn').addEventListener('click', async () => {
    const platform = document.getElementById('social-qr-platform').value;
    const account = '';
    if (platform === 'bilibili') {
        showBiliLoginModal(account);
        return;
    }
    showQrModal(platform, account);
    await startQrLogin(platform, account);
});

document.getElementById('bridge-add-account-btn').addEventListener('click', async () => {
    const platform = document.getElementById('social-bridge-platform').value;
    if (!platform) {
        window.notifyWarning('请先选择网页登录平台');
        return;
    }
    if (isBrowserLoginSupported(platform)) {
        showQrModal(platform, '');
        await startQrLogin(platform, '');
        return;
    }

    const alias = `auto_${platform}_${new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)}`;
    try {
        await api('POST', '/social/accounts', { platform, account: alias, label: '网页登录添加' });
    } catch (err) {
        window.notifyError('创建网页登录账号失败: ' + err.message);
        return;
    }

    try {
        const accounts = await api('GET', '/social/accounts');
        const account = accounts.find(item => item.platform === platform && item.account === alias);
        if (!account) {
            throw new Error('未能创建网页登录账号入口');
        }
        await window.prepareBridgeCookie(account.id);
        window.notifyInfo(`网页登录已启动，本地账号名已自动生成为 ${alias}`);
        loadSocialConfig();
    } catch (err) {
        window.notifyError('启动网页登录失败: ' + err.message);
    }
});

document.getElementById('qr-cancel-btn').addEventListener('click', hideQrModal);
document.getElementById('qr-confirm-btn').addEventListener('click', confirmQrAddAccount);

let qrExistingAccountMode = false;
let qrExistingAccountId = '';
let qrExistingAccountFinalizing = false;

function stopQrResultPolling() {
    if (qrResultPollTimer) {
        clearInterval(qrResultPollTimer);
        qrResultPollTimer = null;
    }
}

function startQrResultPolling() {
    stopQrResultPolling();
    qrResultPollTimer = setInterval(() => {
        void checkQrLoginResult();
    }, 1500);
}

async function tryRecoverQrLogin(platform = qrCurrentPlatform) {
    if (!platform) {
        return false;
    }
    if (qrExistingAccountMode || qrCurrentAccount) {
        return false;
    }
    try {
        const res = await api('GET', `/social/qr-login/recoverable?platform=${encodeURIComponent(platform)}&limit=1`);
        const candidate = (res.items || [])[0];
        if (!candidate) {
            return false;
        }
        if (!qrCurrentPlatform) {
            qrCurrentPlatform = candidate.platform;
        }
        if (!document.getElementById('qr-login-modal').style.display || document.getElementById('qr-login-modal').style.display === 'none') {
            showQrModal(candidate.platform, '');
        }
        qrRecoveryCandidate = candidate;
        document.getElementById('qr-account-display').textContent = `检测到待回填登录: ${candidate.temp_account}`;
        document.getElementById('qr-status').textContent = '已恢复上次登录结果，请填写保存名称';
        document.getElementById('qr-status').style.display = 'block';
        showQrLoginSuccess(true);
        return true;
    } catch (err) {
        console.error('Failed to recover qr login:', err);
        return false;
    }
}

async function checkQrLoginResult() {
    if (!qrCurrentSession || qrLoginSuccess) {
        return false;
    }
    try {
        const result = await api('GET', `/social/qr-login/result/${qrCurrentSession}`);
        if (result.type === 'qrcode') {
            document.getElementById('qrcode-loading').style.display = 'none';
            document.getElementById('qrcode-image').src = result.data;
            document.getElementById('qrcode-image').style.display = 'block';
            document.getElementById('qr-status').textContent = '浏览器已启动；如果浏览器里没显示二维码，可用这里的二维码继续登录';
            document.getElementById('qr-status').style.display = 'block';
            return false;
        }
        if (result.type === 'status') {
            document.getElementById('qrcode-loading').style.display = 'none';
            document.getElementById('qr-status').textContent = result.data || '请在弹出的浏览器窗口中完成扫码、验证码或二次确认';
            document.getElementById('qr-status').style.display = 'block';
            return false;
        }
        if (result.type === 'success') {
            showQrLoginSuccess();
            if (qrEventSource) {
                qrEventSource.close();
                qrEventSource = null;
            }
            return true;
        }
        if (result.type === 'pending') {
            document.getElementById('qr-status').textContent = '浏览器登录仍在进行，请继续在浏览器中完成';
            document.getElementById('qr-status').style.display = 'block';
            return false;
        }
        if (result.type === 'error') {
            if (await tryRecoverQrLogin()) {
                return true;
            }
            stopQrResultPolling();
            document.getElementById('qr-error').textContent = result.message || '登录失败';
            document.getElementById('qr-error').style.display = 'block';
            return true;
        }
    } catch (err) {
        if (await tryRecoverQrLogin()) {
            return true;
        }
        document.getElementById('qr-error').textContent = '连接中断';
        document.getElementById('qr-error').style.display = 'block';
    }
    return false;
}

function showQrModal(platform, account, options = {}) {
    const { existingAccountMode = false, existingAccountId = '' } = options;
    qrExistingAccountMode = existingAccountMode;
    qrExistingAccountId = existingAccountId;
    qrCurrentPlatform = platform;
    qrCurrentAccount = account;
    qrLoginSuccess = false;
    qrExistingAccountFinalizing = false;
    qrRecoveryCandidate = null;
    stopQrResultPolling();
    document.getElementById('qr-modal-title').textContent = '浏览器登录账号 - ' + getSocialPlatformName(platform);
    document.getElementById('qr-platform-display').textContent = '平台: ' + document.getElementById('qr-modal-title').textContent;
    document.getElementById('qr-account-display').textContent = qrExistingAccountMode
        ? `当前账号: ${account}`
        : (account ? ('预设保存名: ' + account) : '登录成功后再填写保存名称');
    document.getElementById('qrcode-loading').style.display = 'block';
    document.getElementById('qrcode-image').style.display = 'none';
    document.getElementById('qr-status').textContent = '正在启动浏览器登录...';
    document.getElementById('qr-status').style.display = 'block';
    document.getElementById('qr-status').style.color = '#666';
    document.getElementById('qr-error').style.display = 'none';
    document.getElementById('qr-confirm-btn').style.display = 'none';
    document.getElementById('qr-final-account').value = account || '';
    document.getElementById('qr-final-label').value = '';
    document.getElementById('qr-save-fields').style.display = 'none';
    document.getElementById('qr-login-modal').style.display = 'block';
}

function hideQrModal() {
    stopQrResultPolling();
    if (qrEventSource) {
        qrEventSource.close();
        qrEventSource = null;
    }
    qrCurrentSession = null;
    qrRecoveryCandidate = null;
    qrExistingAccountMode = false;
    qrExistingAccountId = '';
    qrExistingAccountFinalizing = false;
    document.getElementById('qr-login-modal').style.display = 'none';
}

async function finalizeExistingQrLogin() {
    if (qrExistingAccountFinalizing || !qrCurrentSession) {
        return;
    }
    qrExistingAccountFinalizing = true;
    document.getElementById('qr-status').textContent = '扫码完成，正在更新当前账号登录态...';
    document.getElementById('qr-status').style.display = 'block';
    try {
        await api('POST', '/social/qr-login/refresh-account', {
            session_id: qrCurrentSession,
        });
        window.notifySuccess('扫码登录成功，当前账号已更新');
        setTimeout(() => {
            hideQrModal();
            loadSocialConfig();
        }, 800);
    } catch (err) {
        qrExistingAccountFinalizing = false;
        document.getElementById('qr-error').textContent = '保存登录结果失败: ' + err.message;
        document.getElementById('qr-error').style.display = 'block';
        document.getElementById('qr-status').style.display = 'none';
    }
}

function showQrLoginSuccess(fromRecovery = false) {
    qrLoginSuccess = true;
    stopQrResultPolling();
    document.getElementById('qrcode-loading').style.display = 'none';
    document.getElementById('qr-error').style.display = 'none';
    document.getElementById('qr-status').textContent = qrExistingAccountMode
        ? '扫码登录成功，正在更新当前账号状态...'
        : (fromRecovery ? '已恢复登录结果!' : '登录成功!');
    document.getElementById('qr-status').style.color = 'green';
    document.getElementById('qr-status').style.display = 'block';
    if (qrExistingAccountMode) {
        document.getElementById('qr-save-fields').style.display = 'none';
        document.getElementById('qr-confirm-btn').style.display = 'none';
        void finalizeExistingQrLogin();
        return;
    }
    document.getElementById('qr-save-fields').style.display = 'block';
    document.getElementById('qr-confirm-btn').style.display = 'inline-block';
    document.getElementById('qr-confirm-btn').disabled = false;
    if (!document.getElementById('qr-final-account').value.trim()) {
        document.getElementById('qr-final-account').focus();
    }
}

async function startQrLogin(platform, account, options = {}) {
    const { force = false } = options;
    try {
        const res = await api('POST', '/social/qr-login/start', { platform, account, force });
        qrCurrentSession = res.session_id;
        qrCurrentAccount = account || res.temp_account || '';
        qrRecoveryCandidate = res.recovered_candidate || null;
        if (res.recovered) {
            document.getElementById('qrcode-loading').style.display = 'none';
            document.getElementById('qrcode-image').style.display = 'none';
            document.getElementById('qr-account-display').textContent = `检测到待回填登录: ${res.temp_account}`;
            showQrLoginSuccess(true);
        }
        document.getElementById('qrcode-loading').style.display = 'none';
        if (!res.recovered) {
            document.getElementById('qr-status').textContent = '浏览器已启动，请在浏览器窗口中继续登录';
            document.getElementById('qr-status').style.display = 'block';
        }
        const baseUrl = window.location.origin;
        const token = getApiToken();
        const streamUrl = new URL(`${baseUrl}/api/social/qr-login/stream/${qrCurrentSession}`);
        if (token) {
            streamUrl.searchParams.set('token', token);
        }
        qrEventSource = new EventSource(streamUrl.toString());
        startQrResultPolling();
        qrEventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'qrcode') {
                document.getElementById('qrcode-loading').style.display = 'none';
                document.getElementById('qrcode-image').src = data.data;
                document.getElementById('qrcode-image').style.display = 'block';
                document.getElementById('qr-status').textContent = '浏览器已启动；如果浏览器里没显示二维码，可用这里的二维码继续登录';
            } else if (data.type === 'status') {
                document.getElementById('qrcode-loading').style.display = 'none';
                document.getElementById('qr-status').textContent = data.data || '请在弹出的浏览器窗口中完成扫码、验证码或二次确认';
                document.getElementById('qr-status').style.display = 'block';
                if (!qrExistingAccountMode && ((data.data || '').includes('无需重新扫码') || (data.data || '').includes('已恢复待保存状态'))) {
                    showQrLoginSuccess((data.data || '').includes('已恢复待保存状态'));
                }
            } else if (data.type === 'success') {
                showQrLoginSuccess(Boolean(qrRecoveryCandidate));
                if (qrEventSource) {
                    qrEventSource.close();
                    qrEventSource = null;
                }
            } else if (data.type === 'error') {
                stopQrResultPolling();
                document.getElementById('qr-error').textContent = '错误: ' + data.message;
                document.getElementById('qr-error').style.display = 'block';
                document.getElementById('qr-status').style.display = 'none';
            }
        };
        qrEventSource.onerror = async () => {
            if (qrLoginSuccess) {
                return;
            }
            await checkQrLoginResult();
        };
    } catch (err) {
        stopQrResultPolling();
        document.getElementById('qr-error').textContent = '启动失败: ' + err.message;
        document.getElementById('qr-error').style.display = 'block';
        document.getElementById('qr-status').style.display = 'none';
    }
}

window.startAccountQrLogin = async function(accountId, btn = null) {
    const account = (window.socialAccounts || []).find(item => item.id === accountId);
    if (!account) {
        window.notifyError('账号未找到');
        return;
    }
    if (account.platform === 'bilibili') {
        showBiliLoginModal(account.account);
        return;
    }

    const originalText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '启动中...';
    }

    try {
        showQrModal(account.platform, account.account, {
            existingAccountMode: true,
            existingAccountId: accountId
        });
        document.getElementById('qr-account-display').textContent = `当前账号: ${account.account}`;
        document.getElementById('qr-final-account').value = account.account || '';
        document.getElementById('qr-final-label').value = account.label || '';
        document.getElementById('qr-save-fields').style.display = 'none';
        document.getElementById('qr-confirm-btn').style.display = 'none';
        document.getElementById('qr-status').textContent = '正在启动浏览器登录当前账号...';
        document.getElementById('qr-status').style.display = 'block';
        await startQrLogin(account.platform, account.account, { force: true });
    } catch (err) {
        qrExistingAccountMode = false;
        qrExistingAccountId = '';
        window.notifyError('启动扫码登录失败: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
};

async function confirmQrAddAccount() {
    if (!qrLoginSuccess) return;
    const finalAccount = document.getElementById('qr-final-account').value.trim();
    const finalLabel = document.getElementById('qr-final-label').value.trim();
    if (!finalAccount) {
        window.notifyWarning('请输入保存名称');
        return;
    }
    try {
        if (qrRecoveryCandidate && qrRecoveryCandidate.temp_account) {
            await api('POST', '/social/qr-login/recover-account', {
                platform: qrRecoveryCandidate.platform || qrCurrentPlatform,
                temp_account: qrRecoveryCandidate.temp_account,
                account: finalAccount,
                label: finalLabel
            });
        } else {
            await api('POST', '/social/qr-login/add-account', {
                session_id: qrCurrentSession,
                account: finalAccount,
                label: finalLabel
            });
        }
        window.notifySuccess('账号添加成功!');
        hideQrModal();
        loadSocialConfig();
    } catch (err) {
        if (qrRecoveryCandidate && (
            err.message.includes('待恢复的登录结果不存在')
            || err.message.includes('待恢复的登录结果已失效')
        )) {
            await loadRecoverableQrLogins();
            window.notifyWarning(err.message);
            return;
        }
        window.notifyError('添加失败: ' + err.message);
    }
}

window.resumeRecoveredQrLogin = async function(platform, tempAccount) {
    try {
        const res = await api('GET', `/social/qr-login/recoverable?platform=${encodeURIComponent(platform)}&limit=20`);
        const candidate = (res.items || []).find(item => item.temp_account === tempAccount);
        if (!candidate) {
            await loadRecoverableQrLogins();
            window.notifyWarning('这条临时登录结果已不存在或已失效，请重新扫码登录');
            return;
        }

        showQrModal(platform, '');
        qrRecoveryCandidate = {
            platform,
            temp_account: tempAccount,
            session_id: candidate.session_id || '',
        };
        document.getElementById('qr-account-display').textContent = `检测到待回填登录: ${tempAccount}`;
        showQrLoginSuccess(true);
    } catch (err) {
        window.notifyError('读取临时登录失败: ' + err.message);
    }
};

window.deleteRecoverableQrLogin = async function(platform, tempAccount, sessionId = '') {
    if (!confirm(`确定删除 ${platform} 的临时登录 ${tempAccount} 吗？`)) {
        return;
    }
    try {
        await api('DELETE', '/social/qr-login/recoverable', {
            platform,
            temp_account: tempAccount,
            session_id: sessionId || undefined,
        });
        loadRecoverableQrLogins();
        window.notifySuccess('临时登录已删除');
    } catch (err) {
        window.notifyError('删除失败: ' + err.message);
    }
};

document.getElementById('bili-cancel-btn').addEventListener('click', hideBiliLoginModal);
document.getElementById('bili-login-btn').addEventListener('click', doBiliLogin);
document.getElementById('bili-confirm-btn').addEventListener('click', confirmBiliAddAccount);
document.getElementById('bili-login-mode')?.addEventListener('change', updateBiliLoginModeUi);
document.getElementById('bili-read-browser-cookies-btn')?.addEventListener('click', readBiliBrowserCookies);

function getBiliLoginModeLabel(mode) {
    return {
        account_password: '账号密码',
        browser: '浏览器登录',
        web_cookie1: '网页 Cookie 登录 1',
        web_cookie2: '网页 Cookie 登录 2'
    }[mode] || '账号密码';
}

function updateBiliLoginModeUi() {
    const mode = document.getElementById('bili-login-mode')?.value || 'account_password';
    const needsCredentials = mode === 'account_password';
    const usernameGroup = document.getElementById('bili-username')?.closest('div');
    const passwordGroup = document.getElementById('bili-password')?.closest('div');
    const cookieFields = document.getElementById('bili-cookie-fields');
    if (usernameGroup) usernameGroup.style.display = needsCredentials ? 'block' : 'none';
    if (passwordGroup) passwordGroup.style.display = needsCredentials ? 'block' : 'none';
    if (cookieFields) cookieFields.style.display = mode.startsWith('web_cookie') ? 'block' : 'none';
    document.getElementById('bili-login-btn').textContent = needsCredentials ? '登录' : `启动${getBiliLoginModeLabel(mode)}`;
    document.getElementById('bili-status').textContent = needsCredentials
        ? '输入 B 站账号和密码后，后台会自动选择“账号密码”登录并提交。'
        : (
            mode.startsWith('web_cookie')
                ? '请从 bilibili.com 的浏览器 Cookie 中复制 SESSDATA 和 bili_jct，后台会自动填入 biliup。'
                : `后台会自动选择“${getBiliLoginModeLabel(mode)}”，并尝试弹出本机浏览器；如果没有弹出，会在失败详情里显示终端输出。`
        );
}

function showBiliLoginModal(account) {
    biliCurrentAccount = account;
    biliCurrentSession = null;
    biliCurrentAccount = account;
    biliCurrentSession = null;
    biliLoginSuccess = false;
    document.getElementById('bili-account-display').textContent = '账号名: ' + (account || '登录成功后再填写保存名称');
    document.getElementById('bili-username').value = '';
    document.getElementById('bili-password').value = '';
    document.getElementById('bili-sessdata').value = '';
    document.getElementById('bili-jct').value = '';
    document.getElementById('bili-status').style.display = 'block';
    document.getElementById('bili-status').style.color = '#666';
    document.getElementById('bili-error').style.display = 'none';
    document.getElementById('bili-login-btn').disabled = false;
    document.getElementById('bili-login-btn').style.display = 'inline-block';
    document.getElementById('bili-final-account').value = account || '';
    document.getElementById('bili-final-label').value = '';
    document.getElementById('bili-save-fields').style.display = 'none';
    document.getElementById('bili-confirm-btn').style.display = 'none';
    document.getElementById('bili-login-modal').style.display = 'block';

    api('GET', '/social/settings').then(settings => {
        const provider = settings.bilibili_provider || 'social-auto-upload';
        const modeSelect = document.getElementById('bili-login-mode');
        if (provider === 'bilibili-all-in-one') {
            if (modeSelect) {
                modeSelect.value = 'web_cookie1';
                modeSelect.style.display = 'none';
            }
            document.getElementById('bili-status').textContent = 'bilibili-all-in-one 模式：请从 bilibili.com 的浏览器 Cookie 中复制 SESSDATA 和 bili_jct。';
            document.getElementById('bili-login-btn').textContent = '验证并登录';
        } else {
            if (modeSelect) {
                modeSelect.value = 'account_password';
                modeSelect.style.display = '';
            }
            document.getElementById('bili-status').textContent = '输入 B 站账号和密码后，后台会自动选择账号密码登录并提交。';
            document.getElementById('bili-login-btn').textContent = '登录';
        }
        updateBiliLoginModeUi();
    }).catch(() => {
        document.getElementById('bili-login-mode').value = 'account_password';
        document.getElementById('bili-status').textContent = '输入 B 站账号和密码后，后台会自动选择账号密码登录并提交。';
        document.getElementById('bili-login-btn').textContent = '登录';
        updateBiliLoginModeUi();
    });
}

function hideBiliLoginModal() {
    biliCurrentAccount = null;
    biliCurrentSession = null;
    biliLoginSuccess = false;
    document.getElementById('bili-login-modal').style.display = 'none';
}

async function readBiliBrowserCookies() {
    const btn = document.getElementById('bili-read-browser-cookies-btn');
    const status = document.getElementById('bili-status');
    const error = document.getElementById('bili-error');
    btn.disabled = true;
    status.textContent = '正在读取本机浏览器里的 B 站 Cookie...';
    status.style.display = 'block';
    status.style.color = '#666';
    error.style.display = 'none';
    try {
        const result = await api('GET', '/social/bilibili/browser-cookies');
        if (!result.success) {
            error.textContent = result.message || '未能读取本机浏览器 Cookie';
            error.style.display = 'block';
            status.textContent = '如果浏览器 Cookie 被系统钥匙串加密，可以改用“浏览器登录”完成授权。';
            return;
        }
        document.getElementById('bili-login-mode').value = 'web_cookie1';
        document.getElementById('bili-sessdata').value = result.sessdata || '';
        document.getElementById('bili-jct').value = result.bili_jct || '';
        updateBiliLoginModeUi();
        status.textContent = '已从本机浏览器读取并回填 Cookie，可以点击“启动网页 Cookie 登录 1”。';
        status.style.color = 'green';
    } catch (err) {
        error.textContent = '读取失败: ' + err.message;
        error.style.display = 'block';
        status.textContent = '读取本机浏览器 Cookie 未完成。';
    } finally {
        btn.disabled = false;
    }
}

async function doBiliLogin() {
    const mode = document.getElementById('bili-login-mode')?.value || 'account_password';
    const modeLabel = getBiliLoginModeLabel(mode);
    const username = document.getElementById('bili-username').value.trim();
    const password = document.getElementById('bili-password').value;
    const sessdata = document.getElementById('bili-sessdata')?.value.trim() || '';
    const biliJct = document.getElementById('bili-jct')?.value.trim() || '';
    if (mode === 'account_password' && (!username || !password)) {
        document.getElementById('bili-error').textContent = '请输入用户名和密码';
        document.getElementById('bili-error').style.display = 'block';
        return;
    }
    if (mode.startsWith('web_cookie') && (!sessdata || !biliJct)) {
        document.getElementById('bili-error').textContent = '网页 Cookie 登录需要填写 SESSDATA 和 bili_jct';
        document.getElementById('bili-error').style.display = 'block';
        return;
    }
    const btn = document.getElementById('bili-login-btn');
    btn.disabled = true;
    document.getElementById('bili-status').textContent = mode === 'browser'
        ? '后台正在选择“浏览器登录”并尝试弹出本机浏览器，请稍候...'
        : `后台正在选择“${modeLabel}”并执行登录，请稍候...`;
    document.getElementById('bili-status').style.display = 'block';
    document.getElementById('bili-status').style.color = '#666';
    document.getElementById('bili-error').style.display = 'none';
    try {
        if (!biliCurrentSession) {
            const session = await api('POST', '/social/qr-login/start', {
                platform: 'bilibili',
                account: biliCurrentAccount
            });
            biliCurrentSession = session.session_id;
            if (!document.getElementById('bili-final-account').value.trim()) {
                document.getElementById('bili-final-account').value = biliCurrentAccount || '';
            }
        }
        const result = await api('POST', '/social/bilibili/login', {
            session_id: biliCurrentSession,
            username,
            password,
            mode,
            sessdata,
            bili_jct: biliJct
        });
        if (result.success) {
            biliLoginSuccess = true;
            biliCurrentAccount = result.account || biliCurrentAccount;
            document.getElementById('bili-status').textContent = '登录成功!';
            document.getElementById('bili-status').style.color = 'green';
            document.getElementById('bili-save-fields').style.display = 'block';
            document.getElementById('bili-confirm-btn').style.display = 'inline-block';
            document.getElementById('bili-confirm-btn').disabled = false;
            document.getElementById('bili-login-btn').style.display = 'none';
            if (!document.getElementById('bili-final-account').value.trim()) {
                document.getElementById('bili-final-account').value = username || result.account || '';
            }
        } else {
            const terminalOutput = result.terminal_output
                ? `\n\n终端输出：\n${result.terminal_output}`
                : '';
            document.getElementById('bili-error').textContent = '登录失败: ' + (result.message || '未知错误') + terminalOutput;
            document.getElementById('bili-error').style.display = 'block';
            document.getElementById('bili-status').textContent = result.requires_verification
                ? 'B 站要求验证码/二次验证，当前自动输入流程已停止。'
                : `${modeLabel}未完成，请检查提示后重试。`;
        }
    } catch (err) {
        document.getElementById('bili-error').textContent = '登录失败: ' + err.message;
        document.getElementById('bili-error').style.display = 'block';
    } finally {
        btn.disabled = false;
    }
}

async function confirmBiliAddAccount() {
    if (!biliLoginSuccess || !biliCurrentSession) return;
    const finalAccount = document.getElementById('bili-final-account').value.trim();
    const finalLabel = document.getElementById('bili-final-label').value.trim();
    if (!finalAccount) {
        document.getElementById('bili-error').textContent = '请输入保存名称';
        document.getElementById('bili-error').style.display = 'block';
        return;
    }
    try {
        await api('POST', '/social/qr-login/add-account', {
            session_id: biliCurrentSession,
            account: finalAccount,
            label: finalLabel
        });
        window.notifySuccess('账号添加成功!');
        hideBiliLoginModal();
        loadSocialConfig();
    } catch (err) {
        document.getElementById('bili-error').textContent = '保存失败: ' + err.message;
        document.getElementById('bili-error').style.display = 'block';
        window.notifyError('添加失败: ' + err.message);
    }
}
