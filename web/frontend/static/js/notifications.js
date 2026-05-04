window.notify = function(type, message, duration = 4000) {
    const container = document.getElementById('toast-container');
    if (!container) {
        console.warn('Toast container not found');
        return;
    }
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    container.appendChild(toast);
    
    if (duration > 0) {
        setTimeout(() => {
            toast.classList.add('toast-exiting');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
    
    return toast;
};

window.notifySuccess = function(message, duration) {
    return window.notify('success', message, duration);
};

window.notifyError = function(message, duration) {
    return window.notify('error', message, duration);
};

window.notifyWarning = function(message, duration) {
    return window.notify('warning', message, duration);
};

window.notifyInfo = function(message, duration) {
    return window.notify('info', message, duration);
};


window.apiAction = async function(options) {
    const {
        button,
        loadingText = '处理中...',
        request,
        onSuccess,
        onError,
        successMessage,
        disableButton = true,
    } = options;
    
    const originalText = button ? button.textContent : '';
    
    if (button && disableButton) {
        button.disabled = true;
        if (loadingText) {
            button.textContent = loadingText;
        }
    }
    
    try {
        const result = await request();
        
        if (successMessage) {
            window.notifySuccess(successMessage);
        }
        
        if (onSuccess) {
            await onSuccess(result);
        }
        
        return result;
        
    } catch (err) {
        const errorMessage = err.message || '操作失败';
        window.notifyError(errorMessage);
        
        if (onError) {
            await onError(err);
        }
        
        throw err;
        
    } finally {
        if (button && disableButton) {
            button.disabled = false;
            button.textContent = originalText;
        }
    }
};


window.pollJob = async function(jobId, options) {
    const {
        until = (job) => job.status === 'completed',
        onTick,
        onDone,
        onError,
        interval = 2000,
        maxAttempts = 150,
    } = options;
    
    let attempts = 0;
    
    while (attempts < maxAttempts) {
        try {
            const job = await api('GET', `/jobs/${jobId}`);
            
            if (onTick) {
                await onTick(job);
            }
            
            if (until(job)) {
                if (onDone) {
                    await onDone(job);
                }
                return job;
            }
            
            attempts++;
            await new Promise(resolve => setTimeout(resolve, interval));
            
        } catch (err) {
            if (onError) {
                await onError(err);
            }
            throw err;
        }
    }
    
    throw new Error(`轮询超时: ${jobId}`);
};


window.showJobProgress = function(jobId, message) {
    let panel = document.getElementById('job-progress-panel');
    if (!panel) {
        panel = document.createElement('div');
        panel.id = 'job-progress-panel';
        panel.className = 'progress-panel';
        panel.innerHTML = `
            <div class="progress-title">${message || '处理中...'}</div>
            <div class="progress-bar"></div>
            <div class="progress-status"></div>
        `;
        const container = document.querySelector('.container');
        if (container) {
            container.insertBefore(panel, container.firstChild);
        }
    } else {
        panel.querySelector('.progress-title').textContent = message || '处理中...';
    }
    return panel;
};

window.updateJobProgress = function(message, subtext) {
    const panel = document.getElementById('job-progress-panel');
    if (panel) {
        if (message) {
            panel.querySelector('.progress-title').textContent = message;
        }
        if (subtext) {
            let status = panel.querySelector('.progress-status');
            if (!status) {
                status = document.createElement('div');
                status.className = 'progress-status';
                panel.appendChild(status);
            }
            status.textContent = subtext;
        }
    }
};

window.hideJobProgress = function() {
    const panel = document.getElementById('job-progress-panel');
    if (panel) {
        panel.remove();
    }
};
