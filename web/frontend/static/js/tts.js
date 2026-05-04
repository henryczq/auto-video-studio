function setPipelineProgress(text) {
    document.getElementById('tts-result').innerHTML = `
        <div class="message message-success">${text}</div>
        <p style="color:#666;">一键生成会自动处理视频、应用词库、保存当前字幕、生成配音并合成两个最终视频。执行时间会比较长，请保持页面打开。</p>
    `;
}

function hasPlayingMedia(container) {
    if (!container) return false;
    return Array.from(container.querySelectorAll('audio, video')).some(media => !media.paused && !media.ended);
}

function ensureResultSections(container, prefix) {
    if (!container.querySelector(`[data-section="${prefix}-status"]`)) {
        container.innerHTML = `
            <div data-section="${prefix}-inputs"></div>
            <div data-section="${prefix}-status"></div>
            <div data-section="${prefix}-media"></div>
        `;
    }
    return {
        inputs: container.querySelector(`[data-section="${prefix}-inputs"]`),
        status: container.querySelector(`[data-section="${prefix}-status"]`),
        media: container.querySelector(`[data-section="${prefix}-media"]`),
    };
}

function formatPreciseDuration(seconds) {
    if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) {
        return '-';
    }
    const value = Math.max(0, Number(seconds));
    const minutes = Math.floor(value / 60);
    const totalCentiseconds = Math.round(value * 100);
    const wholeSeconds = Math.floor(totalCentiseconds / 100) % 60;
    const centiseconds = totalCentiseconds % 100;
    return `${minutes}:${wholeSeconds.toString().padStart(2, '0')}.${centiseconds.toString().padStart(2, '0')}`;
}

function durationDeltaText(a, b) {
    if (a === null || a === undefined || b === null || b === undefined) return '';
    const delta = Number(a) - Number(b);
    if (!Number.isFinite(delta)) return '';
    const sign = delta >= 0 ? '+' : '-';
    return `${sign}${formatPreciseDuration(Math.abs(delta))}`;
}

function renderTtsInputInfo(info) {
    const videoDuration = info.video_duration;
    const captionsDuration = info.captions_duration;
    const voiceoverDuration = info.voiceover_duration;
    const videoCaptionDelta = Math.abs(Number(videoDuration || 0) - Number(captionsDuration || 0));
    const voiceoverDelta = voiceoverDuration !== null && voiceoverDuration !== undefined
        ? Math.abs(Number(voiceoverDuration) - Number(videoDuration || 0))
        : 0;
    const warnings = [];
    if (videoDuration && captionsDuration && videoCaptionDelta > 1.5) {
        warnings.push(`视频和字幕时长相差 ${durationDeltaText(captionsDuration, videoDuration)}`);
    }
    if (voiceoverDuration && videoDuration && voiceoverDelta > 1.5) {
        warnings.push(`当前配音和视频时长相差 ${durationDeltaText(voiceoverDuration, videoDuration)}`);
    }
    if (info.tts_segments_source_stage && info.source_stage === 'trimmed' && info.tts_segments_source_stage !== 'trimmed') {
        warnings.push(`已保存朗读分段来源是 ${info.tts_segments_source_stage}，重新生成 TTS 时会按裁剪字幕重新分段`);
    }

    const stageClass = info.source_stage === 'trimmed' ? 'message-success' : '';
    const warningHtml = warnings.length
        ? `<div style="margin-top:8px; color:#856404;">${warnings.map(escapeHtml).join('；')}</div>`
        : '';
    const segmentsText = info.tts_segments_file
        ? `${info.tts_segments_file}${info.tts_segments_source_stage ? ` / ${info.tts_segments_source_stage}` : ''}${info.tts_segments_mode ? ` / ${info.tts_segments_mode}` : ''}`
        : '未保存，生成时自动分段';
    const chunkCacheText = info.chunk_plan_count
        ? `${info.chunk_cache_count || 0}/${info.chunk_plan_count}`
        : `${info.chunk_cache_count || 0}`;

    return `
        <div class="message ${stageClass}" style="margin-bottom:12px;">
            <strong>本次 TTS/合成将使用：</strong>${escapeHtml(info.source_label || info.source_stage || '-')}
            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:8px 14px; margin-top:10px; font-size:13px;">
                <div><strong>视频：</strong><code>${escapeHtml(info.video_file || '-')}</code><br><span class="field-note">时长 ${formatPreciseDuration(videoDuration)}</span></div>
                <div><strong>字幕：</strong><code>${escapeHtml(info.captions_file || '-')}</code><br><span class="field-note">${info.captions_count || 0} 条，末尾 ${formatPreciseDuration(captionsDuration)}</span></div>
                <div><strong>朗读分段：</strong><code>${escapeHtml(segmentsText)}</code></div>
                <div><strong>Chunk 缓存：</strong><code>${escapeHtml(info.chunk_cache_dir || 'voice_chunks')}</code><br><span class="field-note">已生成 ${escapeHtml(chunkCacheText)} 个 raw chunk</span></div>
                <div><strong>当前配音：</strong><code>${escapeHtml(info.voiceover_file || '未生成')}</code><br><span class="field-note">时长 ${formatPreciseDuration(voiceoverDuration)}</span></div>
            </div>
            ${warningHtml}
        </div>
    `;
}

