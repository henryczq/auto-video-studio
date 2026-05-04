let ttsSettingsConfig = null;
let ttsSettingsLoaded = false;

function getTtsSettingsResultBox() {
    return document.getElementById('tts-settings-result');
}

function showTtsSettingsMessage(type, message) {
    const box = getTtsSettingsResultBox();
    if (!box) return;
    box.innerHTML = `<div class="message message-${type}">${escapeHtml(message)}</div>`;
}

function clearTtsSettingsMessage() {
    const box = getTtsSettingsResultBox();
    if (box) {
        box.innerHTML = '';
    }
}

function createEmptyRuntimeProfile() {
    return {
        label: '',
        python: '',
        rocm_gfx_override: ''
    };
}

function createEmptyModeProfile() {
    return {
        runtime_env: '',
        rocm_gfx_override: ''
    };
}

function ensureTtsSettingsShape(config) {
    const next = config || {};
    next.defaults = next.defaults || {};
    next.prompt_presets = next.prompt_presets || {};
    next.provider_defaults = next.provider_defaults || {};
    next.mode_defaults = next.mode_defaults || {};
    next.runtime_envs = next.runtime_envs || {};
    ['cosyvoice', 'indextts2'].forEach(provider => {
        next.runtime_envs[provider] = next.runtime_envs[provider] || {};
        next.mode_defaults[provider] = next.mode_defaults[provider] || {};
        next.provider_defaults[provider] = next.provider_defaults[provider] || {};
    });
    return next;
}

function renderTtsSettingsForm() {
    if (!ttsSettingsConfig) return;
    const defaults = ttsSettingsConfig.defaults || {};

    document.getElementById('tts-settings-default-provider').value = defaults.tts_provider || '';
    document.getElementById('tts-settings-default-runtime-env').value = defaults.tts_runtime_env || '';
    document.getElementById('tts-settings-default-mode').value = defaults.tts_mode || '';
    document.getElementById('tts-settings-default-model').value = defaults.tts_model || '';
    document.getElementById('tts-settings-default-device').value = defaults.device || '';
    document.getElementById('tts-settings-default-gfx').value = defaults.rocm_gfx_override || '';
    document.getElementById('tts-settings-default-threads').value = defaults.tts_threads ?? 4;
    document.getElementById('tts-settings-default-executor').value = defaults.tts_executor || 'batched';
    document.getElementById('tts-settings-default-parallel').value = defaults.tts_parallel ?? 2;
    document.getElementById('tts-settings-default-prompt-text').value = defaults.tts_prompt_text || '';
    document.getElementById('tts-settings-default-cosy-style').value = defaults.tts_cosyvoice_style_text || '';
    document.getElementById('tts-settings-default-indextts-emo').value = defaults.tts_indextts2_emo_text || '';

    renderTtsSettingsPresets();
    renderTtsSettingsRuntimeGroups();
    renderTtsSettingsProviderDefaults();
    renderTtsSettingsModeGroups();
    updateTtsSettingsJson();
}

function renderTtsSettingsPresets() {
    const tbody = document.querySelector('#tts-settings-presets-table tbody');
    if (!tbody) return;
    const presets = ttsSettingsConfig.prompt_presets || {};
    const rows = Object.entries(presets);

    tbody.innerHTML = rows.map(([key, value], index) => `
        <tr data-preset-index="${index}">
            <td><input class="tts-settings-table-input" data-preset-field="key" value="${escapeHtml(key)}"></td>
            <td><textarea class="tts-settings-table-textarea" data-preset-field="value">${escapeHtml(value)}</textarea></td>
            <td><button class="btn btn-danger btn-sm" type="button" data-remove-preset="${index}">删除</button></td>
        </tr>
    `).join('') || '<tr><td colspan="3" style="color:#667085;">暂无预设，可点击上方“新增预设”。</td></tr>';
}

