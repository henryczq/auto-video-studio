function formatDuration(seconds) {
    if (!seconds || seconds < 0) return '0秒';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}小时${m}分${s}秒`;
    if (m > 0) return `${m}分${s}秒`;
    return `${s}秒`;
}

function getTrimPreviewRate() {
    const rate = Number(window.trimPreviewRate || 1);
    return Number.isFinite(rate) && rate > 0 ? rate : 1;
}

function applyTrimPreviewRate(rate) {
    const normalized = Number(rate);
    const finalRate = Number.isFinite(normalized) && normalized > 0 ? normalized : 1;
    window.trimPreviewRate = finalRate;

    const video = document.getElementById('trim-preview-video');
    if (video) {
        video.playbackRate = finalRate;
    }

    const slider = document.getElementById('trim-preview-rate');
    if (slider && Number(slider.value) !== finalRate) {
        slider.value = String(finalRate);
    }

    const label = document.getElementById('trim-preview-rate-value');
    if (label) {
        label.textContent = `${finalRate.toFixed(2)}x`;
    }
}

function parseTrimTimeValue(value) {
    const raw = String(value || '').trim();
    if (!raw) return NaN;
    const parts = raw.split(':').map(part => part.trim());
    if (parts.length === 3) {
        return parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
    }
    if (parts.length === 2) {
        return parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
    }
    return parseFloat(raw);
}

function resetTrimUiForJob(jobId, message = '正在加载当前任务的裁剪信息...') {
    window.trimActiveJobId = jobId || null;
    window.trimCutIndices = new Set();
    window.trimManualSegments = [];
    window.trimManualSegmentsJobId = jobId || null;
    window.trimCurrentDuration = 0;

    const sourceInfo = document.getElementById('trim-source-info');
    const videoPreview = document.getElementById('trim-video-preview');
    const cutCount = document.getElementById('trim-cut-count');
    const cutDuration = document.getElementById('trim-cut-duration');
    const originalDuration = document.getElementById('trim-original-duration');
    const remainingDuration = document.getElementById('trim-remaining-duration');
    const cutList = document.getElementById('trim-cut-list');
    const keepCaptions = document.getElementById('trim-keep-captions');
    const result = document.getElementById('trim-result');
    const keepRangeNote = document.getElementById('keep-range-note');

    if (sourceInfo) sourceInfo.textContent = message;
    if (videoPreview) videoPreview.innerHTML = '<div class="field-note">生成裁剪后视频后，这里可以直接在线播放检查。</div>';
    if (cutCount) cutCount.textContent = '-';
    if (cutDuration) cutDuration.textContent = '-';
    if (originalDuration) originalDuration.textContent = '-';
    if (remainingDuration) remainingDuration.textContent = '-';
    if (cutList) cutList.innerHTML = '<p style="color:#999;">正在读取当前任务的删除片段...</p>';
    if (keepCaptions) keepCaptions.innerHTML = '<p style="color:#999;">暂无数据</p>';
    if (result) result.innerHTML = '';
    if (keepRangeNote) keepRangeNote.textContent = '会保留这段内容，自动删除前后部分；字幕删除标记不会自动清空。';
    updateManualTrimList();
}

async function loadTrimJobs() {
    const jobs = await api('GET', '/jobs');
    const select = document.getElementById('trim-job-select');
    select.innerHTML = jobs.map(j =>
        `<option value="${j.id}">${escapeHtml(formatJobDisplayName(j, { includeStatus: true }))}</option>`
    ).join('');
}

async function syncTrimMarksFromCaptionEditor(jobId) {
    const captionJobId = document.getElementById('caption-job-select')?.value;
    if (
        captionJobId !== jobId ||
        window.currentCutMarksJobId !== jobId ||
        !(window.currentCutIndices instanceof Set)
    ) {
        return;
    }

    let manualSegments = [];
    try {
        const existing = await api('GET', `/jobs/${jobId}/captions/cut-marks`);
        manualSegments = existing?.manual_segments || [];
    } catch (err) {
        console.warn('Failed to load existing manual trim segments:', err);
        return;
    }

    await api('POST', `/jobs/${jobId}/captions/cut-marks`, {
        cut_indices: Array.from(window.currentCutIndices),
        manual_segments: manualSegments
    });
}

async function loadTrimInfo(jobId) {
    const requestId = Symbol(jobId);
    window.trimLoadRequestId = requestId;
    resetTrimUiForJob(jobId);

    try {
        await syncTrimMarksFromCaptionEditor(jobId);

        const [job, preview, cutMarks] = await Promise.all([
            api('GET', `/jobs/${jobId}`),
            api('POST', `/jobs/${jobId}/trim/preview`),
            api('GET', `/jobs/${jobId}/captions/cut-marks`)
        ]);

        if (window.trimLoadRequestId !== requestId || window.trimActiveJobId !== jobId) {
            return;
        }

        const sourceInfo = document.getElementById('trim-source-info');
        const videoSource = job.processed_video ? '处理后视频' : '处理后视频';
        const captionsSource = job.captions_edited || job.captions_final ? '当前字幕' : '原始字幕';
        sourceInfo.innerHTML = `视频：${videoSource} | 字幕：${captionsSource} | 状态：${escapeHtml(job.status || '')}`;
        renderTrimVideoPreview(jobId, job);

        const cutIndices = new Set(cutMarks?.cut_indices || []);
        window.trimCutIndices = cutIndices;
        window.trimManualSegments = cutMarks?.manual_segments || [];
        window.trimManualSegmentsJobId = jobId;
        updateManualTrimList();

        updateTrimPreview(preview, cutIndices);
    } catch (err) {
        if (window.trimLoadRequestId !== requestId || window.trimActiveJobId !== jobId) {
            return;
        }
        updateTrimPreview({ error: err.message || '加载裁剪信息失败' }, new Set());
    }
}

function renderTrimVideoPreview(jobId, job) {
    const container = document.getElementById('trim-video-preview');
    if (!container) return;

    if (!job.video_trimmed) {
        container.innerHTML = '<div class="field-note">生成裁剪后视频后，这里可以直接在线播放检查。</div>';
        return;
    }

    const videoUrl = jobFileUrl(jobId, job.video_trimmed);
    const rate = getTrimPreviewRate();
    container.innerHTML = `
        <div class="message message-success">
            <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;">
                <strong>裁剪后视频预览</strong>
                <div style="display:flex; align-items:center; gap:10px; min-width:min(100%, 360px);">
                    <label for="trim-preview-rate" style="margin:0; color:#475569; font-size:13px;">播放倍速</label>
                    <input type="range" id="trim-preview-rate" min="0.5" max="1.5" step="0.05" value="${rate}" style="flex:1;">
                    <strong id="trim-preview-rate-value" style="min-width:48px; text-align:right;">${rate.toFixed(2)}x</strong>
                </div>
            </div>
            <div class="field-note">这里只是预览播放速度，不会修改文件、音频或字幕时间轴。</div>
            <video id="trim-preview-video" controls preload="metadata" class="video-preview" src="${videoUrl}"></video>
        </div>
    `;

    const slider = document.getElementById('trim-preview-rate');
    slider?.addEventListener('input', (event) => {
        applyTrimPreviewRate(event.target.value);
    });

    const video = document.getElementById('trim-preview-video');
    if (video) {
        video.addEventListener('loadedmetadata', () => {
            applyTrimPreviewRate(getTrimPreviewRate());
        }, { once: true });
        applyTrimPreviewRate(rate);
    }
}

function updateTrimPreview(preview, cutIndices) {
    const cutCount = document.getElementById('trim-cut-count');
    const cutDuration = document.getElementById('trim-cut-duration');
    const originalDuration = document.getElementById('trim-original-duration');
    const remainingDuration = document.getElementById('trim-remaining-duration');
    const cutList = document.getElementById('trim-cut-list');
    const keepCaptions = document.getElementById('trim-keep-captions');

    if (preview.error) {
        window.trimCurrentDuration = 0;
        cutCount.textContent = '-';
        cutDuration.textContent = '-';
        originalDuration.textContent = '-';
        remainingDuration.textContent = '-';
        cutList.innerHTML = `<p style="color:red;">${preview.error}</p>`;
        keepCaptions.innerHTML = '<p style="color:#999;">暂无数据</p>';
        return;
    }

    window.trimCurrentDuration = Number(preview.duration || 0);

    const manualCount = preview.manual_cut_count || 0;
    cutCount.textContent = `${preview.cut_captions_count || 0} 条字幕${manualCount ? `，${manualCount} 个手动时间段` : ''}`;
    cutDuration.textContent = formatDuration(preview.cut_duration || 0);
    originalDuration.textContent = formatDuration(preview.duration || 0);
    remainingDuration.textContent = formatDuration(preview.remaining_duration || 0);

    const cutSegs = preview.cut_segments || [];
    if (cutSegs.length === 0) {
        cutList.innerHTML = '<p style="color:#999;">暂无标记要删除的片段</p>';
    } else {
        cutList.innerHTML = '<table style="width:100%;border-collapse:collapse;"><thead><tr style="background:#f0f0f0;"><th style="padding:8px;">序号</th><th style="padding:8px;">开始</th><th style="padding:8px;">结束</th><th style="padding:8px;">时长</th></tr></thead><tbody>' +
            cutSegs.map((seg, i) => `
                <tr style="border-bottom:1px solid #eee;">
                    <td style="padding:6px;text-align:center;">${i + 1}</td>
                    <td style="padding:6px;">${formatTime(seg.start)}</td>
                    <td style="padding:6px;">${formatTime(seg.end)}</td>
                    <td style="padding:6px;">${formatDuration(seg.duration)}</td>
                </tr>
            `).join('') + '</tbody></table>';
    }

    const keepCaps = preview.keep_captions || [];
    if (keepCaps.length === 0) {
        keepCaptions.innerHTML = '<p style="color:#999;">暂无保留字幕</p>';
    } else {
        keepCaptions.innerHTML = '<table style="width:100%;border-collapse:collapse;"><thead><tr style="background:#f0f0f0;"><th style="padding:8px;width:50px;">序号</th><th style="padding:8px;width:80px;">开始</th><th style="padding:8px;width:80px;">结束</th><th style="padding:8px;">文本</th></tr></thead><tbody>' +
            keepCaps.map(cap => `
                <tr style="border-bottom:1px solid #eee;">
                    <td style="padding:6px;text-align:center;">${cap.index + 1}</td>
                    <td style="padding:6px;">${formatTime(cap.start)}</td>
                    <td style="padding:6px;">${formatTime(cap.end)}</td>
                    <td style="padding:6px;">${escapeHtml(cap.text)}</td>
                </tr>
            `).join('') + '</tbody></table>';
    }
}

function applyKeepRangeSegments() {
    const jobId = document.getElementById('trim-job-select')?.value;
    if (!jobId) {
        window.notifyWarning('请先选择一个任务');
        return;
    }

    const totalDuration = Number(window.trimCurrentDuration || 0);
    if (!Number.isFinite(totalDuration) || totalDuration <= 0) {
        window.notifyWarning('当前还没有读取到视频时长，请先刷新预览');
        return;
    }

    const startInput = document.getElementById('keep-range-start');
    const endInput = document.getElementById('keep-range-end');
    const note = document.getElementById('keep-range-note');
    const keepStart = parseTrimTimeValue(startInput?.value);
    const keepEnd = parseTrimTimeValue(endInput?.value);

    if (!Number.isFinite(keepStart) || !Number.isFinite(keepEnd) || keepEnd <= keepStart) {
        window.notifyWarning('请填写有效的保留开始/结束时间，结束时间必须大于开始时间');
        return;
    }

    if (keepStart < 0 || keepEnd > totalDuration) {
        window.notifyWarning(`保留时间必须在视频时长内，当前视频约 ${formatDuration(totalDuration)}`);
        return;
    }

    const manualSegments = [];
    if (keepStart > 0.01) {
        manualSegments.push({ start: 0, end: keepStart });
    }
    if (keepEnd < totalDuration - 0.01) {
        manualSegments.push({ start: keepEnd, end: totalDuration });
    }

    window.trimManualSegments = manualSegments;
    window.trimManualSegmentsJobId = jobId;
    updateManualTrimList();

    if (note) {
        note.textContent = `已生成粗剪范围：保留 ${formatTime(keepStart)} 到 ${formatTime(keepEnd)}，视频总长约 ${formatDuration(totalDuration)}。`;
    }
    window.notifySuccess('粗剪时间段已生成，可以先预览再执行裁剪');
}

function updateManualTrimList() {
    const container = document.getElementById('manual-trim-list');
    const segments = window.trimManualSegments || [];
    if (!container) return;

    if (!segments.length) {
        container.innerHTML = '<p style="color:#999;">暂无手动时间段</p>';
        return;
    }

    container.innerHTML = '<table style="width:100%;border-collapse:collapse;"><thead><tr style="background:#f0f0f0;"><th style="padding:8px;">序号</th><th style="padding:8px;">开始</th><th style="padding:8px;">结束</th><th style="padding:8px;">时长</th><th style="padding:8px;">操作</th></tr></thead><tbody>' +
        segments.map((seg, i) => `
            <tr style="border-bottom:1px solid #eee;">
                <td style="padding:6px;text-align:center;">${i + 1}</td>
                <td style="padding:6px;">${formatTime(seg.start)}</td>
                <td style="padding:6px;">${formatTime(seg.end)}</td>
                <td style="padding:6px;">${formatDuration(seg.end - seg.start)}</td>
                <td style="padding:6px;text-align:center;"><button class="btn btn-sm btn-secondary" onclick="removeManualTrimSegment(${i})">删除</button></td>
            </tr>
        `).join('') + '</tbody></table>';
}

window.removeManualTrimSegment = function(index) {
    window.trimManualSegments = (window.trimManualSegments || []).filter((_, i) => i !== index);
    updateManualTrimList();
};

function addManualTrimSegment() {
    const jobId = document.getElementById('trim-job-select')?.value;
    if (!jobId) {
        window.notifyWarning('请先选择一个任务');
        return;
    }
    if (window.trimManualSegmentsJobId && window.trimManualSegmentsJobId !== jobId) {
        window.trimManualSegments = [];
    }
    window.trimManualSegmentsJobId = jobId;

    const startInput = document.getElementById('manual-trim-start');
    const endInput = document.getElementById('manual-trim-end');
    const start = parseTrimTimeValue(startInput?.value);
    const end = parseTrimTimeValue(endInput?.value);

    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
        window.notifyWarning('请填写有效的开始/结束时间，结束时间必须大于开始时间');
        return;
    }

    window.trimManualSegments = window.trimManualSegments || [];
    window.trimManualSegments.push({ start, end });
    window.trimManualSegments.sort((a, b) => a.start - b.start);
    if (startInput) startInput.value = '';
    if (endInput) endInput.value = '';
    updateManualTrimList();
}

async function saveTrimMarks(jobId) {
    if (window.trimManualSegmentsJobId && window.trimManualSegmentsJobId !== jobId) {
        throw new Error('当前手动时间段不属于所选任务，请重新加载裁剪页后再保存。');
    }
    await api('POST', `/jobs/${jobId}/captions/cut-marks`, {
        cut_indices: Array.from(window.trimCutIndices || []),
        manual_segments: window.trimManualSegments || []
    });
}

async function executeTrim(jobId) {
    const resultDiv = document.getElementById('trim-result');
    const btn = document.getElementById('trim-execute-btn');
    btn.disabled = true;
    btn.textContent = '裁剪中...';
    resultDiv.innerHTML = '<div class="message">正在裁剪视频，请稍候...</div>';

    try {
        await saveTrimMarks(jobId);
        const result = await api('POST', `/jobs/${jobId}/trim/render`);
        if (result.error) {
            resultDiv.innerHTML = `<div class="message message-error">裁剪失败: ${result.error}</div>`;
        } else {
            const videoUrl = jobFileUrl(jobId, result.video_path);
            resultDiv.innerHTML = `<div class="message message-success">
                裁剪完成！<br>
                - 删除 ${result.cut_count} 条字幕，${result.manual_cut_count || 0} 个手动时间段<br>
                - 节省 ${formatDuration(result.duration_saved)}<br>
                - 视频：${result.video_path}<br>
                - 字幕：${result.captions_srt}
                <video controls preload="metadata" class="video-preview" src="${videoUrl}"></video>
            </div>`;
            loadTrimInfo(jobId);
        }
    } catch (err) {
        resultDiv.innerHTML = `<div class="message message-error">裁剪失败: ${err.message}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = '生成裁剪后视频';
    }
}

