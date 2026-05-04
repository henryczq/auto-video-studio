window.captionEditorState = {
    hasUnsavedChanges: false,
    originalCaptions: null,
    savedCaptionsVersion: 0,
};

window.currentVoiceoverSuggestions = [];

function getVoiceoverSuggestionMap() {
    const items = window.currentVoiceoverSuggestions || [];
    return new Map(items.map(item => [Number(item.caption_id), item]));
}

window.setCaptionDirty = function(isDirty) {
    window.captionEditorState.hasUnsavedChanges = isDirty;
    updateUnsavedIndicator();
};

window.updateUnsavedIndicator = function() {
    const indicator = document.getElementById('captions-stage-indicator');
    if (!indicator) return;
    const baseText = indicator.dataset.baseText || indicator.textContent;
    if (window.captionEditorState.hasUnsavedChanges) {
        if (!indicator.textContent.includes('（有未保存修改）')) {
            indicator.textContent = baseText + '（有未保存修改）';
        }
    } else {
        indicator.textContent = baseText.replace('（有未保存修改）', '');
    }
};

window.checkUnsavedChanges = function(action = 'continue') {
    if (!window.captionEditorState.hasUnsavedChanges) {
        return true;
    }
    const msg = '字幕编辑器有未保存的修改，确定要 ' + action + ' 吗？';
    return confirm(msg);
};

window.markCaptionsSaved = function(version) {
    window.captionEditorState.hasUnsavedChanges = false;
    window.captionEditorState.savedCaptionsVersion = version || 0;
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
    window.captionEditorState.originalCaptions = JSON.stringify(captions);
    updateUnsavedIndicator();
};

window.captureOriginalCaptions = function() {
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
    window.captionEditorState.originalCaptions = JSON.stringify(captions);
    window.captionEditorState.hasUnsavedChanges = false;
};

window.setupBeforeUnloadProtection = function() {
    window.addEventListener('beforeunload', function(e) {
        if (window.captionEditorState.hasUnsavedChanges) {
            e.preventDefault();
            e.returnValue = '字幕编辑器有未保存的修改';
            return e.returnValue;
        }
    });
}

function updateCaptionsStageIndicator(stage, captions) {
    const indicator = document.getElementById('captions-stage-indicator');
    if (!indicator) {
        return;
    }

    const countText = captions && captions.length > 0 ? `，共 ${captions.length} 条` : '';
    if (stage === 'trimmed') {
        indicator.textContent = `当前显示：当前字幕（裁剪后字幕）${countText}`;
        return;
    }
    if (stage === 'final') {
        indicator.textContent = `当前显示：当前字幕（SRT）${countText}`;
        return;
    }
    if (stage === 'working' || stage === 'edited') {
        indicator.textContent = `当前显示：当前字幕（已应用词库/编辑后）${countText}`;
        return;
    }
    if (stage === 'source' || stage === 'initial') {
        indicator.textContent = `当前显示：原始识别字幕${countText}`;
        return;
    }
    indicator.textContent = `当前显示：${stage}${countText}`;
}

function updateCaptionStageButtons(stage) {
    document.querySelectorAll('.caption-stage-btn').forEach(btn => {
        const isActive = btn.dataset.stage === stage;
        btn.classList.toggle('btn-primary', isActive);
        btn.classList.toggle('btn-secondary', !isActive);
    });
}

function parseEditorTimeValue(t) {
    const parts = String(t || '').split(':');
    if (parts.length === 3) return parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
    if (parts.length === 2) return parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
    return parseFloat(parts[0] || '0');
}

