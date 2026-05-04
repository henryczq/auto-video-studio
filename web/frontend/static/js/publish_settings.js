// Publish settings management

const DEFAULT_CONTENT_PROMPT = `你是一名短视频运营策划。请根据以下视频字幕内容，生成适合短视频平台发布的标题、简介和标签。

字幕内容：
{subtitles}

请输出 3 套不同风格的发布文案：
- tutorial: 教程型
- hook: 爆点型
- workplace: 职场效率型

整体要求：
1. 面向抖音、快手、小红书视频号这类短视频平台，不要写成产品说明书
2. 标题要口语化、像真人会发的视频标题，优先突出结果感、实用性、节省时间、自动化体验
3. 可以自然出现“飞书机器人”“OpenClaw”，但不要堆术语，不要生硬
4. 标题尽量控制在 26 字以内，避免过长
5. 简介控制在 2-4 句话，先讲这视频解决什么问题，再讲演示了什么，最后可轻微引导互动
6. 标签 5-8 个，优先场景词、结果词、平台熟词，避免空泛大词
7. 不要输出夸张违禁词，不要标题党过度，不要虚假承诺
8. “自动提醒待办”“省事”“效率提升”这类方向可以优先考虑

标题风格参考：
- 用飞书机器人自动提醒待办，太省事了
- 我把待办提醒交给飞书机器人了
- 用 OpenClaw 搭个飞书机器人，自动管理待办

请按以下 JSON 格式返回，不要 Markdown 代码块，不要额外解释：
{
  "recommended_style": "workplace",
  "versions": {
    "tutorial": {
      "label": "教程型",
      "title": "标题",
      "description": "简介",
      "tags": ["标签1", "标签2", "标签3"]
    },
    "hook": {
      "label": "爆点型",
      "title": "标题",
      "description": "简介",
      "tags": ["标签1", "标签2", "标签3"]
    },
    "workplace": {
      "label": "职场效率型",
      "title": "标题",
      "description": "简介",
      "tags": ["标签1", "标签2", "标签3"]
    }
  }
}
`;

let publishSettings = {};

async function loadPublishSettings() {
    try {
        const settings = await api('GET', '/publish-settings');
        publishSettings = settings || {};
        
        // Fill form
        document.getElementById('publish-content-prompt').value = publishSettings.content_prompt || DEFAULT_CONTENT_PROMPT;
        document.getElementById('publish-default-tags').value = (publishSettings.default_tags || []).join(',');
        
        // Load AI model options
        await loadAiModelOptions();
        document.getElementById('publish-ai-model').value = publishSettings.ai_model || '';
        
        // Load prompts from AI config
        await loadAiPromptsForPublish();
    } catch (err) {
        console.error('Failed to load publish settings:', err);
        // Use defaults
        document.getElementById('publish-content-prompt').value = DEFAULT_CONTENT_PROMPT;
    }
}

async function loadAiModelOptions() {
    try {
        const config = await api('GET', '/ai-config');
        const select = document.getElementById('publish-ai-model');
        const models = config.models || [];
        
        select.innerHTML = '<option value="">使用 AI 配置中的启用模型</option>' +
            models.map(m => `<option value="${escapeHtml(m.name)}">${escapeHtml(m.name)} (${escapeHtml(m.model)})</option>`).join('');
    } catch (err) {
        console.error('Failed to load AI models:', err);
    }
}

async function loadAiPromptsForPublish() {
    try {
        const config = await api('GET', '/ai-config');
        document.getElementById('ai-prompt-publish').value = config.prompt || '';
        document.getElementById('ai-tts-segment-prompt-publish').value = config.tts_segment_prompt || '';
    } catch (err) {
        console.error('Failed to load AI prompts:', err);
    }
}

async function savePublishSettings() {
    const settings = {
        content_prompt: document.getElementById('publish-content-prompt').value,
        default_tags: document.getElementById('publish-default-tags').value.split(',').map(t => t.trim()).filter(t => t),
        ai_model: document.getElementById('publish-ai-model').value,
    };
    
    try {
        await api('POST', '/publish-settings', settings);
        document.getElementById('publish-settings-result').innerHTML = '<div class="message message-success">设置已保存</div>';
        setTimeout(() => {
            document.getElementById('publish-settings-result').innerHTML = '';
        }, 3000);
    } catch (err) {
        document.getElementById('publish-settings-result').innerHTML = '<div class="message message-error">保存失败: ' + err.message + '</div>';
    }
}

async function resetPublishSettings() {
    if (!confirm('确定要恢复默认设置吗？')) return;
    
    document.getElementById('publish-content-prompt').value = DEFAULT_CONTENT_PROMPT;
    document.getElementById('publish-default-tags').value = '';
    document.getElementById('publish-ai-model').value = '';
    
    await savePublishSettings();
}

async function saveAiPromptFromPublish() {
    const prompt = document.getElementById('ai-prompt-publish').value;
    try {
        const config = await api('GET', '/ai-config');
        config.prompt = prompt;
        await api('PUT', '/ai-config', config);
        window.notifySuccess('错词检测提示词已保存');
    } catch (err) {
        window.notifyError('保存失败: ' + err.message);
    }
}

async function saveTtsPromptFromPublish() {
    const prompt = document.getElementById('ai-tts-segment-prompt-publish').value;
    try {
        const config = await api('GET', '/ai-config');
        config.tts_segment_prompt = prompt;
        await api('PUT', '/ai-config', config);
        window.notifySuccess('TTS 分段提示词已保存');
    } catch (err) {
        window.notifyError('保存失败: ' + err.message);
    }
}

// Event listeners
document.addEventListener('DOMContentLoaded', function() {
    const saveBtn = document.getElementById('publish-settings-save-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', savePublishSettings);
    }
    
    const resetBtn = document.getElementById('publish-settings-reset-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', resetPublishSettings);
    }
    
    const savePromptBtn = document.getElementById('ai-save-prompt-btn');
    if (savePromptBtn) {
        savePromptBtn.addEventListener('click', saveAiPromptFromPublish);
    }
    
    const saveTtsPromptBtn = document.getElementById('ai-save-tts-prompt-btn');
    if (saveTtsPromptBtn) {
        saveTtsPromptBtn.addEventListener('click', saveTtsPromptFromPublish);
    }

    const bilibiliProviderSaveBtn = document.getElementById('bilibili-provider-save-btn');
    if (bilibiliProviderSaveBtn) {
        bilibiliProviderSaveBtn.addEventListener('click', saveBilibiliProvider);
    }

    loadBilibiliProvider();
});

async function loadBilibiliProvider() {
    try {
        const settings = await api('GET', '/social/settings');
        const provider = settings.bilibili_provider || 'social-auto-upload';
        const select = document.getElementById('bilibili-provider');
        if (select) {
            select.value = provider;
        }
    } catch (err) {
        console.error('Failed to load bilibili provider:', err);
    }
}

async function saveBilibiliProvider() {
    const select = document.getElementById('bilibili-provider');
    const resultDiv = document.getElementById('bilibili-provider-result');
    if (!select || !resultDiv) return;

    const provider = select.value;
    try {
        const settings = await api('GET', '/social/settings');
        settings.bilibili_provider = provider;
        await api('POST', '/social/settings', settings);
        resultDiv.innerHTML = '<div class="message message-success">B站发布工具设置已保存</div>';
        setTimeout(() => {
            resultDiv.innerHTML = '';
        }, 3000);
    } catch (err) {
        resultDiv.innerHTML = '<div class="message message-error">保存失败: ' + escapeHtml(err.message) + '</div>';
    }
}
