function escapeManualHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function renderManualInline(text) {
    let html = escapeManualHtml(text);
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<figure class="manual-figure"><img src="$2" alt="$1"><figcaption>$1</figcaption></figure>');
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    return html;
}

function renderManualMarkdown(markdown) {
    const lines = (markdown || '').replace(/\r\n/g, '\n').split('\n');
    const parts = [];
    let paragraph = [];
    let listItems = [];
    let codeLines = [];
    let inCodeBlock = false;

    function flushParagraph() {
        if (!paragraph.length) return;
        parts.push(`<p>${renderManualInline(paragraph.join(' '))}</p>`);
        paragraph = [];
    }

    function flushList() {
        if (!listItems.length) return;
        parts.push(`<ul>${listItems.map(item => `<li>${renderManualInline(item)}</li>`).join('')}</ul>`);
        listItems = [];
    }

    function flushCode() {
        if (!codeLines.length) return;
        parts.push(`<pre><code>${escapeManualHtml(codeLines.join('\n'))}</code></pre>`);
        codeLines = [];
    }

    for (const rawLine of lines) {
        const line = rawLine.trimEnd();

        if (line.startsWith('```')) {
            flushParagraph();
            flushList();
            if (inCodeBlock) {
                flushCode();
                inCodeBlock = false;
            } else {
                inCodeBlock = true;
            }
            continue;
        }

        if (inCodeBlock) {
            codeLines.push(rawLine);
            continue;
        }

        if (!line.trim()) {
            flushParagraph();
            flushList();
            continue;
        }

        const heading = line.match(/^(#{1,3})\s+(.*)$/);
        if (heading) {
            flushParagraph();
            flushList();
            const level = Math.min(heading[1].length, 3);
            parts.push(`<h${level + 1}>${renderManualInline(heading[2])}</h${level + 1}>`);
            continue;
        }

        const listItem = line.match(/^[-*]\s+(.*)$/);
        if (listItem) {
            flushParagraph();
            listItems.push(listItem[1]);
            continue;
        }

        const numbered = line.match(/^\d+\.\s+(.*)$/);
        if (numbered) {
            flushParagraph();
            listItems.push(numbered[1]);
            continue;
        }

        paragraph.push(line);
    }

    flushParagraph();
    flushList();
    flushCode();
    return parts.join('');
}

async function loadOperationManual() {
    const contentEl = document.getElementById('operation-manual-content');
    const metaEl = document.getElementById('manual-meta');
    if (!contentEl || !metaEl) return;

    contentEl.innerHTML = '<div class="message">加载操作说明中...</div>';

    try {
        const manualUrl = `/static/docs/operation_manual.md?v=${Date.now()}`;
        const response = await fetch(manualUrl, { cache: 'no-store' });
        if (!response.ok) {
            throw new Error(response.statusText || 'Request failed');
        }
        const content = await response.text();
        metaEl.textContent = `来源: webapp/static/docs/operation_manual.md`;
        contentEl.innerHTML = renderManualMarkdown(content);
    } catch (err) {
        contentEl.innerHTML = `<div class="message message-error">加载操作说明失败: ${escapeHtml(err.message)}</div>`;
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const refreshBtn = document.getElementById('manual-refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadOperationManual);
    }
});
