document.addEventListener('DOMContentLoaded', function() {
    const tabs = document.querySelectorAll('.tab');
    const tabContents = document.querySelectorAll('.tab-content');
    const settingsNavItems = document.querySelectorAll('.settings-nav-item');
    const settingsPanels = document.querySelectorAll('.settings-panel');

    function activateSettingsPanel(panelId) {
        settingsNavItems.forEach(item => {
            item.classList.toggle('active', item.dataset.settingsPanel === panelId);
        });
        settingsPanels.forEach(panel => {
            panel.classList.toggle('active', panel.id === 'settings-panel-' + panelId);
        });
        if (panelId === 'operation-manual' && typeof loadOperationManual === 'function') {
            loadOperationManual();
        }
        if (panelId === 'tts-settings' && typeof loadTtsSettings === 'function') {
            loadTtsSettings();
        }
    }

    tabs.forEach(tab => {
        tab.addEventListener('click', function() {
            const tabId = this.dataset.tab;

            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(tc => tc.classList.remove('active'));

            this.classList.add('active');
            const targetContent = document.getElementById('tab-' + tabId);
            if (targetContent) {
                targetContent.classList.add('active');
            }

            const activeJobId = (typeof currentJobId !== 'undefined' && currentJobId) || document.getElementById('caption-job-select')?.value || '';
            if (tabId === 'trim' && activeJobId) {
                const trimSelect = document.getElementById('trim-job-select');
                if (trimSelect) {
                    trimSelect.value = activeJobId;
                }
                if (typeof loadTrimInfo === 'function') {
                    loadTrimInfo(activeJobId);
                }
            }

            if (tabId === 'compose' && activeJobId) {
                const composeSelect = document.getElementById('compose-job-select');
                if (composeSelect) {
                    composeSelect.value = activeJobId;
                }
                if (typeof loadComposeInfo === 'function') {
                    loadComposeInfo(activeJobId);
                }
            }

            if (tabId === 'captions' && activeJobId) {
                const captionSelect = document.getElementById('caption-job-select');
                if (captionSelect) {
                    captionSelect.value = activeJobId;
                }
                if (typeof loadCaptions === 'function') {
                    loadCaptions(activeJobId, window.currentCaptionViewStage || 'auto');
                }
                if (typeof loadSavedTtsSegments === 'function') {
                    loadSavedTtsSegments(activeJobId);
                }
            }

            if (tabId === 'settings') {
                const activeSettingsItem = document.querySelector('.settings-nav-item.active');
                activateSettingsPanel(activeSettingsItem?.dataset.settingsPanel || 'operation-manual');
            }
        });
    });

    settingsNavItems.forEach(item => {
        item.addEventListener('click', function() {
            activateSettingsPanel(this.dataset.settingsPanel);
        });
    });
});
