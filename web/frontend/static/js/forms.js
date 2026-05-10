document.getElementById('verify-prompt-btn').addEventListener('click', async () => {
    const promptWav = document.getElementById('prompt-wav').value.trim();
    const promptText = document.getElementById('prompt-text').value.trim();

    if (!promptWav) {
        window.notifyWarning('请先填写参考音频路径');
        return;
    }

    const btn = document.getElementById('verify-prompt-btn');

    await window.apiAction({
        button: btn,
        loadingText: '校验中...',
        request: async () => {
            return await api('POST', '/jobs/verify-prompt', {
                prompt_wav: promptWav,
                prompt_text: promptText,
                device: 'cpu'
            });
        },
        onSuccess: (result) => {
            const matchColor = result.match_status === '匹配' ? '#28a745' :
                               result.match_status === '部分匹配' ? '#ffc107' : '#dc3545';
            window.notifyInfo(`校验完成 - 相似度: ${result.similarity}% (${result.match_status})`);
        },
        successMessage: null,
    });
});

document.getElementById('tts-mode').addEventListener('change', updateTtsModeUI);
document.getElementById('tts-model').addEventListener('change', syncTtsModelDir);
document.getElementById('tts-provider').addEventListener('change', updateTtsProviderUI);
document.getElementById('tts-executor')?.addEventListener('change', updateTtsParallelModeUI);
document.getElementById('tts-emo-preset')?.addEventListener('change', updateTtsPresetUI);
document.getElementById('tts-compose-playback-rate')?.addEventListener('input', updateTtsComposePlaybackRateLabel);
updateTtsParallelModeUI();
updateTtsComposePlaybackRateLabel();

document.getElementById('process-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const jobId = document.getElementById('process-job-id').value;
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }

    const btn = e.submitter;

    try {
        const params = getProcessRequest();
        
        window.showJobProgress(jobId, '视频处理中...');
        await refreshProcessLog(jobId);
        
        const result = await api('POST', `/jobs/${jobId}/process-video`, params);
        
        window.updateJobProgress('视频处理完成', '正在刷新状态...');
        
        displayProcessResult(result);
        await refreshCurrentJobViews(true);
        window.hideJobProgress();
        window.notifySuccess('视频处理请求已提交');
        
        if (result.status === 'processing') {
            window.pollJob(jobId, {
                until: (job) => job.status !== 'processing',
                onTick: (job) => {
                    window.updateJobProgress('视频处理中...', `状态: ${job.status}`);
                    refreshProcessLog(jobId);
                },
                onDone: (job) => {
                    window.hideJobProgress();
                    displayProcessResult(job);
                    refreshProcessLog(jobId);
                    refreshCurrentJobViews(true);
                    window.notifySuccess('视频处理完成');
                },
                onError: (err) => {
                    window.hideJobProgress();
                    refreshProcessLog(jobId);
                    window.notifyError('视频处理失败: ' + err.message);
                }
            });
        }
    } catch (err) {
        window.hideJobProgress();
        await refreshProcessLog(jobId);
        window.notifyError('处理失败: ' + err.message);
    }
});

document.getElementById('full-pipeline-btn').addEventListener('click', async () => {
    const jobId = document.getElementById('process-job-id').value;
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    window.runFullPipeline(jobId, document.getElementById('full-pipeline-btn'));
});

document.getElementById('tts-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const jobId = document.getElementById('tts-job-id').value;
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }

    const action = e.submitter;
    const originalText = action.textContent;

    try {
        if (action.value === 'generate') {
            window.showJobProgress(jobId, '提交 TTS 生成任务...');
            const result = await api('POST', `/jobs/${jobId}/generate-tts`, getTtsRequest());
            displayTtsResult(result);
            await refreshCurrentJobViews(true);
            window.hideJobProgress();
            window.notifySuccess('TTS 生成任务已提交，请看下方 chunk 进度');
        } else {
            const composeParams = {
                mode: action.value === 'compose-replace' ? 'replace_audio' : 'subtitles_only',
                playback_rate: getTtsComposePlaybackRate()
            };
            window.showJobProgress(jobId, '合成中...');
            const result = await api('POST', `/jobs/${jobId}/compose`, composeParams);
            displayTtsResult(result);
            await refreshCurrentJobViews(true);
            window.hideJobProgress();
            window.notifySuccess('合成完成');
        }
    } catch (err) {
        window.hideJobProgress();
        window.notifyError('处理失败: ' + err.message);
        await refreshCurrentJobViews(true);
    }
});

document.getElementById('caption-job-select').addEventListener('change', async (e) => {
    const jobId = e.target.value;
    if (!jobId) return;
    window.currentVoiceoverSuggestions = [];
    displayVoiceoverSuggestions({ items: [] });
    await loadCaptions(jobId, window.currentCaptionViewStage || 'auto');
    await loadSavedTtsSegments(jobId);
    await loadLogs(jobId);
    await refreshProcessLog(jobId);
});