function renderTtsSettingsRuntimeGroups() {
    const container = document.getElementById('tts-settings-runtime-groups');
    if (!container) return;
    const runtimeEnvs = ttsSettingsConfig.runtime_envs || {};

    container.innerHTML = Object.entries(runtimeEnvs).map(([provider, envs]) => {
        const rows = Object.entries(envs || {}).map(([envName, profile], index) => `
            <tr data-runtime-provider="${escapeHtml(provider)}" data-runtime-index="${index}">
                <td><input class="tts-settings-table-input" data-runtime-field="name" value="${escapeHtml(envName)}"></td>
                <td><input class="tts-settings-table-input" data-runtime-field="label" value="${escapeHtml(profile.label || '')}"></td>
                <td><input class="tts-settings-table-input" data-runtime-field="python" value="${escapeHtml(profile.python || '')}"></td>
                <td><input class="tts-settings-table-input" data-runtime-field="gfx" value="${escapeHtml(profile.rocm_gfx_override || '')}"></td>
                <td><button class="btn btn-danger btn-sm" type="button" data-remove-runtime="${provider}:${index}">删除</button></td>
            </tr>
        `).join('') || '<tr><td colspan="5" style="color:#667085;">当前 provider 没有运行环境。</td></tr>';

        return `
            <div class="tts-settings-group">
                <h3>${escapeHtml(provider)}</h3>
                <div class="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th style="width:120px;">环境名</th>
                                <th style="width:220px;">显示标签</th>
                                <th>Python 路径</th>
                                <th style="width:130px;">gfx 覆盖</th>
                                <th style="width:90px;">操作</th>
                            </tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        `;
    }).join('');
}

function renderTtsSettingsModeGroups() {
    const container = document.getElementById('tts-settings-mode-groups');
    if (!container) return;
    const modeDefaults = ttsSettingsConfig.mode_defaults || {};

    container.innerHTML = Object.entries(modeDefaults).map(([provider, modes]) => {
        const rows = Object.entries(modes || {}).map(([modeName, profile], index) => `
            <tr data-mode-provider="${escapeHtml(provider)}" data-mode-index="${index}">
                <td><input class="tts-settings-table-input" data-mode-field="name" value="${escapeHtml(modeName)}"></td>
                <td><input class="tts-settings-table-input" data-mode-field="runtime_env" value="${escapeHtml(profile.runtime_env || '')}"></td>
                <td><input class="tts-settings-table-input" data-mode-field="gfx" value="${escapeHtml(profile.rocm_gfx_override || '')}"></td>
                <td><button class="btn btn-danger btn-sm" type="button" data-remove-mode="${provider}:${index}">删除</button></td>
            </tr>
        `).join('') || '<tr><td colspan="4" style="color:#667085;">当前 provider 没有模式映射。</td></tr>';

        return `
            <div class="tts-settings-group">
                <h3>${escapeHtml(provider)}</h3>
                <div class="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th style="width:160px;">模式名</th>
                                <th>默认运行环境</th>
                                <th style="width:140px;">gfx 覆盖</th>
                                <th style="width:90px;">操作</th>
                            </tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        `;
    }).join('');
}

function renderTtsSettingsProviderDefaults() {
    const container = document.getElementById('tts-settings-provider-defaults');
    if (!container) return;
    const providerDefaults = ttsSettingsConfig.provider_defaults || {};

    container.innerHTML = Object.entries(providerDefaults).map(([provider, profile]) => `
        <div class="tts-settings-group">
            <h3>${escapeHtml(provider)}</h3>
            <div class="form-row">
                <div class="form-group">
                    <label>默认运行环境</label>
                    <input class="tts-settings-table-input" data-provider-default-provider="${escapeHtml(provider)}" data-provider-default-field="runtime_env" value="${escapeHtml(profile.runtime_env || '')}">
                </div>
                <div class="form-group">
                    <label>默认 gfx 覆盖</label>
                    <input class="tts-settings-table-input" data-provider-default-provider="${escapeHtml(provider)}" data-provider-default-field="gfx" value="${escapeHtml(profile.rocm_gfx_override || '')}">
                </div>
            </div>
        </div>
    `).join('');
}

