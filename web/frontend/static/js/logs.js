async function loadLogs(jobId) {
    try {
        const [process, tts, compose] = await Promise.all([
            api('GET', `/jobs/${jobId}/logs/process`).catch(() => ({ content: '' })),
            api('GET', `/jobs/${jobId}/logs/tts`).catch(() => ({ content: '' })),
            api('GET', `/jobs/${jobId}/logs/compose`).catch(() => ({ content: '' }))
        ]);

        window.currentTtsProgress = typeof window.parseTtsProgress === 'function'
            ? window.parseTtsProgress(tts.content || '')
            : null;

        const logViewer = document.getElementById('log-viewer');
        updateLogViewerContent(logViewer, [
            '=== Process Log ===',
            process.content || '(empty)',
            '',
            '=== TTS Log ===',
            tts.content || '(empty)',
            '',
            '=== Compose Log ===',
            compose.content || '(empty)'
        ].join('\n'));

        if (window.currentDisplayedTtsJob?.id === jobId) {
            displayTtsResult(window.currentDisplayedTtsJob);
        }
    } catch (err) {
        console.error('Failed to load logs:', err);
    }
}