async function loadTtsInputInfo(job, container) {
    if (!job?.id || !container) return;
    const jobId = job.id;
    container.dataset.jobId = jobId;
    if ((job.status === 'video_processing' || job.status === 'processing') && !job.processed_video) {
        container.innerHTML = '<div class="field-note">视频还在处理，处理后才会读取 TTS 使用素材。</div>';
        return;
    }
    if (job.status === 'error' && !job.processed_video) {
        const message = job.process_error || '视频处理没有生成 processed.mp4。';
        container.innerHTML = `<div class="message message-error">暂时不能读取 TTS 使用素材：${escapeHtml(message)}</div>`;
        return;
    }
    if (!container.innerHTML.trim()) {
        container.innerHTML = '<div class="field-note">正在读取 TTS 使用素材...</div>';
    }
    try {
        const info = await api('GET', `/jobs/${jobId}/tts/inputs`);
        if (container.dataset.jobId !== jobId) return;
        container.innerHTML = renderTtsInputInfo(info);
    } catch (err) {
        if (container.dataset.jobId !== jobId) return;
        if (!job.processed_video && String(err.message || '').includes('Processed video not found')) {
            container.innerHTML = '<div class="field-note">视频处理结果还没有生成，TTS 使用素材会在处理完成后显示。</div>';
            return;
        }
        container.innerHTML = `<div class="message message-error">读取 TTS 使用素材失败：${escapeHtml(err.message)}</div>`;
    }
}

function getProcessRequest() {
    return {
        margin: parseFloat(document.getElementById('margin').value),
        silence_noise: document.getElementById('silence-noise').value,
        silence_min_duration: parseFloat(document.getElementById('silence-min-duration').value),
        silence_keep: parseFloat(document.getElementById('silence-keep').value),
        model: document.getElementById('model').value,
        device: document.getElementById('device').value,
        rocm_gfx_override: document.getElementById('rocm-gfx-override').value || null
    };
}

function getTtsRequest() {
    const ttsMode = document.getElementById('tts-mode').value;
    const promptText = document.getElementById('prompt-text').value.trim();

    return {
        tts_provider: document.getElementById('tts-provider').value,
        tts_runtime_env: document.getElementById('tts-runtime-env').value,
        prompt_wav: document.getElementById('prompt-wav').value,
        prompt_text: promptText,
        tts_mode: ttsMode,
        segment_mode: document.getElementById('tts-segment-mode').value,
        model_name: document.getElementById('tts-model').value,
        model_dir: document.getElementById('tts-model-dir').value.trim(),
        speed: parseFloat(document.getElementById('speed').value),
        max_speedup: parseFloat(document.getElementById('max-speedup').value),
        rocm_gfx_override: document.getElementById('tts-rocm-gfx').value || null,
        threads: parseInt(document.getElementById('tts-threads').value, 10),
        parallel: parseInt(document.getElementById('tts-parallel').value, 10),
        tts_executor: document.getElementById('tts-executor')?.value || 'batched',
        emo_text: document.getElementById('tts-emo-text')?.value?.trim() || '',
        emo_alpha: parseFloat(document.getElementById('tts-emo-alpha')?.value || '0.6'),
        reuse_chunks: document.getElementById('tts-reuse-chunks')?.value !== 'false',
        serial_chunk_timeout: parseInt(document.getElementById('tts-serial-timeout')?.value || '1200', 10)
    };
}