async function loadCaptions(jobId, stage = 'auto') {
    try {
        let resolvedStage = stage;
        let captions = [];

        if (stage === 'auto') {
            const [trimmedJson, final, working, source] = await Promise.all([
                api('GET', `/jobs/${jobId}`),
                api('GET', `/jobs/${jobId}/captions?stage=final`),
                api('GET', `/jobs/${jobId}/captions?stage=working`),
                api('GET', `/jobs/${jobId}/captions?stage=source`)
            ]);
            
            if (trimmedJson?.captions_trimmed_json) {
                captions = await api('GET', `/jobs/${jobId}/captions?stage=trimmed`);
                if (captions && captions.length > 0) {
                    resolvedStage = 'trimmed';
                }
            }
            
            if (!captions || captions.length === 0) {
                if (final && final.length > 0) {
                    captions = final;
                    resolvedStage = 'final';
                } else if (working && working.length > 0) {
                    captions = working;
                    resolvedStage = 'working';
                } else if (source && source.length > 0) {
                    captions = source;
                    resolvedStage = 'source';
                }
            }
        } else {
            captions = await api('GET', `/jobs/${jobId}/captions?stage=${stage}`);
        }

        window.currentCaptionViewStage = resolvedStage;
        window.currentCaptionStage = resolvedStage;
        updateCaptionsStageIndicator(resolvedStage, captions);
        updateCaptionStageButtons(stage === 'auto' ? 'auto' : resolvedStage);
        
        const cutMarks = await api('GET', `/jobs/${jobId}/captions/cut-marks`);
        window.currentCutIndices = new Set(cutMarks?.cut_indices || []);
        window.currentCutMarksJobId = jobId;
        updateCutMarksIndicator();
        displayCaptionsEditor(captions);
    } catch (err) {
        console.error('Failed to load captions:', err);
        window.currentCaptionStage = null;
        window.currentCaptionViewStage = null;
        window.currentCutIndices = new Set();
        window.currentCutMarksJobId = null;
        updateCaptionsStageIndicator('加载失败', []);
        updateCaptionStageButtons('');
        updateCutMarksIndicator();
        document.getElementById('captions-editor').innerHTML = '<p style="color:red;">加载字幕失败: ' + escapeHtml(err.message) + '</p>';
    }
}

function updateCutMarksIndicator() {
    const indicator = document.getElementById('cut-marks-indicator');
    if (!indicator) return;
    const count = window.currentCutIndices?.size || 0;
    if (count > 0) {
        indicator.textContent = `已标记删除：${count} 条`;
        indicator.style.color = '#e65100';
    } else {
        indicator.textContent = '已标记删除：0 条';
        indicator.style.color = '';
    }
}

function displayCaptionsEditor(captions) {
    const editor = document.getElementById('captions-editor');
    if (!captions || captions.length === 0) {
        editor.innerHTML = '<p style="color:#666;">暂无字幕数据</p>';
        return;
    }
    const voiceoverSuggestionMap = getVoiceoverSuggestionMap();
    editor.innerHTML = '<table style="width:100%;border-collapse:collapse;">' +
        '<thead><tr style="background:#f0f0f0;"><th style="padding:8px;text-align:center;width:40px;">删除</th><th style="padding:8px;text-align:center;width:50px;">序号</th><th style="padding:8px;">开始</th><th style="padding:8px;">结束</th><th style="padding:8px;">文本</th><th style="padding:8px;min-width:280px;">口播优化候选</th><th style="padding:8px;text-align:center;">操作</th></tr></thead>' +
        '<tbody>' +
        captions.map((cap, i) => {
            const isCut = window.currentCutIndices?.has(i);
            const suggestion = voiceoverSuggestionMap.get(Number(cap.id || i + 1));
            const suggestionHtml = renderVoiceoverCandidates(suggestion);
            return `
            <tr data-index="${i}" data-caption-id="${cap.id || i + 1}" style="border-bottom:1px solid #eee;${isCut ? 'background:#ffebee;' : ''}">
                <td style="padding:6px;text-align:center;"><input type="checkbox" class="cut-checkbox" data-index="${i}" ${isCut ? 'checked' : ''} onchange="toggleCutMark(${i}, this.checked)"></td>
                <td style="padding:6px;text-align:center;">${i + 1}</td>
                <td style="padding:6px;"><input type="text" class="caption-input" data-field="start" value="${formatTime(cap.start)}" style="width:80px;"></td>
                <td style="padding:6px;"><input type="text" class="caption-input" data-field="end" value="${formatTime(cap.end)}" style="width:80px;"></td>
                <td style="padding:6px;"><input type="text" class="caption-input" data-field="text" value="${escapeHtml(cap.text)}" style="width:100%;" oninput="onCaptionInputChanged(this)"></td>
                <td style="padding:6px; vertical-align:top;">${suggestionHtml}</td>
                <td style="padding:6px;text-align:center;"><button class="btn btn-sm btn-secondary" onclick="playCaption(${i})">播放</button></td>
            </tr>
        `}).join('') +
        '</tbody></table>';
    editor.querySelectorAll('.caption-input[data-field="start"], .caption-input[data-field="end"]').forEach(input => {
        input.addEventListener('input', () => window.setCaptionDirty(true));
    });
    window.captureOriginalCaptions();
}