function collectTtsSettingsForm() {
    const config = ensureTtsSettingsShape(JSON.parse(JSON.stringify(ttsSettingsConfig || {})));

    config.defaults = {
        ...config.defaults,
        tts_provider: document.getElementById('tts-settings-default-provider').value.trim(),
        tts_runtime_env: document.getElementById('tts-settings-default-runtime-env').value.trim(),
        tts_mode: document.getElementById('tts-settings-default-mode').value.trim(),
        tts_model: document.getElementById('tts-settings-default-model').value.trim(),
        device: document.getElementById('tts-settings-default-device').value.trim(),
        rocm_gfx_override: document.getElementById('tts-settings-default-gfx').value.trim(),
        tts_threads: parseInt(document.getElementById('tts-settings-default-threads').value || '4', 10),
        tts_executor: document.getElementById('tts-settings-default-executor').value,
        tts_parallel: parseInt(document.getElementById('tts-settings-default-parallel').value || '2', 10),
        tts_prompt_text: document.getElementById('tts-settings-default-prompt-text').value,
        tts_cosyvoice_style_text: document.getElementById('tts-settings-default-cosy-style').value,
        tts_indextts2_emo_text: document.getElementById('tts-settings-default-indextts-emo').value
    };

    const presetRows = Array.from(document.querySelectorAll('#tts-settings-presets-table tbody tr[data-preset-index]'));
    const promptPresets = {};
    presetRows.forEach(row => {
        const key = row.querySelector('[data-preset-field="key"]')?.value?.trim();
        const value = row.querySelector('[data-preset-field="value"]')?.value ?? '';
        if (key) {
            promptPresets[key] = value;
        }
    });
    config.prompt_presets = promptPresets;

    const runtimeEnvs = {};
    Object.keys(config.runtime_envs || {}).forEach(provider => {
        runtimeEnvs[provider] = {};
    });
    const runtimeRows = Array.from(document.querySelectorAll('[data-runtime-provider][data-runtime-index]'));
    runtimeRows.forEach(row => {
        const provider = row.dataset.runtimeProvider;
        const name = row.querySelector('[data-runtime-field="name"]')?.value?.trim();
        const label = row.querySelector('[data-runtime-field="label"]')?.value ?? '';
        const python = row.querySelector('[data-runtime-field="python"]')?.value?.trim() || '';
        const gfx = row.querySelector('[data-runtime-field="gfx"]')?.value?.trim() || null;
        runtimeEnvs[provider] = runtimeEnvs[provider] || {};
        if (name) {
            runtimeEnvs[provider][name] = {
                label,
                python,
                rocm_gfx_override: gfx
            };
        }
    });
    config.runtime_envs = runtimeEnvs;

    const providerDefaults = {};
    Object.keys(config.provider_defaults || {}).forEach(provider => {
        providerDefaults[provider] = {};
    });
    const providerDefaultInputs = Array.from(document.querySelectorAll('[data-provider-default-provider]'));
    providerDefaultInputs.forEach(input => {
        const provider = input.dataset.providerDefaultProvider;
        const field = input.dataset.providerDefaultField;
        providerDefaults[provider] = providerDefaults[provider] || {};
        if (field === 'runtime_env') {
            providerDefaults[provider].runtime_env = input.value.trim();
        } else if (field === 'gfx') {
            providerDefaults[provider].rocm_gfx_override = input.value.trim() || null;
        }
    });
    config.provider_defaults = providerDefaults;

    const modeDefaults = {};
    Object.keys(config.mode_defaults || {}).forEach(provider => {
        modeDefaults[provider] = {};
    });
    const modeRows = Array.from(document.querySelectorAll('[data-mode-provider][data-mode-index]'));
    modeRows.forEach(row => {
        const provider = row.dataset.modeProvider;
        const name = row.querySelector('[data-mode-field="name"]')?.value?.trim();
        const runtimeEnv = row.querySelector('[data-mode-field="runtime_env"]')?.value?.trim() || '';
        const gfx = row.querySelector('[data-mode-field="gfx"]')?.value?.trim() || null;
        modeDefaults[provider] = modeDefaults[provider] || {};
        if (name) {
            modeDefaults[provider][name] = {
                runtime_env: runtimeEnv,
                rocm_gfx_override: gfx
            };
        }
    });
    config.mode_defaults = modeDefaults;

    return config;
}

