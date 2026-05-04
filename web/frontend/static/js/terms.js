// terms 变量已在 state.js 中声明，此处直接使用

window.loadTerms = async function() {
    try {
        terms = await api('GET', '/terms') || {};
        displayTerms();
    } catch (err) {
        console.error('Failed to load terms:', err);
        terms = {};
    }
};

window.displayTerms = function() {
    const tbody = document.querySelector('#terms-table tbody');
    if (!tbody) return;
    const entries = Object.entries(terms);

    if (entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#999;">暂无替换规则</td></tr>';
        return;
    }

    tbody.innerHTML = entries.map(([src, dst]) => `
        <tr data-source="${escapeHtml(src)}">
            <td><input type="text" class="term-edit-src" value="${escapeHtml(src)}" onchange="editTerm(this, '${escapeHtml(src)}', 'src')"></td>
            <td>→</td>
            <td><input type="text" class="term-edit-dst" value="${escapeHtml(dst)}" onchange="editTerm(this, '${escapeHtml(src)}', 'dst')"></td>
            <td><button class="btn btn-danger btn-sm" onclick="deleteTerm('${escapeHtml(src)}')">删除</button></td>
        </tr>
    `).join('');
}

window.editTerm = function(input, oldSource, type) {
    const newValue = input.value.trim();
    if (!newValue) {
        window.notifyWarning('不能为空');
        displayTerms();
        return;
    }

    let newTerms = { ...terms };
    delete newTerms[oldSource];

    if (type === 'src') {
        const dst = terms[oldSource] || '';
        newTerms[newValue] = dst;
    } else {
        newTerms[oldSource] = newValue;
    }

    api('POST', '/terms', newTerms).then(() => {
        terms = newTerms;
        displayTerms();
    }).catch(err => {
        window.notifyError('保存失败: ' + err.message);
        displayTerms();
    });
};

window.deleteTerm = function(source) {
    if (!confirm(`确定删除替换规则 "${source}"？`)) return;

    let newTerms = { ...terms };
    delete newTerms[source];

    api('POST', '/terms', newTerms).then(() => {
        terms = newTerms;
        displayTerms();
        window.notifySuccess('替换规则已删除');
    }).catch(err => {
        window.notifyError('删除失败: ' + err.message);
    });
};

window.addTerm = async function() {
    const srcInput = document.getElementById('term-source');
    const dstInput = document.getElementById('term-target');
    const src = srcInput.value.trim();
    const dst = dstInput.value.trim();

    if (!src) {
        window.notifyWarning('请输入源文字');
        return;
    }
    if (!dst) {
        window.notifyWarning('请输入目标文字');
        return;
    }

    let newTerms = { ...terms, [src]: dst };

    try {
        await api('POST', '/terms', newTerms);
        terms = newTerms;
        displayTerms();
        srcInput.value = '';
        dstInput.value = '';
        window.notifySuccess('替换规则已添加');
    } catch (err) {
        window.notifyError('添加失败: ' + err.message);
    }
};

// 绑定添加按钮点击事件
function bindTermsEvents() {
    const addBtn = document.getElementById('add-term-btn');
    if (addBtn) {
        addBtn.addEventListener('click', window.addTerm);
    }
    
    // 支持回车键添加
    const srcInput = document.getElementById('term-source');
    const dstInput = document.getElementById('term-target');
    if (dstInput) {
        dstInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                window.addTerm();
            }
        });
    }
    if (srcInput) {
        srcInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                const dst = document.getElementById('term-target');
                if (dst) dst.focus();
            }
        });
    }
}

// 页面加载完成后自动加载数据并绑定事件
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        bindTermsEvents();
        window.loadTerms();
    });
} else {
    bindTermsEvents();
    window.loadTerms();
}