document.getElementById('refresh-process-log-btn')?.addEventListener('click', async () => {
    const jobId = document.getElementById('process-job-id')?.value || document.getElementById('caption-job-select')?.value;
    await refreshProcessLog(jobId);
});

document.getElementById('save-captions-btn').addEventListener('click', async () => {
    const jobId = document.getElementById('caption-job-select').value;
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    try {
        const rows = document.querySelectorAll('#captions-editor tr[data-index]');
        const captions = [];
        rows.forEach(row => {
            const startInput = row.querySelector('[data-field="start"]');
            const endInput = row.querySelector('[data-field="end"]');
            const textInput = row.querySelector('[data-field="text"]');
            if (startInput && endInput && textInput) {
                captions.push({
                    start: parseEditorTimeValue(startInput.value),
                    end: parseEditorTimeValue(endInput.value),
                    text: textInput.value
                });
            }
        });
        await api('POST', `/jobs/${jobId}/captions/final`, { captions });
        displayTtsSegmentsEditor({ segments: [] });
        await loadCaptions(jobId, 'final');
        await refreshCurrentJobViews(true);
        window.notifyWarning('字幕已变更，裁剪/合成/TTS 结果已失效，请按需要重新生成。');
    } catch (err) {
        window.notifyError('保存失败: ' + err.message);
    }
});

document.getElementById('apply-terms-btn').addEventListener('click', async () => {
    const jobId = document.getElementById('caption-job-select').value;
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    const btn = document.getElementById('apply-terms-btn');

    await window.apiAction({
        button: btn,
        loadingText: '应用中...',
        request: async () => {
            await saveFinalCaptionsFromStage(jobId, 'working');
            return await api('POST', `/jobs/${jobId}/apply-terms`, { stage: 'working' });
        },
        onSuccess: async (result) => {
            await loadCaptions(jobId, 'working');
            await refreshCurrentJobViews(true);
            window.notifySuccess(`已应用 ${result.applied} 条替换规则`);
        },
        successMessage: null,
    });
});

document.getElementById('generate-tts-segments-btn')?.addEventListener('click', async () => {
    const jobId = document.getElementById('caption-job-select').value;
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    const btn = document.getElementById('generate-tts-segments-btn');

    await window.apiAction({
        button: btn,
        loadingText: '生成中...',
        request: async () => {
            return await api('POST', `/jobs/${jobId}/tts-segments/generate`, {
                segment_mode: 'ai',
                stage: 'auto'
            });
        },
        onSuccess: (result) => {
            displayTtsSegmentsEditor(result);
            window.notifySuccess(`已生成 ${result.segments?.length || 0} 个朗读分段`);
        },
        successMessage: null,
    });
});

document.getElementById('save-tts-segments-btn')?.addEventListener('click', async () => {
    const jobId = document.getElementById('caption-job-select').value;
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    const btn = document.getElementById('save-tts-segments-btn');

    const segments = window.currentTtsSegments;
    if (!segments || segments.length === 0) {
        window.notifyWarning('当前没有可保存的朗读分段');
        return;
    }

    await window.apiAction({
        button: btn,
        loadingText: '保存中...',
        request: async () => {
            return await api('POST', `/jobs/${jobId}/tts-segments`, {
                segments: segments,
                requested_mode: 'manual',
                mode_used: 'manual',
                source_stage: 'working'
            });
        },
        onSuccess: () => {
            window.notifySuccess('朗读分段已保存，生成 TTS 时会优先使用');
        },
        successMessage: null,
    });
});

function showSuggestionsProgress(message, subtext) {
    const container = document.getElementById('suggestions-container');
    if (!container) return;

    container.classList.remove('hidden');
    container.innerHTML = `
        <div class="progress-panel">
            <div class="progress-title">${escapeHtml(message || '正在生成错词建议...')}</div>
            <div class="progress-bar"></div>
            <div class="progress-status">${escapeHtml(subtext || 'AI 正在结合字幕上下文检测错词，请稍候。')}</div>
        </div>
    `;
}

function clearSuggestionsProgressIfVisible() {
    const container = document.getElementById('suggestions-container');
    const panel = container?.querySelector('.progress-panel');
    if (panel) {
        container.innerHTML = '';
        container.classList.add('hidden');
    }
}

function showSuggestionsMessage(type, message) {
    const container = document.getElementById('suggestions-container');
    if (!container) return;

    const className = type === 'error' ? 'message-error' : 'message-success';
    container.classList.remove('hidden');
    container.innerHTML = `<div class="message ${className}">${escapeHtml(message)}</div>`;
}