function renderVoiceoverCandidates(item) {
    if (!item || !Array.isArray(item.candidates) || item.candidates.length === 0) {
        return '<span style="color:#999;">未生成</span>';
    }
    const buttons = item.candidates.map((candidate, index) => {
        const lengthText = `${String(candidate || '').length}/${item.char_limit || '-'}`;
        return `
            <div style="display:flex; gap:6px; align-items:flex-start; margin-bottom:6px;">
                <button class="btn btn-sm btn-secondary" onclick="applyVoiceoverSuggestion(${Number(item.caption_id)}, ${index})">替换</button>
                <div style="flex:1;">
                    <div style="line-height:1.5;">${escapeHtml(candidate)}</div>
                    <div style="font-size:12px; color:#666;">长度 ${escapeHtml(lengthText)}</div>
                </div>
            </div>
        `;
    }).join('');
    const reason = item.reason ? `<div style="font-size:12px; color:#666; margin-top:4px;">${escapeHtml(item.reason)}</div>` : '';
    return `<div>${buttons}${reason}</div>`;
}

function displayVoiceoverSuggestions(payload) {
    const container = document.getElementById('voiceover-suggestions-container');
    const items = payload?.items || [];
    window.currentVoiceoverSuggestions = items;
    if (!container) {
        return;
    }
    if (!items.length) {
        container.innerHTML = '';
        container.classList.add('hidden');
        return;
    }
    container.classList.remove('hidden');
    container.innerHTML = `
        <div style="margin:12px 0; padding:12px; background:#fff7e6; border:1px solid #f5c46b; border-radius:8px;">
            <div style="font-weight:600; margin-bottom:6px;">AI 讲解风格口播已生成</div>
            <div style="font-size:13px; color:#666;">右侧候选会更偏短视频讲解口吻：第一个通常最稳，后面的会更口语化，可能带一点轻微强调或惊讶感。点击“替换”才会写入当前字幕。</div>
        </div>
    `;
}

window.onCaptionInputChanged = function(input) {
    window.setCaptionDirty(true);
};

window.applyVoiceoverSuggestion = function(captionId, candidateIndex = 0) {
    const item = (window.currentVoiceoverSuggestions || []).find(entry => Number(entry.caption_id) === Number(captionId));
    if (!item) {
        window.notifyWarning('没有找到对应的口播优化候选');
        return;
    }
    const candidate = item.candidates?.[candidateIndex];
    if (!candidate) {
        window.notifyWarning('当前候选为空');
        return;
    }
    let row = document.querySelector(`#captions-editor tr[data-caption-id="${captionId}"]`);
    if (!row && Number.isFinite(Number(captionId))) {
        row = document.querySelector(`#captions-editor tr[data-index="${Number(captionId) - 1}"]`);
    }
    const input = row?.querySelector('[data-field="text"]');
    if (!input) {
        window.notifyError('没有找到对应字幕行，可能字幕已经切换了版本。');
        return;
    }
    input.value = candidate;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    window.setCaptionDirty(true);
    window.notifySuccess(`已替换第 ${captionId} 条字幕`);
};

window.toggleCutMark = function(index, checked) {
    if (!window.currentCutIndices) {
        window.currentCutIndices = new Set();
    }
    window.currentCutMarksJobId = document.getElementById('caption-job-select')?.value || window.currentCutMarksJobId || null;
    if (checked) {
        window.currentCutIndices.add(index);
    } else {
        window.currentCutIndices.delete(index);
    }
    const row = document.querySelector(`tr[data-index="${index}"]`);
    if (row) {
        row.style.backgroundColor = checked ? '#ffebee' : '';
    }
    updateCutMarksIndicator();
};