function updateTtsComposePlaybackRateLabel() {
    const slider = document.getElementById('tts-compose-playback-rate');
    const label = document.getElementById('tts-compose-playback-rate-value');
    if (!slider || !label) return;
    const rate = Number(slider.value || 1);
    label.textContent = `${rate.toFixed(2)}x`;
}

function updateTtsParallelModeUI() {
    const executor = document.getElementById('tts-executor')?.value || 'batched';
    const label = document.getElementById('tts-parallel-label');
    const note = document.getElementById('tts-parallel-note');
    const input = document.getElementById('tts-parallel');
    if (!label || !note || !input) return;
    if (executor === 'workers') {
        label.textContent = 'Worker 数 📦';
        label.title = '极速模式下启动的独立 worker 数；每个 worker 都会加载一份模型权重';
        note.textContent = '速度更快但更吃显存/内存；建议先用 2。';
        input.max = '4';
        return;
    }
    label.textContent = '同时处理块数 📦';
    label.title = '省显存模式下单模型合批一次处理的字幕块数，只加载一次权重';
    note.textContent = '只加载一次权重；数值是 batch size。';
    input.max = '8';
}

function getTtsComposePlaybackRate() {
    return Number(document.getElementById('tts-compose-playback-rate')?.value || 1);
}

function updateTtsPresetUI() {
    const presetSelect = document.getElementById('tts-emo-preset');
    const emoInput = document.getElementById('tts-emo-text');
    const presets = appConfig?.tts?.prompt_presets || {};
    if (!presetSelect || !emoInput) return;
    const key = presetSelect.value;
    if (key && presets[key]) {
        emoInput.value = presets[key];
    }
}

function syncTtsModelDir() {
    const provider = document.getElementById('tts-provider').value;
    const model = document.getElementById('tts-model').value;
    const modelDir = document.getElementById('tts-model-dir');
    const mappedDir = provider === 'indextts2'
        ? appConfig?.tts?.model_dirs?.['IndexTTS2']
        : appConfig?.tts?.model_dirs?.[model];
    if (mappedDir) {
        modelDir.value = mappedDir;
    }
}

function updateTtsProviderUI() {
    const provider = document.getElementById('tts-provider').value;
    const runtimeGroup = document.getElementById('tts-runtime-env-group');
    const emoRow = document.getElementById('indextts2-emo-row');
    const modeSelect = document.getElementById('tts-mode');
    const modelSelect = document.getElementById('tts-model');
    const rocmGfx = document.getElementById('tts-rocm-gfx');

    if (provider === 'indextts2') {
        runtimeGroup.style.display = 'block';
        emoRow.style.display = 'flex';
        modeSelect.value = 'cross_lingual';
        modeSelect.disabled = true;
        modelSelect.disabled = true;
        syncTtsModelDir();
        rocmGfx.placeholder = 'IndexTTS2 由运行环境自动控制';
    } else {
        runtimeGroup.style.display = 'none';
        emoRow.style.display = 'flex';
        modeSelect.disabled = false;
        modelSelect.disabled = false;
        rocmGfx.placeholder = '默认 11.0.0；必要时再改';
        syncTtsModelDir();
    }
    updateTtsModeUI();
}

