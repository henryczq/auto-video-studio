async function loadComposeJobs() {
    const jobs = await api('GET', '/jobs');
    const select = document.getElementById('compose-job-select');
    select.innerHTML = jobs.map(j =>
        `<option value="${j.id}">${escapeHtml(formatJobDisplayName(j, { includeStatus: true }))}</option>`
    ).join('');
}

function updateComposePlaybackRateLabel() {
    const slider = document.getElementById('compose-playback-rate');
    const label = document.getElementById('compose-playback-rate-value');
    if (!slider || !label) return;
    const rate = Number(slider.value || 1);
    label.textContent = `${rate.toFixed(2)}x`;
}

function renderAudioOptimizePreview(jobId, job) {
    const preview = document.getElementById('audio-optimize-preview');
    if (!preview) return;

    if (!job.optimized_audio) {
        preview.innerHTML = '<div class="field-note">生成优化声音后，这里可以直接在线播放试听。</div>';
        return;
    }

    const audioUrl = jobFileUrl(jobId, 'optimized.audio.wav', getJobMediaVersion(job));
    const existingAudio = preview.querySelector('audio');
    const shouldPreservePlayer =
        existingAudio &&
        existingAudio.getAttribute('src') === audioUrl &&
        hasPlayingMedia(preview);
    if (!shouldPreservePlayer) {
        preview.innerHTML = `
            <div class="message message-success">
                <strong>优化声音试听</strong>
                <audio controls preload="metadata" style="display:block; width:100%; margin-top:10px;" src="${audioUrl}"></audio>
            </div>
        `;
    }
}

function renderComposeVideoPreview(jobId, job) {
    const preview = document.getElementById('compose-video-preview');
    if (!preview) return;

    if (!job.final_subtitles_video) {
        preview.innerHTML = '<div class="field-note">生成字幕版视频后，这里可以直接在线播放检查。</div>';
        return;
    }

    const videoUrl = jobFileUrl(jobId, job.final_subtitles_video, getJobMediaVersion(job));
    const existingVideo = preview.querySelector('video');
    const shouldPreservePlayer =
        existingVideo &&
        existingVideo.getAttribute('src') === videoUrl &&
        hasPlayingMedia(preview);
    if (!shouldPreservePlayer) {
        preview.innerHTML = `
            <div class="message message-success">
                <strong>字幕版视频预览</strong>
                <video controls preload="metadata" class="video-preview" src="${videoUrl}"></video>
            </div>
        `;
    }
}

async function loadComposeInfo(jobId) {
    const job = await api('GET', `/jobs/${jobId}`);

    const videoLabel = document.getElementById('compose-video-label');
    const captionsLabel = document.getElementById('compose-captions-label');
    const audioLabel = document.getElementById('compose-audio-label');
    const audioMode = document.getElementById('compose-audio-mode');

    videoLabel.textContent = job.video_trimmed ? '裁剪后视频 (processed.trimmed.mp4)' :
        job.processed_video ? '处理后视频 (processed.mp4)' : '-';

    captionsLabel.textContent = job.captions_trimmed ? '裁剪后字幕' :
        (job.captions_final || job.captions_edited) ? '当前字幕' : '-';

    audioLabel.textContent = job.optimized_audio ? '已生成 (optimized.audio.wav)' : '未生成';
    if (audioMode) {
        audioMode.querySelector('option[value="optimized"]').disabled = !job.optimized_audio;
        if (job.optimized_audio) {
            audioMode.value = 'optimized';
            window.composeMissingOptimizedAudioNotifiedFor = null;
        } else {
            audioMode.value = 'original';
            if (window.composeMissingOptimizedAudioNotifiedFor !== jobId) {
                window.composeMissingOptimizedAudioNotifiedFor = jobId;
                window.notifyWarning('当前任务还没有优化后声音，已自动切回原视频声音');
            }
        }
    }
    renderAudioOptimizePreview(jobId, job);
    renderComposeVideoPreview(jobId, job);

    window.composeJobId = jobId;
}