async function saveCutMarks(jobId) {
    if (window.currentCutMarksJobId && window.currentCutMarksJobId !== jobId) {
        throw new Error('当前裁剪标记不属于所选任务，请重新加载字幕后再保存。');
    }
    const indices = Array.from(window.currentCutIndices || []);
    let manualSegments = [];
    try {
        const existing = await api('GET', `/jobs/${jobId}/captions/cut-marks`);
        manualSegments = existing?.manual_segments || [];
    } catch (err) {
        console.warn('Failed to preserve manual trim segments:', err);
        throw new Error('读取已保存的手动裁剪时间段失败。为避免覆盖原有时间段，本次未保存。');
    }
    await api('POST', `/jobs/${jobId}/captions/cut-marks`, {
        cut_indices: indices,
        manual_segments: manualSegments
    });
    window.currentCutMarksJobId = jobId;
    window.notifySuccess('裁剪标记已保存');
}

async function clearCutMarks(jobId) {
    if (!confirm('确定清除所有裁剪标记？')) return;
    await api('DELETE', `/jobs/${jobId}/captions/cut-marks`);
    window.currentCutIndices = new Set();
    window.currentCutMarksJobId = jobId;
    const checkboxes = document.querySelectorAll('.cut-checkbox');
    checkboxes.forEach(cb => {
        cb.checked = false;
        const row = document.querySelector(`tr[data-index="${cb.dataset.index}"]`);
        if (row) row.style.backgroundColor = '';
    });
    updateCutMarksIndicator();
    window.notifySuccess('裁剪标记已清除');
}

async function saveFinalCaptionsFromStage(jobId, stage) {
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
    await api('POST', `/jobs/${jobId}/captions?stage=${stage}`, { captions });
    window.captionEditorState.hasUnsavedChanges = false;
    window.captionEditorState.savedCaptionsVersion = (window.captionEditorState.savedCaptionsVersion || 0) + 1;
    updateUnsavedIndicator();
}

function suggestionKey(suggestion) {
    return [
        suggestion?.caption_id ?? '',
        suggestion?.src || suggestion?.suspect || '',
        suggestion?.dst || '',
        suggestion?.original || ''
    ].join('::');
}

function displaySuggestions(suggestions) {
    const container = document.getElementById('suggestions-container');
    if (!suggestions || suggestions.length === 0) {
        container.innerHTML = '';
        container.classList.add('hidden');
        window.pendingSuggestions = [];
        window.ignoredSuggestionKeys = new Set();
        return;
    }
    window.pendingSuggestions = suggestions;
    window.ignoredSuggestionKeys = new Set();

    container.classList.remove('hidden');
    container.innerHTML = `
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; margin:15px 0 10px; flex-wrap:wrap;">
            <h3 style="margin:0;">错词建议</h3>
            <button class="btn btn-success btn-sm" onclick="applyAllSuggestions()">一键替换全部</button>
        </div>
    ` +
        suggestions.map((s, i) => `
            <div class="suggestion-item" data-index="${i}" data-suggestion-key="${escapeHtml(suggestionKey(s))}">
                <div class="suspect">错词：${escapeHtml(s.src)} → 建议：${escapeHtml(s.dst)} (${(s.confidence * 100).toFixed(0)}% 置信度)</div>
                <div>原文：${escapeHtml(s.original)}</div>
                <div class="candidates">
                    ${(s.candidates || [s.dst]).map((c, candidateIndex) => `<button class="btn btn-sm btn-secondary" onclick="applySuggestion(${i}, ${candidateIndex})">${escapeHtml(c)}</button>`).join('')}
                    <button class="btn btn-sm btn-secondary" onclick="ignoreSuggestion(${i})">忽略</button>
                </div>
            </div>
        `).join('');
}

