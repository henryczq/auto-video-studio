const API_BASE = '/api';

let currentJobId = null;
let terms = {};
let appConfig = null;
let aiConfig = { active_id: '', prompt: '', models: [] };
let selectedAiModelId = '';
let apiToken = localStorage.getItem('autocut_token') || '';

let qrEventSource = null;
let qrCurrentSession = null;
let qrCurrentPlatform = null;
let qrCurrentAccount = null;
let qrLoginSuccess = false;
let qrResultPollTimer = null;
let qrRecoveryCandidate = null;

let biliCurrentAccount = null;
let biliCurrentSession = null;
let biliLoginSuccess = false;
let biliExistingAccountId = '';

let socialPlatformsConfig = { platforms: {}, default_categories: {} };

function getState() {
    return {
        currentJobId,
        terms,
        appConfig,
        aiConfig,
        selectedAiModelId,
        apiToken,
    };
}

function setApiToken(token) {
    apiToken = token;
    localStorage.setItem('autocut_token', token);
}

function getApiToken() {
    return apiToken;
}

function setSocialPlatformsConfig(config) {
    socialPlatformsConfig = config && typeof config === 'object'
        ? config
        : { platforms: {}, default_categories: {} };
}

function getSocialPlatformsConfig() {
    return socialPlatformsConfig || { platforms: {}, default_categories: {} };
}

function getSocialPlatformEntries() {
    return Object.entries(getSocialPlatformsConfig().platforms || {});
}

function getSocialPlatformInfo(platformId) {
    return (getSocialPlatformsConfig().platforms || {})[platformId] || {};
}

function getSocialPlatformName(platformId) {
    return getSocialPlatformInfo(platformId).name || platformId;
}

function isCliSupported(platformId) {
    const info = getSocialPlatformInfo(platformId);
    return info.support_cli === true;
}

function isWebBridgeSupported(platformId) {
    const info = getSocialPlatformInfo(platformId);
    return info.support_web_bridge === true;
}

function isBrowserLoginSupported(platformId) {
    const info = getSocialPlatformInfo(platformId);
    return info.support_cli === true && info.login_mode === 'headed';
}

function isWebPublishSupported(platformId) {
    return isCliSupported(platformId) || isWebBridgeSupported(platformId);
}

function isDraftSupported(platformId) {
    const info = getSocialPlatformInfo(platformId);
    return info.support_draft === true;
}

function updateLogViewerContent(target, content) {
    const el = typeof target === 'string' ? document.getElementById(target) : target;
    if (!el) return;
    el.textContent = content || '';
    el.scrollTop = el.scrollHeight;
}

window.updateLogViewerContent = updateLogViewerContent;