async function clearTrimCutMarks(jobId) {
    if (!confirm('确定清除所有删除标记？')) return;
    await api('DELETE', `/jobs/${jobId}/captions/cut-marks`);
    window.trimManualSegments = [];
    window.trimManualSegmentsJobId = jobId;
    updateManualTrimList();
    loadTrimInfo(jobId);
}

document.addEventListener('DOMContentLoaded', function() {
    const jobSelect = document.getElementById('trim-job-select');
    const previewBtn = document.getElementById('trim-preview-btn');
    const executeBtn = document.getElementById('trim-execute-btn');
    const clearBtn = document.getElementById('trim-clear-btn');
    const addManualBtn = document.getElementById('manual-trim-add-btn');
    const saveManualBtn = document.getElementById('trim-save-manual-btn');
    const keepRangeBtn = document.getElementById('keep-range-apply-btn');

    jobSelect?.addEventListener('change', async () => {
        const jobId = jobSelect.value;
        if (jobId) {
            loadTrimInfo(jobId);
        }
    });

    previewBtn?.addEventListener('click', async () => {
        const jobId = jobSelect?.value;
        if (jobId) {
            await saveTrimMarks(jobId);
            loadTrimInfo(jobId);
        }
    });

    addManualBtn?.addEventListener('click', () => {
        addManualTrimSegment();
    });

    saveManualBtn?.addEventListener('click', async () => {
        const jobId = jobSelect?.value;
        if (!jobId) {
            window.notifyWarning('请先选择一个任务');
            return;
        }
        await saveTrimMarks(jobId);
        await loadTrimInfo(jobId);
        window.notifySuccess('手动时间段已保存');
    });

    keepRangeBtn?.addEventListener('click', async () => {
        applyKeepRangeSegments();
    });

    executeBtn?.addEventListener('click', async () => {
        const jobId = jobSelect?.value;
        if (!jobId) {
            window.notifyWarning('请先选择一个任务');
            return;
        }
        if (!confirm('确定要裁剪视频吗？此操作会重新计算字幕时间轴，并清除 TTS 相关文件。')) return;
        await executeTrim(jobId);
    });

    clearBtn?.addEventListener('click', async () => {
        const jobId = jobSelect?.value;
        if (jobId) {
            await clearTrimCutMarks(jobId);
        }
    });
});

window.loadTrimJobs = loadTrimJobs;
window.loadTrimInfo = loadTrimInfo;