function applySuggestionToEditor(index, candidateIndex = 0, options = {}) {
    const sugg = window.pendingSuggestions?.[index];
    if (!sugg) {
        return false;
    }
    const replacement = sugg.candidates?.[candidateIndex] || sugg.dst;
    if (!replacement) {
        return false;
    }
    let row = document.querySelector(`#captions-editor tr[data-caption-id="${sugg.caption_id}"]`);
    if (!row && Number.isFinite(Number(sugg.caption_id))) {
        row = document.querySelector(`#captions-editor tr[data-index="${Number(sugg.caption_id) - 1}"]`);
    }
    const input = row?.querySelector('[data-field="text"]');
    if (!input) {
        if (!options.silent) {
            window.notifyError('没有找到对应字幕行，可能字幕已经切换了版本。');
        }
        return false;
    }

    const source = sugg.src || sugg.suspect || '';
    if (!source || !input.value.includes(source)) {
        if (!options.silent) {
            window.notifyError('当前字幕里没有找到这段错词，可能字幕已经被改过或切换了版本。');
        }
        return false;
    }

    input.value = input.value.replace(source, replacement);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    window.setCaptionDirty(true);

    const item = document.querySelector(`.suggestion-item[data-index="${index}"]`);
    if (item) {
        item.remove();
    }
    return true;
}

window.applySuggestion = function(index, candidateIndex = 0) {
    applySuggestionToEditor(index, candidateIndex);
};

window.applyAllSuggestions = function() {
    const suggestions = window.pendingSuggestions || [];
    const ignoredKeys = window.ignoredSuggestionKeys || new Set();
    let applied = 0;
    let skipped = 0;

    // 按 caption_id 分组，避免同一条字幕的多次替换互相影响
    const groupedByCaption = {};
    suggestions.forEach((suggestion, index) => {
        const item = document.querySelector(`.suggestion-item[data-index="${index}"]`);
        if (!item || ignoredKeys.has(suggestionKey(suggestion))) {
            skipped++;
            return;
        }
        const captionId = suggestion.caption_id;
        if (!groupedByCaption[captionId]) {
            groupedByCaption[captionId] = [];
        }
        groupedByCaption[captionId].push({ suggestion, index });
    });

    // 对每条字幕，先找到对应的 input，然后按顺序执行所有替换
    Object.values(groupedByCaption).forEach(group => {
        if (group.length === 0) return;

        // 找到对应的字幕行 input
        const firstSugg = group[0].suggestion;
        let row = document.querySelector(`#captions-editor tr[data-caption-id="${firstSugg.caption_id}"]`);
        if (!row && Number.isFinite(Number(firstSugg.caption_id))) {
            row = document.querySelector(`#captions-editor tr[data-index="${Number(firstSugg.caption_id) - 1}"]`);
        }
        const input = row?.querySelector('[data-field="text"]');
        if (!input) {
            skipped += group.length;
            return;
        }

        // 按 index 排序，确保替换顺序稳定
        group.sort((a, b) => a.index - b.index);

        // 在 input.value 上依次执行替换
        let currentText = input.value;
        let hasChange = false;

        group.forEach(({ suggestion, index }) => {
            const source = suggestion.src || suggestion.suspect || '';
            const replacement = suggestion.candidates?.[0] || suggestion.dst || '';
            if (!source || !replacement) {
                skipped++;
                return;
            }
            if (currentText.includes(source)) {
                currentText = currentText.replace(source, replacement);
                hasChange = true;
                applied++;
                // 移除对应的建议项
                const item = document.querySelector(`.suggestion-item[data-index="${index}"]`);
                if (item) {
                    item.remove();
                }
            } else {
                skipped++;
            }
        });

        // 如果有修改，更新 input 并触发事件
        if (hasChange) {
            input.value = currentText;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            window.setCaptionDirty(true);
        }
    });

    if (applied > 0) {
        window.notifySuccess(`已替换 ${applied} 条建议${skipped ? `，跳过 ${skipped} 条` : ''}`);
    } else {
        window.notifyWarning('没有可替换的建议');
    }
};

function updateTtsSegmentsIndicator(payload) {
    const indicator = document.getElementById('tts-segments-indicator');
    if (!indicator) {
        return;
    }
    const count = payload?.segments?.length || 0;
    if (!count) {
        indicator.textContent = '请先在字幕编辑器中保存字幕，然后切换到 TTS 页面生成配音。';
        return;
    }
    indicator.textContent = `当前共有 ${count} 个 TTS 分段，来源字幕编辑器。修改字幕编辑器内容后需要重新生成。`;
}