function updateTtsSettingsJson() {
    const textarea = document.getElementById('tts-settings-json');
    if (!textarea) return;
    const collected = collectTtsSettingsForm();
    ttsSettingsConfig = ensureTtsSettingsShape(collected);
    textarea.value = JSON.stringify(ttsSettingsConfig, null, 2);
}

async function loadTtsSettings(force = false) {
    if (ttsSettingsLoaded && !force) return;
    try {
        const config = await api('GET', '/tts-settings');
        ttsSettingsConfig = ensureTtsSettingsShape(config);
        renderTtsSettingsForm();
        clearTtsSettingsMessage();
        ttsSettingsLoaded = true;
    } catch (err) {
        console.error('Failed to load TTS settings:', err);
        showTtsSettingsMessage('error', '加载失败: ' + err.message);
    }
}

function addTtsPresetRow() {
    updateTtsSettingsJson();
    let index = 1;
    let key = `preset_${index}`;
    while (ttsSettingsConfig.prompt_presets[key]) {
        index += 1;
        key = `preset_${index}`;
    }
    ttsSettingsConfig.prompt_presets[key] = '';
    renderTtsSettingsPresets();
    updateTtsSettingsJson();
}

function addTtsRuntimeRow() {
    updateTtsSettingsJson();
    const provider = document.getElementById('tts-settings-runtime-provider').value;
    ttsSettingsConfig.runtime_envs[provider] = ttsSettingsConfig.runtime_envs[provider] || {};
    let index = 1;
    let key = `new_env_${index}`;
    while (ttsSettingsConfig.runtime_envs[provider][key]) {
        index += 1;
        key = `new_env_${index}`;
    }
    ttsSettingsConfig.runtime_envs[provider][key] = createEmptyRuntimeProfile();
    renderTtsSettingsRuntimeGroups();
    updateTtsSettingsJson();
}

function addTtsModeRow() {
    updateTtsSettingsJson();
    const provider = document.getElementById('tts-settings-mode-provider').value;
    ttsSettingsConfig.mode_defaults[provider] = ttsSettingsConfig.mode_defaults[provider] || {};
    let index = 1;
    let key = `new_mode_${index}`;
    while (ttsSettingsConfig.mode_defaults[provider][key]) {
        index += 1;
        key = `new_mode_${index}`;
    }
    ttsSettingsConfig.mode_defaults[provider][key] = createEmptyModeProfile();
    renderTtsSettingsModeGroups();
    updateTtsSettingsJson();
}

async function saveTtsSettings() {
    try {
        updateTtsSettingsJson();
        const payload = JSON.parse(document.getElementById('tts-settings-json').value);
        const result = await api('PUT', '/tts-settings', payload);
        ttsSettingsConfig = ensureTtsSettingsShape(result);
        renderTtsSettingsForm();
        if (typeof loadConfig === 'function') {
            await loadConfig();
        }
        showTtsSettingsMessage('success', 'TTS 配置已保存，并已刷新到前台默认值');
    } catch (err) {
        showTtsSettingsMessage('error', '保存失败: ' + err.message);
    }
}