function updateTtsModeUI() {
    const provider = document.getElementById('tts-provider').value;
    const mode = document.getElementById('tts-mode').value;
    const promptTextGroup = document.getElementById('prompt-text-group');
    const helpPanel = document.getElementById('tts-mode-help');
    const emoRow = document.getElementById('indextts2-emo-row');

    if (provider === 'indextts2') {
        promptTextGroup.style.display = 'block';
        emoRow.style.display = 'flex';
        helpPanel.innerHTML = '<strong style="color:#155724;">IndexTTS2：</strong>当前按中文克隆实验路线运行。可在上方切换 `rocm7.12 原生 gfx1150` 或 `rocm6.3 + gfx 11.0.0`。风格/情绪提示词会直接影响生成语气。';
        helpPanel.style.background = '#d4edda';
        helpPanel.style.borderColor = '#c3e6cb';
        return;
    }

    if (mode === 'instruct2') {
        promptTextGroup.style.display = 'block';
        emoRow.style.display = 'flex';
        helpPanel.innerHTML = '<strong style="color:#155724;">CosyVoice3 instruct2 模式：</strong>当前默认推荐。保留参考音色，同时使用风格/情绪提示词增强短视频解说感，适合你当前喜欢的效果。';
        helpPanel.style.background = '#d4edda';
        helpPanel.style.borderColor = '#c3e6cb';
    } else if (mode === 'cross_lingual') {
        promptTextGroup.style.display = 'block';
        emoRow.style.display = 'none';
        helpPanel.innerHTML = '<strong style="color:#155724;">cross_lingual 模式：</strong>更偏保真，更像原始参考音色。适合做“原声版”或稳定教程版。';
        helpPanel.style.background = '#d4edda';
        helpPanel.style.borderColor = '#c3e6cb';
    } else {
        promptTextGroup.style.display = 'block';
        emoRow.style.display = 'none';
        helpPanel.innerHTML = '<strong>zero_shot 模式：</strong>可选实验模式。Prompt 文本建议与参考音频内容一致；在你当前这套音频上清晰度可能不如 cross_lingual。';
        helpPanel.style.background = '#fff3cd';
        helpPanel.style.borderColor = '#f0ad4e';
    }
}

function markDownloadedWhisperModels(downloadedModels) {
    const downloaded = new Set(downloadedModels);
    const labels = {
        tiny: 'tiny (最快)',
        base: 'base (推荐)',
        small: 'small (较准)',
        medium: 'medium (最准)'
    };

    document.querySelectorAll('#model option').forEach(option => {
        const baseLabel = labels[option.value] || option.value;
        option.textContent = downloaded.has(option.value)
            ? `${baseLabel} - 已下载`
            : `${baseLabel} - 未下载`;
    });
}

function applyDefaults(config) {
    const defaults = config.defaults || {};
    const device = document.getElementById('device');
    const rocmGfx = document.getElementById('rocm-gfx-override');
    const ttsRocmGfx = document.getElementById('tts-rocm-gfx');
    const ttsProvider = document.getElementById('tts-provider');
    const ttsRuntimeEnv = document.getElementById('tts-runtime-env');
    const ttsMode = document.getElementById('tts-mode');
    const ttsModel = document.getElementById('tts-model');
    const ttsModelDir = document.getElementById('tts-model-dir');
    const promptText = document.getElementById('prompt-text');
    const ttsThreads = document.getElementById('tts-threads');
    const ttsParallel = document.getElementById('tts-parallel');
    const ttsExecutor = document.getElementById('tts-executor');
    const ttsEmoText = document.getElementById('tts-emo-text');
    const ttsReuseChunks = document.getElementById('tts-reuse-chunks');
    const ttsSerialTimeout = document.getElementById('tts-serial-timeout');

    if (defaults.device) {
        device.value = defaults.device;
    }
    if (defaults.rocm_gfx_override) {
        rocmGfx.value = defaults.rocm_gfx_override;
        ttsRocmGfx.value = defaults.rocm_gfx_override;
    }
    if (defaults.tts_provider) {
        ttsProvider.value = defaults.tts_provider;
    }
    if (defaults.tts_runtime_env) {
        ttsRuntimeEnv.value = defaults.tts_runtime_env;
    }
    if (defaults.tts_mode) {
        ttsMode.value = defaults.tts_mode;
    }
    if (defaults.tts_model) {
        ttsModel.value = defaults.tts_model;
    }
    if (defaults.tts_model_dir) {
        ttsModelDir.value = defaults.tts_model_dir;
    }
    if (defaults.tts_prompt_text && promptText && !promptText.value.trim()) {
        promptText.value = defaults.tts_prompt_text;
    }
    if (defaults.tts_cosyvoice_style_text && ttsEmoText && !ttsEmoText.value.trim()) {
        ttsEmoText.value = defaults.tts_cosyvoice_style_text;
    }
    if (defaults.tts_threads) {
        ttsThreads.value = defaults.tts_threads;
    }
    if (defaults.tts_parallel) {
        ttsParallel.value = defaults.tts_parallel;
    }
    if (defaults.tts_executor && ttsExecutor) {
        ttsExecutor.value = defaults.tts_executor;
    }
    updateTtsParallelModeUI();
    if (ttsReuseChunks) {
        ttsReuseChunks.value = 'true';
    }
    if (ttsSerialTimeout) {
        ttsSerialTimeout.value = defaults.tts_serial_chunk_timeout || 1200;
    }
}