document.getElementById('generate-suggestions-btn')?.addEventListener('click', async () => {
    const jobId = document.getElementById('caption-job-select').value;
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    const btn = document.getElementById('generate-suggestions-btn');

    try {
        await window.apiAction({
            button: btn,
            loadingText: '生成中...',
            request: async () => {
                showSuggestionsProgress('正在生成错词建议...', '请求已经发出，通常需要等待模型返回结果。');
                return await api('POST', `/jobs/${jobId}/suggestions`, {});
            },
            onSuccess: (result) => {
                if (result && result.length > 0) {
                    displaySuggestions(result);
                } else {
                    showSuggestionsMessage('success', '未发现明显错词');
                    window.notifySuccess('未发现明显错词');
                }
            },
            onError: (err) => {
                showSuggestionsMessage('error', '生成错词建议失败: ' + (err.message || '未知错误'));
            },
            successMessage: null,
        });
    } catch (err) {
        console.error('Failed to generate suggestions:', err);
    }
});

function showVoiceoverSuggestionsProgress(message, subtext) {
    const container = document.getElementById('voiceover-suggestions-container');
    if (!container) return;

    container.classList.remove('hidden');
    container.innerHTML = `
        <div class="progress-panel">
            <div class="progress-title">${escapeHtml(message || '正在生成口播优化文案...')}</div>
            <div class="progress-bar"></div>
            <div class="progress-status">${escapeHtml(subtext || 'AI 正在生成逐条口播候选，请稍候。')}</div>
        </div>
    `;
}

function showVoiceoverSuggestionsMessage(type, message) {
    const container = document.getElementById('voiceover-suggestions-container');
    if (!container) return;

    const className = type === 'error' ? 'message-error' : 'message-success';
    container.classList.remove('hidden');
    container.innerHTML = `<div class="message ${className}">${escapeHtml(message)}</div>`;
}

document.getElementById('generate-voiceover-suggestions-btn')?.addEventListener('click', async () => {
    const jobId = document.getElementById('caption-job-select').value;
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    const btn = document.getElementById('generate-voiceover-suggestions-btn');

    try {
        // 先自动保存当前字幕，避免读取到旧文件
        try {
            const rows = document.querySelectorAll('#captions-editor tr[data-index]');
            const captions = [];
            rows.forEach(row => {
                const startInput = row.querySelector('[data-field="start"]');
                const endInput = row.querySelector('[data-field="end"]');
                const textInput = row.querySelector('[data-field="text"]');
                if (startInput && endInput && textInput) {
                    captions.push({
                        start: parseEditorTimeValue(startInput.value),
                        end: parseEditorTimeValue(endInput.value),
                        text: textInput.value
                    });
                }
            });
            if (captions.length > 0) {
                await api('POST', `/jobs/${jobId}/captions/final`, { captions });
                // 短暂延迟确保文件系统写入完成
                await new Promise(resolve => setTimeout(resolve, 200));
            }
        } catch (saveErr) {
            console.warn('自动保存字幕失败，继续生成口播优化:', saveErr);
        }

        await window.apiAction({
            button: btn,
            loadingText: '生成中...',
            request: async () => {
                showVoiceoverSuggestionsProgress('正在生成讲解风格口播文案...', '会基于当前字幕生成更适合短视频讲解、带轻微惊讶感的逐条候选。');
                return await api('POST', `/jobs/${jobId}/voiceover-suggestions`, {
                    stage: window.currentCaptionViewStage || 'working',
                });
            },
            onSuccess: async (result) => {
                const items = result?.items || [];
                if (items.length > 0) {
                    displayVoiceoverSuggestions(result);
                    await loadCaptions(jobId, window.currentCaptionViewStage || 'auto');
                    window.notifySuccess(`已生成 ${items.length} 条口播优化候选`);
                } else {
                    window.currentVoiceoverSuggestions = [];
                    showVoiceoverSuggestionsMessage('success', '没有生成新的口播优化候选');
                    await loadCaptions(jobId, window.currentCaptionViewStage || 'auto');
                }
            },
            onError: async (err) => {
                window.currentVoiceoverSuggestions = [];
                showVoiceoverSuggestionsMessage('error', '生成口播优化失败: ' + (err.message || '未知错误'));
                await loadCaptions(jobId, window.currentCaptionViewStage || 'auto');
            },
            successMessage: null,
        });
    } catch (err) {
        console.error('Failed to generate voiceover suggestions:', err);
    }
});

document.getElementById('trim-btn')?.addEventListener('click', async () => {
    const jobId = document.getElementById('caption-job-select')?.value;
    if (!jobId) {
        window.notifyWarning('请先选择任务');
        return;
    }
    window.notifyInfo('正在提交裁剪任务...');
});