function displayTtsSegmentsEditor(payload) {
    const editor = document.getElementById('tts-segments-editor');
    const segments = payload?.segments || [];
    window.currentTtsSegmentsPayload = payload || { segments: [] };
    updateTtsSegmentsIndicator(payload || { segments: [] });

    if (!segments.length) {
        editor.innerHTML = '<p style="color:#999;">暂无分段数据。请在字幕编辑器中保存字幕后，切换到 TTS 页面生成配音。</p>';
        return;
    }

    editor.innerHTML = '<table style="width:100%;border-collapse:collapse;">' +
        '<thead><tr style="background:#f0f0f0;"><th style="padding:8px;text-align:center;width:50px;">序号</th><th style="padding:8px;">开始</th><th style="padding:8px;">结束</th><th style="padding:8px;">来源字幕ID</th><th style="padding:8px;">TTS 文本</th><th style="padding:8px;text-align:center;width:80px;">操作</th></tr></thead>' +
        '<tbody>' +
        segments.map((segment, i) => `
            <tr data-tts-segment-index="${i}" style="border-bottom:1px solid #eee;">
                <td style="padding:6px;text-align:center;">${i + 1}</td>
                <td style="padding:6px;"><input type="text" class="caption-input" data-field="start" value="${formatTime(segment.start)}" style="width:90px;" readonly></td>
                <td style="padding:6px;"><input type="text" class="caption-input" data-field="end" value="${formatTime(segment.end)}" style="width:90px;" readonly></td>
                <td style="padding:6px;"><input type="text" class="caption-input" data-field="source-ids" value="${escapeHtml((segment.source_ids || []).join(', '))}" style="width:110px;" readonly></td>
                <td style="padding:6px;"><input type="text" class="caption-input" data-field="text" value="${escapeHtml(segment.text)}" style="width:100%; background:#f5f5f5;" readonly></td>
                <td style="padding:6px;text-align:center;">
                    <button class="btn btn-sm btn-secondary" onclick="regenerateSingleChunk(${i + 1})" title="重新生成此段 TTS 语音">重新生成</button>
                </td>
            </tr>
        `).join('') +
        '</tbody></table>' +
        '<div class="field-note" style="margin-top:10px; background:#fff7e6; border-color:#ffc107; padding:8px; border-radius:4px;">📌 TTS 文本直接从字幕编辑器读取。如需修改文本，请在字幕编辑器中修改后保存，然后重新生成 TTS。</div>';
}

function collectTtsSegmentsFromEditor() {
    const rows = document.querySelectorAll('#tts-segments-editor tr[data-tts-segment-index]');
    const segments = [];
    rows.forEach(row => {
        const startInput = row.querySelector('[data-field="start"]');
        const endInput = row.querySelector('[data-field="end"]');
        const sourceIdsInput = row.querySelector('[data-field="source-ids"]');
        const textInput = row.querySelector('[data-field="text"]');
        if (!startInput || !endInput || !sourceIdsInput || !textInput) {
            return;
        }
        const sourceIds = sourceIdsInput.value
            .split(',')
            .map(item => item.trim())
            .filter(Boolean)
            .map(item => parseInt(item, 10))
            .filter(Number.isFinite);
        segments.push({
            start: parseEditorTimeValue(startInput.value),
            end: parseEditorTimeValue(endInput.value),
            source_ids: sourceIds,
            text: textInput.value.trim()
        });
    });
    return segments;
}

async function loadSavedTtsSegments(jobId) {
    try {
        const payload = await api('GET', `/jobs/${jobId}/tts-segments`);
        displayTtsSegmentsEditor(payload);
    } catch (err) {
        console.error('Failed to load tts segments:', err);
        displayTtsSegmentsEditor({ segments: [] });
    }
}

window.ignoreSuggestion = function(index) {
    const suggestion = window.pendingSuggestions?.[index];
    if (suggestion) {
        if (!(window.ignoredSuggestionKeys instanceof Set)) {
            window.ignoredSuggestionKeys = new Set();
        }
        window.ignoredSuggestionKeys.add(suggestionKey(suggestion));
    }
    document.querySelector(`.suggestion-item[data-index="${index}"]`)?.remove();
};