async function loadConfig() {
    try {
        appConfig = await api('GET', '/config');
        applyDefaults(appConfig);
        markDownloadedWhisperModels(appConfig.whisper?.downloaded || []);
        if (appConfig.auth?.token_required && !apiToken) {
            showTokenInput();
        }
    } catch (err) {
        console.error('Failed to load config:', err);
    }
}

function displayProcessResult(job) {
    const resultDiv = document.getElementById('process-result');
    const previewDiv = document.getElementById('process-video-preview');
    if (!job) {
        resultDiv.innerHTML = '<p style="color:#666;">请先选择任务</p>';
        if (previewDiv) {
            previewDiv.innerHTML = '';
        }
        return;
    }

    const sourceFilename = job?.source_video ? String(job.source_video).split('/').pop() : 'original.mp4';
    const sourceLabel = job?.source_video ? '上传时裁剪后视频' : '原视频';
    const mediaVersion = getJobMediaVersion(job);
    const sourceVideoUrl = job?.id ? jobFileUrl(job.id, sourceFilename, mediaVersion) : null;

    if (job.job_id && !job.id) {
        const statusText = job.status === 'processing'
            ? '请求已提交，视频正在后台处理中'
            : `接口已返回：${escapeHtml(job.status || 'unknown')}`;
        resultDiv.innerHTML = `
            <div class="progress-panel">
                <strong>${statusText}</strong>
                <div style="margin-top:6px; font-size:13px;">任务 ID：<code>${escapeHtml(job.job_id)}</code>。页面会自动刷新状态，你也可以查看“操作日志”里的视频处理日志。</div>
                <div class="progress-bar"></div>
            </div>
        `;
        if (previewDiv && sourceVideoUrl) {
            previewDiv.innerHTML = `
                <div class="message">
                    <strong>当前任务输入视频预览</strong>
                    <div class="field-note">视频处理会基于这份视频继续执行。</div>
                    <video controls preload="metadata" class="video-preview" src="${sourceVideoUrl}"></video>
                </div>
            `;
        }
        return;
    }

    let html = `<p><strong>状态：</strong><span class="status-badge status-${job.status}">${job.status}</span></p>`;
    html += `<p><strong>当前处理输入：</strong><code>${escapeHtml(sourceLabel)}</code></p>`;
    if (job.source_start || job.source_end) {
        html += `<p><strong>上传裁剪范围：</strong><code>${escapeHtml(job.source_start || '0')}</code> - <code>${escapeHtml(job.source_end || '')}</code></p>`;
    }

    if (job.status === 'video_processing' || job.status === 'processing') {
        html += `
            <div class="progress-panel">
                <strong>正在处理视频</strong>
                <div style="margin-top:6px; font-size:13px;">请求已经发出，后台任务正在执行。页面会自动刷新当前状态，处理完成后会出现处理后视频和初始字幕。</div>
                <div class="progress-bar"></div>
            </div>
        `;
    }

    if (job.processed_video) {
        html += `<p><strong>处理后视频：</strong><code>${job.processed_video}</code></p>`;
        html += `<p><strong>原始字幕文件：</strong><code>${job.captions_initial || '无'}</code></p>`;
    }

    if (job.process_error) {
        html += `<p style="color:red;"><strong>处理错误：</strong>${escapeHtml(job.process_error)}</p>`;
    }

    resultDiv.innerHTML = html;

    if (previewDiv) {
        const previewFilename = job.processed_video
            ? String(job.processed_video).split('/').pop()
            : sourceFilename;
        const previewLabel = job.processed_video ? '处理后视频预览' : `${sourceLabel}预览`;
        if (job.id && previewFilename) {
            const videoUrl = jobFileUrl(job.id, previewFilename, mediaVersion);
            const existingVideo = previewDiv.querySelector('video');
            const shouldPreservePlayer =
                existingVideo &&
                existingVideo.getAttribute('src') === videoUrl &&
                hasPlayingMedia(previewDiv);
            if (!shouldPreservePlayer) {
                previewDiv.innerHTML = `
                    <div class="message ${job.processed_video ? 'message-success' : ''}">
                        <strong>${previewLabel}</strong>
                        <div class="field-note">${job.processed_video ? '处理完成后的视频结果。' : '还没开始处理时，这里先播放当前任务输入视频。'}</div>
                        <video controls preload="metadata" class="video-preview" src="${videoUrl}"></video>
                    </div>
                `;
            }
        } else {
            if (!hasPlayingMedia(previewDiv)) {
                previewDiv.innerHTML = '<div class="field-note">上传后，这里会显示原视频或上传时裁剪后的视频；处理完成后会切换为处理后视频。</div>';
            }
        }
    }
}