async function validateTtsSettings() {
    try {
        updateTtsSettingsJson();
        const payload = JSON.parse(document.getElementById('tts-settings-json').value);
        const result = await api('POST', '/tts-settings/validate', payload);
        ttsSettingsConfig = ensureTtsSettingsShape(result.config || payload);
        renderTtsSettingsForm();
        showTtsSettingsMessage('success', '配置校验通过');
    } catch (err) {
        showTtsSettingsMessage('error', '校验失败: ' + err.message);
    }
}

async function resetTtsSettings() {
    if (!confirm('确定恢复 TTS 配置默认值吗？这会覆盖当前 JSON 文件。')) return;
    try {
        const result = await api('POST', '/tts-settings/reset', {});
        ttsSettingsConfig = ensureTtsSettingsShape(result);
        renderTtsSettingsForm();
        if (typeof loadConfig === 'function') {
            await loadConfig();
        }
        showTtsSettingsMessage('success', '已恢复默认配置');
    } catch (err) {
        showTtsSettingsMessage('error', '恢复失败: ' + err.message);
    }
}

function bindTtsSettingsEvents() {
    document.getElementById('tts-settings-save-btn')?.addEventListener('click', saveTtsSettings);
    document.getElementById('tts-settings-validate-btn')?.addEventListener('click', validateTtsSettings);
    document.getElementById('tts-settings-reload-btn')?.addEventListener('click', () => loadTtsSettings(true));
    document.getElementById('tts-settings-reset-btn')?.addEventListener('click', resetTtsSettings);
    document.getElementById('tts-settings-sync-json-btn')?.addEventListener('click', () => {
        updateTtsSettingsJson();
        showTtsSettingsMessage('success', '已将表单同步到原始 JSON');
    });
    document.getElementById('tts-settings-add-preset-btn')?.addEventListener('click', addTtsPresetRow);
    document.getElementById('tts-settings-add-runtime-btn')?.addEventListener('click', addTtsRuntimeRow);
    document.getElementById('tts-settings-add-mode-btn')?.addEventListener('click', addTtsModeRow);

    document.addEventListener('click', event => {
        const presetBtn = event.target.closest('[data-remove-preset]');
        if (presetBtn) {
            const index = parseInt(presetBtn.dataset.removePreset, 10);
            const entries = Object.entries(collectTtsSettingsForm().prompt_presets || {});
            entries.splice(index, 1);
            ttsSettingsConfig.prompt_presets = Object.fromEntries(entries);
            renderTtsSettingsPresets();
            updateTtsSettingsJson();
            return;
        }

        const runtimeBtn = event.target.closest('[data-remove-runtime]');
        if (runtimeBtn) {
            const [provider, indexText] = runtimeBtn.dataset.removeRuntime.split(':');
            const index = parseInt(indexText, 10);
            const entries = Object.entries(collectTtsSettingsForm().runtime_envs?.[provider] || {});
            entries.splice(index, 1);
            ttsSettingsConfig.runtime_envs[provider] = Object.fromEntries(entries);
            renderTtsSettingsRuntimeGroups();
            updateTtsSettingsJson();
            return;
        }

        const modeBtn = event.target.closest('[data-remove-mode]');
        if (modeBtn) {
            const [provider, indexText] = modeBtn.dataset.removeMode.split(':');
            const index = parseInt(indexText, 10);
            const entries = Object.entries(collectTtsSettingsForm().mode_defaults?.[provider] || {});
            entries.splice(index, 1);
            ttsSettingsConfig.mode_defaults[provider] = Object.fromEntries(entries);
            renderTtsSettingsModeGroups();
            updateTtsSettingsJson();
        }
    });

    document.addEventListener('input', event => {
        if (event.target.closest('#settings-panel-tts-settings')) {
            clearTtsSettingsMessage();
        }
    });
}

window.loadTtsSettings = loadTtsSettings;

document.addEventListener('DOMContentLoaded', function() {
    bindTtsSettingsEvents();
});