window.playCaption = function(index) {
    const rows = document.querySelectorAll('#captions-editor tr[data-index]');
    const row = rows[index];
    if (!row) return;
    const startInput = row.querySelector('[data-field="start"]');
    const endInput = row.querySelector('[data-field="end"]');
    if (startInput && endInput) {
        const parseTime = (t) => {
            const parts = t.split(':');
            if (parts.length === 3) return parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
            if (parts.length === 2) return parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
            return parseFloat(parts[0]);
        };
        const start = parseTime(startInput.value);
        const end = parseTime(endInput.value);
        window.notifyInfo(`播放时间范围: ${formatTime(start)} - ${formatTime(end)}`);
    }
};

window.regenerateSingleChunk = async function(chunkIndex) {
    const jobId = document.getElementById('caption-job-select')?.value;
    if (!jobId) {
        window.notifyError('请先选择一个任务');
        return;
    }

    // 从当前编辑行获取文本
    const row = document.querySelector(`#tts-segments-editor tr[data-tts-segment-index="${chunkIndex - 1}"]`);
    const textInput = row?.querySelector('[data-field="text"]');
    const text = textInput?.value?.trim();
    if (!text) {
        window.notifyError('第 ' + chunkIndex + ' 段文本为空');
        return;
    }

    if (!confirm(`确定重新生成第 ${chunkIndex} 段的 TTS 语音吗？`)) {
        return;
    }

    const btn = event?.target?.closest('button');
    const originalText = btn?.textContent;
    if (btn) {
        btn.textContent = '生成中...';
        btn.disabled = true;
    }

    try {
        const ttsSettings = window.getCurrentTtsSettings();
        const response = await api('POST', `/jobs/${jobId}/tts/chunks/${chunkIndex}/regenerate`, {
            chunk_index: chunkIndex,
            text: text,
            prompt_wav: ttsSettings.prompt_wav,
            prompt_text: ttsSettings.prompt_text,
            tts_provider: ttsSettings.tts_provider,
            tts_runtime_env: ttsSettings.tts_runtime_env,
            tts_mode: ttsSettings.tts_mode,
            model_name: ttsSettings.model_name,
            speed: ttsSettings.speed,
            rocm_gfx_override: ttsSettings.rocm_gfx_override,
            disable_text_frontend: ttsSettings.disable_text_frontend,
            threads: ttsSettings.threads,
            emo_text: ttsSettings.emo_text,
            emo_alpha: ttsSettings.emo_alpha,
        });

        if (response.status === 'success') {
            window.notifySuccess(`第 ${chunkIndex} 段 TTS 语音已重新生成`);
        } else {
            window.notifyError('生成失败: ' + (response.detail || '未知错误'));
        }
    } catch (err) {
        console.error('Regenerate chunk failed:', err);
        window.notifyError('生成失败: ' + err.message);
    } finally {
        if (btn) {
            btn.textContent = originalText || '重新生成';
            btn.disabled = false;
        }
    }
};

window.getCurrentTtsSettings = function() {
    return {
        prompt_wav: document.getElementById('prompt-wav')?.value || '',
        prompt_text: document.getElementById('prompt-text')?.value || '',
        tts_provider: document.getElementById('tts-provider')?.value || 'cosyvoice',
        tts_runtime_env: document.getElementById('tts-runtime-env')?.value || 'rocm6.3',
        tts_mode: document.getElementById('tts-mode')?.value || 'instruct2',
        model_name: document.getElementById('tts-model')?.value || 'Fun-CosyVoice3-0.5B-2512_RL',
        speed: parseFloat(document.getElementById('speed')?.value || '1.0'),
        rocm_gfx_override: document.getElementById('tts-rocm-gfx')?.value || null,
        disable_text_frontend: false,
        threads: parseInt(document.getElementById('tts-threads')?.value || '4'),
        emo_text: document.getElementById('tts-emo-text')?.value || '',
        emo_alpha: parseFloat(document.getElementById('tts-emo-alpha')?.value || '0.6'),
    };
};