async function refreshProcessLog(jobId) {
    const logViewer = document.getElementById('process-log-viewer');
    if (!logViewer) {
        return;
    }
    if (!jobId) {
        logViewer.textContent = '请选择任务后开始处理。';
        return;
    }
    try {
        const result = await api('GET', `/jobs/${jobId}/logs/process`);
        const content = String(result?.content || '').trim();
        logViewer.textContent = content || '当前还没有处理日志。处理开始后会自动刷新。';
        logViewer.scrollTop = logViewer.scrollHeight;
    } catch (err) {
        logViewer.textContent = '读取处理日志失败：' + err.message;
    }
}

function displayTtsResult(job) {
    const resultDiv = document.getElementById('tts-result');
    if (!job) {
        resultDiv.innerHTML = '<p style="color:#666;">请先选择任务</p>';
        return;
    }

    if (job.id) {
        window.currentDisplayedTtsJob = job;
    }

    if (job.job_id && !job.id) {
        const statusText = job.status === 'processing'
            ? '请求已提交，任务正在后台执行'
            : `接口已返回：${escapeHtml(job.status || 'unknown')}`;
        resultDiv.innerHTML = `
            <div class="progress-panel">
                <strong>${statusText}</strong>
                <div style="margin-top:6px; font-size:13px;">任务 ID：<code>${escapeHtml(job.job_id)}</code>。可继续查看下方日志，页面也会自动刷新状态。</div>
                <div class="progress-bar"></div>
            </div>
        `;
        return;
    }

    const sections = ensureResultSections(resultDiv, 'tts-result');
    loadTtsInputInfo(job, sections.inputs);
    let statusHtml = `<p><strong>任务状态：</strong><span class="status-badge status-${job.status}">${job.status}</span></p>`;
    const ttsProgress = window.currentTtsProgress || null;

    if (job.status === 'tts_processing' || job.status === 'composing') {
        const actionText = job.status === 'tts_processing' ? '正在生成配音' : '正在合成最终视频';
        const progressText = ttsProgress && ttsProgress.total > 0
            ? `已完成 ${ttsProgress.completed}/${ttsProgress.total} 个 chunk（${ttsProgress.percent}%）`
            : '正在读取进度...';
        const progressBar = ttsProgress && ttsProgress.total > 0
            ? `<div style="margin-top:8px; font-size:13px;">${progressText}</div>
               <div style="height:8px; margin-top:8px; background:#d7e9fb; border-radius:999px; overflow:hidden;">
                   <div style="width:${ttsProgress.percent}%; height:100%; background:linear-gradient(90deg, #2388ff, #73c2ff);"></div>
               </div>`
            : `<div style="margin-top:8px; font-size:13px;">${progressText}</div>
               <div class="progress-bar"></div>`;
        statusHtml += `
            <div class="progress-panel">
                <strong>${actionText}</strong>
                <div style="margin-top:6px; font-size:13px;">请求已经发出，后台任务正在执行。页面会自动根据 TTS 日志更新 chunk 进度。</div>
                ${progressBar}
            </div>
        `;

        if (job.status === 'tts_processing' && !ttsProgress) {
            statusHtml += '<p style="color:#856404;"><strong>提示：</strong>如果这个状态持续不变且日志为空，通常是当前字幕不可用、参考音频路径错误，或后台启动后立即报错。可先看“操作日志”里的 TTS 日志。</p>';
        }
    }

    let mediaHtml = '';
    if (job.voiceover) {
        mediaHtml += renderPlayableAudio(job, job.voiceover, '配音文件');
    }

    if (job.final_replace_audio || job.final_subtitles_only) {
        mediaHtml += `<hr style="margin:15px 0;">`;
        mediaHtml += `<p><strong>合成结果：</strong></p>`;
        if (job.final_replace_audio) {
            mediaHtml += renderPlayableVideo(job, job.final_replace_audio, '替换音频视频');
        }
        if (job.final_subtitles_only) {
            mediaHtml += renderPlayableVideo(job, job.final_subtitles_only, '仅字幕视频');
        }
    }

    if (!job.voiceover && !job.final_replace_audio && !job.final_subtitles_only && !job.tts_error && !job.compose_error) {
        mediaHtml += '<p style="color:#666;">当前任务还没有生成配音或最终视频。</p>';
    }

    if (job.tts_error) {
        statusHtml += `<p style="color:red;"><strong>TTS 错误：</strong>${escapeHtml(job.tts_error)}</p>`;
    }

    if (job.compose_error) {
        statusHtml += `<p style="color:red;"><strong>合成错误：</strong>${escapeHtml(job.compose_error)}</p>`;
    }

    sections.status.innerHTML = statusHtml;
    if (!hasPlayingMedia(sections.media)) {
        sections.media.innerHTML = mediaHtml;
    }
}