async function executeAudioOptimize(jobId) {
    const resultDiv = document.getElementById('audio-optimize-result');
    const btn = document.getElementById('audio-optimize-btn');
    btn.disabled = true;
    btn.textContent = '优化中...';
    resultDiv.innerHTML = '<div class="message">正在优化声音，请稍候...</div>';

    const payload = {
        preset: document.getElementById('audio-opt-preset')?.value || 'voice_light',
        denoise: document.getElementById('audio-opt-denoise')?.checked ?? true,
        loudnorm: document.getElementById('audio-opt-loudnorm')?.checked ?? true,
        compressor: document.getElementById('audio-opt-compressor')?.checked ?? true,
    };

    try {
        const result = await api('POST', `/jobs/${jobId}/compose/audio-optimize`, payload);
        if (result.error) {
            resultDiv.innerHTML = `<div class="message message-error">声音优化失败: ${result.error}</div>`;
        } else {
            await loadComposeInfo(jobId);
            resultDiv.innerHTML = `<div class="message message-success">
                声音优化完成！<br>
                - 声音来源：${result.video_label}<br>
                - 优化音频：${result.audio_path}<br>
                - 使用滤镜：${escapeHtml(result.audio_filter || '')}
            </div>`;
        }
    } catch (err) {
        resultDiv.innerHTML = `<div class="message message-error">声音优化失败: ${err.message}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = '生成优化声音';
    }
}

async function executeCompose(jobId) {
    const resultDiv = document.getElementById('compose-result');
    const btn = document.getElementById('compose-execute-btn');
    const audioMode = document.getElementById('compose-audio-mode')?.value || 'original';
    const playbackRate = Number(document.getElementById('compose-playback-rate')?.value || 1);
    btn.disabled = true;
    btn.textContent = '合成中...';
    resultDiv.innerHTML = '<div class="message">正在合成视频，请稍候...</div>';

    try {
        const result = await api('POST', `/jobs/${jobId}/compose/video`, {
            audio_mode: audioMode,
            playback_rate: playbackRate,
        });
        if (result.error) {
            resultDiv.innerHTML = `<div class="message message-error">合成失败: ${result.error}</div>`;
        } else {
            const videoUrl = jobFileUrl(jobId, result.video_path);
            resultDiv.innerHTML = `<div class="message message-success">
                合成完成！<br>
                - 视频来源：${result.video_label}<br>
                - 字幕来源：${result.captions_label}<br>
                - 声音来源：${result.audio_label}<br>
                - 合成倍速：${Number(result.playback_rate || 1).toFixed(2)}x<br>
                - 输出文件：${result.video_path}
                <video controls preload="metadata" class="video-preview" src="${videoUrl}"></video>
            </div>`;
            await loadComposeInfo(jobId);
        }
    } catch (err) {
        resultDiv.innerHTML = `<div class="message message-error">合成失败: ${err.message}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = '生成字幕版视频';
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const jobSelect = document.getElementById('compose-job-select');
    const refreshBtn = document.getElementById('compose-refresh-btn');
    const executeBtn = document.getElementById('compose-execute-btn');
    const audioOptimizeBtn = document.getElementById('audio-optimize-btn');
    const audioPreset = document.getElementById('audio-opt-preset');
    const playbackRate = document.getElementById('compose-playback-rate');

    audioPreset?.addEventListener('change', () => {
        const isCustom = audioPreset.value === 'custom';
        ['audio-opt-denoise', 'audio-opt-loudnorm', 'audio-opt-compressor'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.disabled = !isCustom;
            }
        });
    });
    audioPreset?.dispatchEvent(new Event('change'));
    playbackRate?.addEventListener('input', updateComposePlaybackRateLabel);
    updateComposePlaybackRateLabel();

    jobSelect?.addEventListener('change', async () => {
        const jobId = jobSelect.value;
        if (jobId) {
            loadComposeInfo(jobId);
        }
    });

    refreshBtn?.addEventListener('click', async () => {
        const jobId = jobSelect?.value;
        if (jobId) {
            loadComposeInfo(jobId);
        }
    });

    audioOptimizeBtn?.addEventListener('click', async () => {
        const jobId = jobSelect?.value;
        if (!jobId) {
            window.notifyWarning('请先选择一个任务');
            return;
        }
        if (!confirm('确定要生成优化后的声音吗？')) return;
        await executeAudioOptimize(jobId);
    });

    executeBtn?.addEventListener('click', async () => {
        const jobId = jobSelect?.value;
        if (!jobId) {
            window.notifyWarning('请先选择一个任务');
            return;
        }
        if (!confirm('确定要生成字幕版视频吗？')) return;
        await executeCompose(jobId);
    });
});

window.loadComposeJobs = loadComposeJobs;
window.loadComposeInfo = loadComposeInfo;