function getJobOutputFilename(path) {
    const value = String(path || '').trim();
    if (!value) return '';
    return value.split('/').pop();
}

function renderPlayableAudio(job, path, title) {
    const filename = getJobOutputFilename(path);
    const player = job.id && filename
        ? `<audio controls preload="metadata" src="${jobFileUrl(job.id, filename, getJobMediaVersion(job))}" style="width:100%; margin-top:8px;"></audio>`
        : '';
    return `
        <div style="margin-top:10px;">
            <p style="margin:0 0 5px;"><strong>${title}：</strong><code>${escapeHtml(path)}</code></p>
            ${player}
        </div>
    `;
}

function renderPlayableVideo(job, path, title) {
    const filename = getJobOutputFilename(path);
    const player = job.id && filename
        ? `<video controls preload="metadata" src="${jobFileUrl(job.id, filename, getJobMediaVersion(job))}" style="width:100%; max-height:420px; margin-top:8px; border-radius:6px; background:#111; object-fit:contain;"></video>`
        : '';
    return `
        <div style="margin-top:12px;">
            <p style="margin:0 0 5px;"><strong>${title}：</strong><code>${escapeHtml(path)}</code></p>
            ${player}
        </div>
    `;
}

function parseTtsProgress(logContent) {
    if (!logContent) {
        return null;
    }

    const latestConfigIndex = logContent.lastIndexOf('[TTS Config]');
    const scopedLog = latestConfigIndex >= 0 ? logContent.slice(latestConfigIndex) : logContent;
    const totalMatch = scopedLog.match(/^\s*chunks:\s*(\d+)/m);
    const reuseMatch = scopedLog.match(/reuse_chunks:\s*found\s+(\d+)\/(\d+)\s+existing raw chunks/);
    const chunkRegex = /\[Chunk\s+(\d+)\/(\d+)\]/g;
    const doneChunkRegex = /^\s*chunk\s+(\d+)\s+done\b/gmi;
    const completedChunks = new Set();
    let inferredTotal = totalMatch ? parseInt(totalMatch[1], 10) : 0;
    let reusedCount = 0;
    let match;

    if (reuseMatch) {
        reusedCount = parseInt(reuseMatch[1], 10);
        inferredTotal = Math.max(inferredTotal, parseInt(reuseMatch[2], 10));
    }

    while ((match = chunkRegex.exec(scopedLog)) !== null) {
        completedChunks.add(parseInt(match[1], 10));
        inferredTotal = Math.max(inferredTotal, parseInt(match[2], 10));
    }

    while ((match = doneChunkRegex.exec(scopedLog)) !== null) {
        completedChunks.add(parseInt(match[1], 10));
    }

    if (inferredTotal <= 0 && completedChunks.size === 0 && reusedCount === 0) {
        return null;
    }

    const completed = Math.min(inferredTotal || reusedCount + completedChunks.size, reusedCount + completedChunks.size);
    const total = inferredTotal || completed;
    const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;

    return { completed, total, percent };
}

window.parseTtsProgress = parseTtsProgress;

function finalVideoCard(job, filename, title, description) {
    return `<div style="margin-top:10px; padding:10px; background:#f8f9fa; border-radius:4px;">
        <p style="margin:0 0 5px;"><strong>${title}</strong></p>
        <p style="margin:0 0 5px; font-size:13px; color:#666;">${description}</p>
        <code style="font-size:12px;">${filename}</code>
    </div>`;
}
