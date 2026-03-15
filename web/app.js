const state = {
    isAuthenticated: false,
    requiresAuth: false,
    activeSection: "diaries",
    diaryDates: [],
    selectedDiaryDate: "",
    observations: [],
    selectedObservationIndices: new Set(),
    observationPage: 1,
    observationPages: 1,
    observationTotal: 0,
    observationLimit: 12,
    sceneFilter: "",
    sortFilter: "desc",
    memories: [],
    runtime: null,
    health: null,
    diaryObservationsExpanded: false,
    settingsSchema: {},
    settingsValues: {},
    settingsSnapshot: {},
    settingsGroups: [],
    activeSettingsGroup: "persona",
    settingsSearch: "",
    windowCandidates: [],
    activityStats: null,
};

const elements = {
    statusDot: document.getElementById("statusDot"),
    statusText: document.getElementById("statusText"),
    pluginVersion: document.getElementById("pluginVersion"),
    webuiVersion: document.getElementById("webuiVersion"),
    refreshButton: document.getElementById("refreshButton"),
    logoutButton: document.getElementById("logoutButton"),
    diaryCount: document.getElementById("diaryCount"),
    observationCount: document.getElementById("observationCount"),
    memoryCount: document.getElementById("memoryCount"),
    lastUpdated: document.getElementById("lastUpdated"),
    healthMeta: document.getElementById("healthMeta"),
    healthGrid: document.getElementById("healthGrid"),
    diaryList: document.getElementById("diaryList"),
    diaryReflection: document.getElementById("diaryReflection"),
    diaryObservations: document.getElementById("diaryObservations"),
    toggleDiaryObservations: document.getElementById("toggleDiaryObservations"),
    diaryTitle: document.getElementById("diaryTitle"),
    diaryMeta: document.getElementById("diaryMeta"),
    diarySummary: document.getElementById("diarySummary"),
    diaryDateInput: document.getElementById("diaryDateInput"),
    observationList: document.getElementById("observationList"),
    observationMeta: document.getElementById("observationMeta"),
    observationPagination: document.getElementById("observationPagination"),
    sceneFilter: document.getElementById("sceneFilter"),
    sortFilter: document.getElementById("sortFilter"),
    selectAllObservations: document.getElementById("selectAllObservations"),
    clearSelectionsButton: document.getElementById("clearSelectionsButton"),
    clearAllDataButton: document.getElementById("clearAllDataButton"),
    deleteSelectedButton: document.getElementById("deleteSelectedButton"),
    memoryHighlights: document.getElementById("memoryHighlights"),
    memoryGroups: document.getElementById("memoryGroups"),
    loginOverlay: document.getElementById("loginOverlay"),
    loginForm: document.getElementById("loginForm"),
    loginPassword: document.getElementById("loginPassword"),
    loginError: document.getElementById("loginError"),
    todayActivityStats: document.getElementById("todayActivityStats"),
    totalActivityStats: document.getElementById("totalActivityStats"),
    recentActivities: document.getElementById("recentActivities"),
    runtimeMeta: document.getElementById("runtimeMeta"),
    runtimeStats: document.getElementById("runtimeStats"),
    runtimeInsights: document.getElementById("runtimeInsights"),
    runtimeMedia: document.getElementById("runtimeMedia"),
    runtimeMediaMeta: document.getElementById("runtimeMediaMeta"),
    runtimeForm: document.getElementById("runtimeForm"),
    runtimeFeedback: document.getElementById("runtimeFeedback"),
    enabledSelect: document.getElementById("enabledSelect"),
    presetSelect: document.getElementById("presetSelect"),
    checkIntervalInput: document.getElementById("checkIntervalInput"),
    triggerProbabilityInput: document.getElementById("triggerProbabilityInput"),
    interactionFrequencyInput: document.getElementById("interactionFrequencyInput"),
    enableDiarySelect: document.getElementById("enableDiarySelect"),
    enableLearningSelect: document.getElementById("enableLearningSelect"),
    enableMicMonitorSelect: document.getElementById("enableMicMonitorSelect"),
    debugSelect: document.getElementById("debugSelect"),
    stopTasksButton: document.getElementById("stopTasksButton"),
    settingsSummary: document.getElementById("settingsSummary"),
    settingsGroupList: document.getElementById("settingsGroupList"),
    settingsGroupTitle: document.getElementById("settingsGroupTitle"),
    settingsGroupDescription: document.getElementById("settingsGroupDescription"),
    settingsHelper: document.getElementById("settingsHelper"),
    settingsSearchInput: document.getElementById("settingsSearchInput"),
    settingsForm: document.getElementById("settingsForm"),
    settingsFeedback: document.getElementById("settingsFeedback"),
    saveSettingsButton: document.getElementById("saveSettingsButton"),
    resetSettingsButton: document.getElementById("resetSettingsButton"),
    emptyStateTemplate: document.getElementById("emptyStateTemplate"),
    navLinks: Array.from(document.querySelectorAll(".nav-link")),
    sections: Array.from(document.querySelectorAll(".section")),
};

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function cloneEmptyState() {
    return elements.emptyStateTemplate.content.firstElementChild.cloneNode(true);
}

function setConnectionState(type, text) {
    elements.statusDot.className = "status-dot";
    if (type) elements.statusDot.classList.add(type);
    elements.statusText.textContent = text;
}

function formatDateTime(value) {
    if (!value) return "未知时间";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    }).format(date);
}

function formatDateLabel(value) {
    if (!value) return "未指定日期";
    const date = new Date(`${value}T00:00:00`);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("zh-CN", {
        year: "numeric",
        month: "long",
        day: "numeric",
        weekday: "short",
    }).format(date);
}

function formatBytes(value) {
    const size = Number(value || 0);
    if (!Number.isFinite(size) || size <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let current = size;
    let index = 0;
    while (current >= 1024 && index < units.length - 1) {
        current /= 1024;
        index += 1;
    }
    const digits = current >= 100 || index === 0 ? 0 : 1;
    return `${current.toFixed(digits)} ${units[index]}`;
}

async function apiFetch(url, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers,
    });

    let payload = {};
    try {
        payload = await response.json();
    } catch (error) {
        payload = {};
    }

    if (response.status === 401) {
        state.isAuthenticated = false;
        if (state.requiresAuth) showLoginForm("登录已失效，请重新输入密码。");
    }

    if (!response.ok || payload.success === false) {
        const message = payload.error || `请求失败 (${response.status})`;
        throw new Error(`${message} @ ${url}`);
    }

    return payload;
}

function showLoginForm(message = "") {
    elements.loginOverlay.classList.remove("hidden");
    elements.loginOverlay.setAttribute("aria-hidden", "false");
    elements.loginError.textContent = message;
    elements.loginPassword.value = "";
    window.setTimeout(() => elements.loginPassword.focus(), 30);
}

function hideLoginForm() {
    elements.loginOverlay.classList.add("hidden");
    elements.loginOverlay.setAttribute("aria-hidden", "true");
    elements.loginError.textContent = "";
}

function renderLoading(target, text = "正在加载...") {
    target.innerHTML = `<div class="empty-state"><strong>${escapeHtml(text)}</strong></div>`;
}

function switchSection(sectionId) {
    state.activeSection = sectionId;
    elements.navLinks.forEach((link) => {
        link.classList.toggle("active", link.dataset.section === sectionId);
    });
    elements.sections.forEach((section) => {
        section.classList.toggle("active", section.id === sectionId);
    });
}

function updateSummaryCards() {
    elements.diaryCount.textContent = String(state.diaryDates.length);
    elements.observationCount.textContent = String(state.observationTotal);
    elements.memoryCount.textContent = String(state.memories.length);
    elements.lastUpdated.textContent = new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    }).format(new Date());
}

function getSettingMeta(key) {
    return state.settingsSchema[key] || {};
}

function areSettingValuesEqual(left, right) {
    return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
}

function isSettingDirty(key) {
    return !areSettingValuesEqual(state.settingsValues[key], state.settingsSnapshot[key]);
}

function formatSettingPreview(value) {
    if (value === undefined || value === null || value === "") return "空";
    if (typeof value === "boolean") return value ? "开启" : "关闭";
    const text = String(value).replace(/\s+/g, " ").trim();
    return text.length > 18 ? `${text.slice(0, 18)}...` : text;
}

function formatRuntimeSwitch(value, onText = "开启", offText = "关闭") {
    return value ? onText : offText;
}

function truncateLabel(value, maxLength = 18) {
    const text = String(value ?? "").trim();
    if (!text) return "未命名";
    return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function setSettingsValues(updates) {
    state.settingsValues = {
        ...state.settingsValues,
        ...updates,
    };
    renderSettingsGroups();
    renderSettingsForm();
}

function appendWindowCompanionTarget(title) {
    const target = String(title ?? "").trim();
    if (!target) return;

    const current = String(state.settingsValues.window_companion_targets || "")
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);

    const exists = current.some((item) => item.split("|", 1)[0].trim().toLowerCase() === target.toLowerCase());
    if (!exists) current.push(target);

    setSettingsValues({
        enable_window_companion: true,
        window_companion_targets: current.join("\n"),
    });
}

function switchSettingsGroup(groupId) {
    state.activeSettingsGroup = groupId;
    renderSettingsGroups();
    renderSettingsForm();
}

function getVisibleSettingsGroups() {
    const query = state.settingsSearch.trim().toLowerCase();
    if (!query) return state.settingsGroups;

    return state.settingsGroups
        .map((group) => {
            const fields = (group.fields || []).filter((fieldKey) => {
                const meta = getSettingMeta(fieldKey);
                const haystacks = [
                    fieldKey,
                    meta.description || "",
                    meta.hint || "",
                ];
                return haystacks.some((item) => String(item).toLowerCase().includes(query));
            });
            return { ...group, fields };
        })
        .filter((group) => group.fields.length > 0);
}

function shouldShowSettingField(fieldKey, currentValues) {
    const meta = getSettingMeta(fieldKey);
    const condition = meta.condition || {};
    return Object.entries(condition).every(([key, expected]) => currentValues[key] === expected);
}

function createSettingsInput(fieldKey, meta, value) {
    const type = meta.type || "string";

    if (type === "bool") {
        const select = document.createElement("select");
        select.dataset.settingKey = fieldKey;
        select.innerHTML = `
            <option value="true">开启</option>
            <option value="false">关闭</option>
        `;
        select.value = value ? "true" : "false";
        return select;
    }

    if (meta.enum && Array.isArray(meta.enum)) {
        const select = document.createElement("select");
        select.dataset.settingKey = fieldKey;
        select.innerHTML = meta.enum
            .map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`)
            .join("");
        select.value = String(value ?? meta.default ?? "");
        return select;
    }

    const input = document.createElement(meta.type === "text" ? "textarea" : "input");
    input.dataset.settingKey = fieldKey;

    if (meta.type === "text") {
        input.rows = Math.min(12, Math.max(4, String(value ?? meta.default ?? "").split("\n").length + 1));
    } else {
        input.type = meta.type === "password" ? "password" : meta.type === "int" ? "number" : "text";
        if (meta.type === "int") {
            if (meta.min !== undefined) input.min = String(meta.min);
            if (meta.max !== undefined) input.max = String(meta.max);
            input.step = "1";
        }
    }

    input.value = String(value ?? meta.default ?? "");
    return input;
}

function readSettingInputValue(input, meta) {
    if (meta.type === "bool") {
        return input.value === "true";
    }
    if (meta.type === "int") {
        return Number(input.value || 0);
    }
    return input.value;
}

function renderRuntimeInsights(runtime) {
    elements.runtimeInsights.innerHTML = "";
    if (!runtime) return;

    const insights = [
        {
            title: "\u8bc6\u5c4f\u6a21\u5f0f",
            body: runtime.screen_recognition_mode
                ? "\u5f53\u524d\u4e3a\u5f55\u5c4f\u89c6\u9891\u8bc6\u522b\u6a21\u5f0f\u3002\u63d2\u4ef6\u4f1a\u5148\u7528 ffmpeg \u5f55\u5236\u6700\u8fd1\u4e00\u6bb5\u684c\u9762 mp4\uff0c\u518d\u628a\u89c6\u9891 base64 \u4f5c\u4e3a\u591a\u6a21\u6001\u6d88\u606f\u53d1\u7ed9\u6a21\u578b\u7406\u89e3\u3002"
                : runtime.use_shared_screenshot_dir
                    ? `\u5f53\u524d\u4e3a\u5171\u4eab\u622a\u56fe\u76ee\u5f55\u6a21\u5f0f\uff0c\u9002\u5408 Docker \u7b49\u65e0\u6cd5\u76f4\u63a5\u622a\u56fe\u7684\u73af\u5883\u3002${runtime.shared_screenshot_dir ? `\u76ee\u5f55\uff1a${runtime.shared_screenshot_dir}` : "\u5efa\u8bae\u786e\u8ba4\u5171\u4eab\u76ee\u5f55\u8def\u5f84\u5df2\u914d\u7f6e\u4e14\u4f1a\u6301\u7eed\u66f4\u65b0\u3002"}`
                    : "\u5f53\u524d\u4e3a\u5b9e\u65f6\u622a\u56fe\u6a21\u5f0f\uff0c\u9002\u5408\u666e\u901a\u684c\u9762\u73af\u5883\uff0c\u80fd\u907f\u514d\u8bef\u8bfb\u65e7\u622a\u56fe\u3002",
            actions: [{ label: "\u8c03\u6574\u8bc6\u5c4f\u8bbe\u7f6e", action: "open-vision-group" }],
        },
        {
            title: "\u8bc6\u522b\u94fe\u8def",
            body: runtime.use_external_vision
                ? "\u5f53\u524d\u4f1a\u5148\u8c03\u7528\u5916\u90e8\u89c6\u89c9 API\uff0c\u628a\u622a\u56fe\u6216\u5f55\u5c4f\u8f6c\u6210\u8bc6\u522b\u6587\u672c\u540e\uff0c\u518d\u4ea4\u7ed9 AstrBot \u7ed3\u5408\u4e0a\u4e0b\u6587\u56de\u590d\u3002"
                : "\u5f53\u524d\u4e0d\u4f1a\u8c03\u7528\u5916\u90e8\u89c6\u89c9 API\uff0c\u800c\u662f\u628a\u622a\u56fe\u6216\u5f55\u5c4f\u8f6c\u6210 base64 \u591a\u6a21\u6001\u6d88\u606f\uff0c\u76f4\u63a5\u53d1\u7ed9 AstrBot \u5f53\u524d provider\u3002",
            actions: [{ label: "\u67e5\u770b\u89c6\u89c9\u94fe\u8def", action: "open-vision-group" }],
        },
        {
            title: "\u81ea\u7136\u8bed\u8a00\u6c42\u52a9",
            body: runtime.enable_natural_language_screen_assist
                ? "\u5df2\u5f00\u542f\u3002\u7528\u6237\u660e\u786e\u8bf4\u201c\u5e2e\u6211\u770b\u770b\u5c4f\u5e55\u201d\u8fd9\u7c7b\u8bdd\u65f6\uff0cBot \u4f1a\u4e3b\u52a8\u8bc6\u5c4f\u5e76\u7ed9\u5efa\u8bae\u3002"
                : "\u9ed8\u8ba4\u5173\u95ed\uff0c\u53ef\u51cf\u5c11\u8bef\u89e6\u3002\u5982\u679c\u4f60\u5e0c\u671b Bot \u5728\u81ea\u7136\u5bf9\u8bdd\u91cc\u4e3b\u52a8\u5e2e\u4f60\u770b\u5c4f\u5e55\uff0c\u53ef\u4ee5\u624b\u52a8\u6253\u5f00\u3002",
            actions: [
                { label: runtime.enable_natural_language_screen_assist ? "\u5173\u95ed\u6c42\u52a9\u89e6\u53d1" : "\u5f00\u542f\u6c42\u52a9\u89e6\u53d1", action: "toggle-screen-assist" },
                { label: "\u524d\u5f80\u4eba\u683c\u8bbe\u7f6e", action: "open-persona-group" },
            ],
        },
        {
            title: "\u7a97\u53e3\u81ea\u52a8\u966a\u4f34",
            body: runtime.enable_window_companion
                ? `\u5df2\u5f00\u542f\u3002${runtime.window_companion_active_title ? `\u5f53\u524d\u6b63\u966a\u7740\u300a${runtime.window_companion_active_title}\u300b\u3002` : "\u4f1a\u5728\u547d\u4e2d\u7684\u7a97\u53e3\u51fa\u73b0\u65f6\u81ea\u52a8\u8fc7\u6765\uff0c\u7a97\u53e3\u5173\u95ed\u540e\u81ea\u52a8\u9000\u573a\u3002"}`
                : "\u9ed8\u8ba4\u5173\u95ed\u3002\u9002\u5408\u7ed9\u5e38\u7528\u6e38\u620f\u3001IDE \u6216\u89c6\u9891\u64ad\u653e\u5668\u505a\u201c\u7a97\u53e3\u4e00\u5f00\u5c31\u6765\u201d\u7684\u966a\u4f34\u8054\u52a8\u3002",
            actions: [{ label: "\u914d\u7f6e\u7a97\u53e3\u966a\u4f34", action: "open-runtime-group" }],
        },
        {
            title: "\u7d20\u6750\u7559\u5b58",
            body: runtime.save_local
                ? runtime.screen_recognition_mode
                    ? "\u5f53\u524d\u4f1a\u5728\u672c\u5730\u4fdd\u7559\u6700\u8fd1\u4e00\u6b21\u5f55\u5c4f mp4\uff0c\u65b9\u4fbf\u6392\u67e5\u89c6\u9891\u8bc6\u522b\u7ed3\u679c\u3002"
                    : "\u5f53\u524d\u4f1a\u5728\u672c\u5730\u4fdd\u7559\u6700\u8fd1\u4e00\u6b21\u622a\u56fe\uff0c\u65b9\u4fbf\u6392\u67e5\u8bc6\u5c4f\u7ed3\u679c\u3002"
                : "\u5f53\u524d\u4e0d\u4f1a\u4fdd\u7559\u672c\u5730\u8bc6\u522b\u7d20\u6750\uff0c\u66f4\u7701\u7a7a\u95f4\uff0c\u4e5f\u66f4\u504f\u9690\u79c1\u53cb\u597d\u3002",
            actions: [],
        },
    ];

    insights.forEach((item) => {
        const card = document.createElement("article");
        card.className = "helper-card";
        const actions = item.actions.length
            ? `<div class="helper-actions">${item.actions.map((action) => `<button type="button" class="ghost-button helper-button" data-settings-action="${escapeHtml(action.action)}">${escapeHtml(action.label)}</button>`).join("")}</div>`
            : "";
        card.innerHTML = `
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.body)}</p>
            ${actions}
        `;
        elements.runtimeInsights.appendChild(card);
    });
}

function renderRuntimeMedia(runtime) {
    elements.runtimeMedia.innerHTML = "";
    if (!runtime) {
        elements.runtimeMediaMeta.textContent = "等待运行态加载。";
        elements.runtimeMedia.appendChild(cloneEmptyState());
        return;
    }

    if (state.requiresAuth && !state.isAuthenticated) {
        elements.runtimeMediaMeta.textContent = "登录后可查看最新识别素材。";
        elements.runtimeMedia.appendChild(cloneEmptyState());
        return;
    }

    const mediaItems = [runtime.latest_screenshot, runtime.latest_video].filter(Boolean);
    const availableCount = mediaItems.filter((item) => item.available).length;
    elements.runtimeMediaMeta.textContent = availableCount
        ? `当前可预览 ${availableCount} 份最新素材。`
        : "当前没有可直接预览的素材。";

    mediaItems.forEach((item) => {
        const card = document.createElement("article");
        card.className = "runtime-media-card";
        const title = item.kind === "video" ? "最新录屏" : "最新截图";
        const meta = item.available
            ? `${formatDateTime(item.updated_at)} · ${formatBytes(item.size_bytes)}`
            : (item.message || "暂无可预览素材");
        let preview = '<div class="empty-state"><strong>暂无可预览素材</strong></div>';
        if (item.available && item.url) {
            if (item.kind === "video") {
                preview = `
                    <video class="runtime-media-preview" controls preload="metadata">
                        <source src="${escapeHtml(item.url)}" type="video/mp4">
                    </video>
                `;
            } else {
                preview = `<img class="runtime-media-preview" src="${escapeHtml(item.url)}" alt="${escapeHtml(title)}">`;
            }
        }
        const action = item.available && item.url
            ? `<a class="ghost-button runtime-media-link" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">打开原文件</a>`
            : "";
        card.innerHTML = `
            <div class="panel-header">
                <div>
                    <h4>${escapeHtml(title)}</h4>
                    <span class="panel-subtle">${escapeHtml(meta)}</span>
                </div>
                ${action}
            </div>
            <div class="runtime-media-frame">${preview}</div>
        `;
        elements.runtimeMedia.appendChild(card);
    });
}

function renderHealthChecks() {
    elements.healthGrid.innerHTML = "";
    if (!state.health) {
        elements.healthMeta.textContent = "尚未完成服务自检。";
        elements.healthGrid.appendChild(cloneEmptyState());
        return;
    }

    const health = state.health;
    elements.healthMeta.textContent = `最近检查: ${formatDateTime(health.checked_at)} | 服务: ${health.service || "unknown"}`;
    const cards = [
        ["健康状态", health.status || "unknown"],
        ["实例版本", health.version || "--"],
        ["插件版本", health.plugin_version || "--"],
        ["监听地址", `${health.host || "--"}:${health.port || "--"}`],
        ["实例匹配", health.instance_match ? "当前实例" : "可能不是当前实例"],
        ["访问保护", health.auth_enabled ? "已开启" : "未开启"],
        ["服务 PID", health.pid || "--"],
        ["Session 数", health.session_count ?? 0],
    ];

    cards.forEach(([label, value]) => {
        const card = document.createElement("article");
        card.className = "health-card";
        card.innerHTML = `<span class="panel-label">${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
        elements.healthGrid.appendChild(card);
    });
}

function renderSettingsHelper(activeGroup, currentValues) {
    elements.settingsHelper.innerHTML = "";
    if (!activeGroup) return;

    const cards = [];

    if (activeGroup.id === "vision") {
        cards.push({
            title: currentValues.screen_recognition_mode
                ? "\u5f55\u5c4f\u89c6\u9891\u8bc6\u522b\u6a21\u5f0f"
                : currentValues.use_shared_screenshot_dir
                    ? "Docker / \u5171\u4eab\u76ee\u5f55\u6a21\u5f0f"
                    : "\u5b9e\u65f6\u622a\u56fe\u6a21\u5f0f",
            body: currentValues.screen_recognition_mode
                ? "\u4f1a\u5728\u672c\u5730\u7528 ffmpeg \u5f55\u5236\u684c\u9762 mp4\uff0c\u5e76\u5728\u89e6\u53d1\u804a\u5929\u65f6\u628a\u6700\u8fd1\u4e00\u6bb5\u5f55\u5c4f\u4f5c\u4e3a\u8bc6\u522b\u7d20\u6750\u3002\u5efa\u8bae\u786e\u8ba4\u7cfb\u7edf\u91cc\u53ef\u76f4\u63a5\u8c03\u7528 ffmpeg\u3002"
                : currentValues.use_shared_screenshot_dir
                    ? `\u5f53\u524d\u4f1a\u4f18\u5148\u8bfb\u53d6\u5171\u4eab\u76ee\u5f55\u91cc\u7684\u622a\u56fe\u3002${currentValues.shared_screenshot_dir ? `\u76ee\u5f55\uff1a${currentValues.shared_screenshot_dir}` : "\u5efa\u8bae\u8865\u5145\u5171\u4eab\u76ee\u5f55\u8def\u5f84\u3002"}`
                    : "\u666e\u901a\u684c\u9762\u73af\u5883\u63a8\u8350\u4fdd\u6301\u8fd9\u4e2a\u6a21\u5f0f\uff0c\u80fd\u907f\u514d\u8bfb\u5230\u65e7\u56fe\uff0c\u4e5f\u4e0d\u9700\u8981\u989d\u5916\u6302\u8f7d\u622a\u56fe\u76ee\u5f55\u3002",
            actions: currentValues.screen_recognition_mode
                ? []
                : currentValues.use_shared_screenshot_dir
                    ? [{ label: "\u6539\u56de\u5b9e\u65f6\u622a\u56fe\u63a8\u8350\u503c", action: "vision-live" }]
                    : [{ label: "\u5207\u5230 Docker \u6a21\u5f0f", action: "vision-docker" }],
        });
        cards.push({
            title: currentValues.use_external_vision ? "\u4e24\u6b65\u8bc6\u522b\u94fe\u8def" : "\u76f4\u63a5 AstrBot \u591a\u6a21\u6001",
            body: currentValues.use_external_vision
                ? "\u4f1a\u5148\u8c03\u7528\u5916\u90e8\u89c6\u89c9 API \u83b7\u53d6\u8bc6\u522b\u7ed3\u679c\uff0c\u518d\u628a\u8bc6\u522b\u6587\u672c\u548c\u4e0a\u4e0b\u6587\u4ea4\u7ed9 AstrBot \u751f\u6210\u6700\u7ec8\u56de\u590d\u3002"
                : "\u4e0d\u4f1a\u5148\u8d70\u5916\u90e8\u89c6\u89c9 API\uff0c\u800c\u662f\u628a\u622a\u56fe\u6216\u5f55\u5c4f\u76f4\u63a5\u8f6c\u6210 base64 \u591a\u6a21\u6001\u6d88\u606f\u53d1\u7ed9 AstrBot \u5f53\u524d provider\u3002\u524d\u63d0\u662f\u5f53\u524d provider \u771f\u6b63\u652f\u6301\u5bf9\u5e94\u56fe\u7247\u6216\u89c6\u9891\u8f93\u5165\u3002",
            actions: [],
        });
        cards.push({
            title: "\u8bc6\u5c4f\u5efa\u8bae",
            body: "\u5982\u679c\u8981\u51cf\u5c11 token\uff0c\u4f18\u5148\u628a image_prompt \u4fdd\u6301\u7b80\u77ed\uff0c\u5e76\u53ea\u8ba9\u6a21\u578b\u8f93\u51fa\u4efb\u52a1\u3001\u9636\u6bb5\u3001\u5173\u952e\u7ebf\u7d22\u548c\u4e00\u4e2a\u5efa\u8bae\u70b9\u3002",
            actions: [],
        });
    }

    if (activeGroup.id === "persona") {
        cards.push({
            title: currentValues.enable_natural_language_screen_assist ? "\u81ea\u7136\u8bed\u8a00\u8bc6\u5c4f\u6c42\u52a9\u5df2\u5f00\u542f" : "\u81ea\u7136\u8bed\u8a00\u8bc6\u5c4f\u6c42\u52a9\u5df2\u5173\u95ed",
            body: currentValues.enable_natural_language_screen_assist
                ? "\u73b0\u5728\u7528\u6237\u660e\u786e\u6c42\u52a9\u65f6\uff0cBot \u4f1a\u4e3b\u52a8\u770b\u5c4f\u5e55\u518d\u56de\u7b54\u3002\u9002\u5408\u6e38\u620f\u51fa\u88c5\u3001\u505a\u9898\u3001\u6392\u9519\u8fd9\u7c7b\u573a\u666f\u3002"
                : "\u9ed8\u8ba4\u5173\u95ed\u66f4\u7a33\uff0c\u907f\u514d\u666e\u901a\u804a\u5929\u8bef\u89e6\u53d1\u3002\u53ea\u6709\u4f60\u5e0c\u671b Bot \u5728\u81ea\u7136\u5bf9\u8bdd\u91cc\u4e3b\u52a8\u8bc6\u5c4f\u65f6\u518d\u6253\u5f00\u3002",
            actions: [
                { label: currentValues.enable_natural_language_screen_assist ? "\u5173\u95ed\u5b83" : "\u5f00\u542f\u5b83", action: "toggle-screen-assist" },
                { label: "\u67e5\u770b\u8bc6\u5c4f\u8bbe\u7f6e", action: "open-vision-group" },
            ],
        });
    }

    if (activeGroup.id === "runtime") {
        cards.push({
            title: currentValues.enable_window_companion ? "\u7a97\u53e3\u81ea\u52a8\u966a\u4f34\u5df2\u5f00\u542f" : "\u7a97\u53e3\u81ea\u52a8\u966a\u4f34\u5df2\u5173\u95ed",
            body: currentValues.enable_window_companion
                ? "\u547d\u4e2d\u7684\u7a97\u53e3\u51fa\u73b0\u540e\uff0cBot \u4f1a\u81ea\u52a8\u5f00\u966a\u4f34\uff1b\u7a97\u53e3\u5173\u6389\u540e\u4f1a\u81ea\u52a8\u9000\u573a\u3002\u9002\u5408\u5e38\u9a7b\u6e38\u620f\u3001IDE\u3001\u89c6\u9891\u64ad\u653e\u5668\u3002"
                : "\u6253\u5f00\u540e\u5c31\u80fd\u628a\u67d0\u4e2a\u7a97\u53e3\u548c\u966a\u4f34\u4efb\u52a1\u7ed1\u5b9a\u8d77\u6765\uff0c\u4e0d\u9700\u8981\u6bcf\u6b21\u624b\u52a8\u628a Bot \u53eb\u8fc7\u6765\u3002",
            actions: [
                {
                    label: currentValues.enable_window_companion ? "\u5173\u95ed\u81ea\u52a8\u966a\u4f34" : "\u5f00\u542f\u81ea\u52a8\u966a\u4f34",
                    action: "toggle-window-companion",
                },
                { label: "\u8bfb\u53d6\u5f53\u524d\u7a97\u53e3", action: "load-window-candidates" },
            ],
        });

        if (state.windowCandidates.length) {
            cards.push({
                title: "\u5f53\u524d\u7a97\u53e3\u5019\u9009",
                body: "\u70b9\u4e00\u4e2a\u5c31\u4f1a\u628a\u5b83\u8ffd\u52a0\u5230\u201c\u7a97\u53e3\u966a\u4f34\u76ee\u6807\u201d\uff0c\u5e76\u81ea\u52a8\u6253\u5f00\u7a97\u53e3\u966a\u4f34\u5f00\u5173\u3002",
                actions: state.windowCandidates.slice(0, 8).map((title, index) => ({
                    label: truncateLabel(title, 12),
                    action: `window-candidate::${index}`,
                })),
            });
        }
    }

    if (activeGroup.id === "webui") {
        cards.push({
            title: "WebUI \u63d0\u9192",
            body: "host\u3001port \u548c\u8bbf\u95ee\u4fdd\u62a4\u8fd9\u7c7b\u8bbe\u7f6e\u66f4\u9002\u5408\u6539\u5b8c\u540e\u91cd\u542f\u63d2\u4ef6\u518d\u9a8c\u8bc1\u3002\u8fd9\u6837\u66f4\u5bb9\u6613\u907f\u5f00\u7aef\u53e3\u5360\u7528\u548c\u65e7\u5b9e\u4f8b\u6b8b\u7559\u3002",
            actions: [],
        });
    }

    if (!cards.length) {
        elements.settingsHelper.classList.add("hidden");
        return;
    }

    elements.settingsHelper.classList.remove("hidden");
    cards.forEach((item) => {
        const card = document.createElement("article");
        card.className = "helper-card";
        const actions = item.actions.length
            ? `<div class="helper-actions">${item.actions.map((action) => `<button type="button" class="ghost-button helper-button" data-settings-action="${escapeHtml(action.action)}">${escapeHtml(action.label)}</button>`).join("")}</div>`
            : "";
        card.innerHTML = `
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.body)}</p>
            ${actions}
        `;
        elements.settingsHelper.appendChild(card);
    });
}
function renderSettingsGroups() {
    const visibleGroups = getVisibleSettingsGroups();
    elements.settingsGroupList.innerHTML = "";
    const dirtyCount = Object.keys(state.settingsValues).filter((key) => isSettingDirty(key)).length;
    elements.settingsSummary.textContent = visibleGroups.length
        ? `当前可见 ${visibleGroups.length} 个配置分组，待保存 ${dirtyCount} 项。`
        : "没有匹配到配置项。";

    if (!visibleGroups.length) {
        elements.settingsGroupList.appendChild(cloneEmptyState());
        return;
    }

    if (!visibleGroups.some((group) => group.id === state.activeSettingsGroup)) {
        state.activeSettingsGroup = visibleGroups[0].id;
    }

    visibleGroups.forEach((group) => {
        const groupDirtyCount = (group.fields || []).filter((fieldKey) => isSettingDirty(fieldKey)).length;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "settings-group-button";
        if (group.id === state.activeSettingsGroup) button.classList.add("active");
        button.innerHTML = `
            <strong>${escapeHtml(group.title)}${groupDirtyCount ? ` · ${groupDirtyCount}` : ""}</strong>
            <span>${escapeHtml(group.description || "")}</span>
        `;
        button.addEventListener("click", () => {
            state.activeSettingsGroup = group.id;
            renderSettingsGroups();
            renderSettingsForm();
        });
        elements.settingsGroupList.appendChild(button);
    });
}

function renderSettingsForm() {
    const visibleGroups = getVisibleSettingsGroups();
    const activeGroup = visibleGroups.find((group) => group.id === state.activeSettingsGroup);

    elements.settingsForm.innerHTML = "";
    if (!activeGroup) {
        elements.settingsGroupTitle.textContent = "没有匹配结果";
        elements.settingsGroupDescription.textContent = "换个关键词试试，或者清空筛选。";
        elements.settingsHelper.classList.add("hidden");
        elements.settingsHelper.innerHTML = "";
        elements.settingsForm.appendChild(cloneEmptyState());
        return;
    }

    elements.settingsGroupTitle.textContent = activeGroup.title;
    const groupDirtyCount = (activeGroup.fields || []).filter((fieldKey) => isSettingDirty(fieldKey)).length;
    elements.settingsGroupDescription.textContent = `${activeGroup.description || "编辑后点击保存即可写回插件配置。"}${groupDirtyCount ? ` 当前分组有 ${groupDirtyCount} 项待保存。` : ""}`;

    const currentValues = { ...state.settingsValues };
    const visibleFields = activeGroup.fields.filter((fieldKey) => shouldShowSettingField(fieldKey, currentValues));
    renderSettingsHelper(activeGroup, currentValues);

    if (!visibleFields.length) {
        const empty = cloneEmptyState();
        empty.querySelector("strong").textContent = "当前分组没有可编辑项";
        empty.querySelector("p").textContent = "可能是被前置条件隐藏了，也可能是筛选词过于严格。";
        elements.settingsForm.appendChild(empty);
        return;
    }

    visibleFields.forEach((fieldKey) => {
        const meta = getSettingMeta(fieldKey);
        const wrapper = document.createElement("label");
        wrapper.className = meta.type === "text" ? "field settings-field settings-field-wide" : "field settings-field";
        if (isSettingDirty(fieldKey)) wrapper.classList.add("settings-field-dirty");

        const badges = [
            `<span class="settings-badge">默认 ${escapeHtml(formatSettingPreview(meta.default))}</span>`,
            `<code>${escapeHtml(fieldKey)}</code>`,
        ];
        if (isSettingDirty(fieldKey)) {
            badges.unshift('<span class="settings-badge settings-badge-warm">已修改</span>');
        }

        const header = document.createElement("div");
        header.className = "settings-field-header";
        header.innerHTML = `
            <strong>${escapeHtml(meta.description || fieldKey)}</strong>
            <div class="settings-badges">${badges.join("")}</div>
        `;

        const hint = document.createElement("p");
        hint.className = "settings-field-hint";
        hint.textContent = meta.hint || "未提供额外说明。";

        const input = createSettingsInput(fieldKey, meta, currentValues[fieldKey]);
        input.addEventListener("change", () => {
            state.settingsValues[fieldKey] = readSettingInputValue(input, meta);
            renderSettingsForm();
        });

        wrapper.append(header, hint, input);
        elements.settingsForm.appendChild(wrapper);
    });
}
function renderInlineMarkdown(text) {
    return escapeHtml(text)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

function renderDiaryMarkdown(content) {
    if (!content) return "";

    const lines = String(content).replace(/\r\n/g, "\n").split("\n");
    const blocks = [];
    let paragraph = [];
    let listItems = [];
    let codeLines = [];
    let inCodeBlock = false;

    function flushParagraph() {
        if (!paragraph.length) return;
        blocks.push(`<p>${renderInlineMarkdown(paragraph.join("<br>"))}</p>`);
        paragraph = [];
    }

    function flushList() {
        if (!listItems.length) return;
        blocks.push(`<ul>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`);
        listItems = [];
    }

    function flushCode() {
        if (!codeLines.length) return;
        blocks.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
    }

    for (const rawLine of lines) {
        const line = rawLine.trimEnd();

        if (line.startsWith("```")) {
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

        if (line.startsWith("# ")) {
            flushParagraph();
            flushList();
            blocks.push(`<h1>${renderInlineMarkdown(line.slice(2))}</h1>`);
            continue;
        }
        if (line.startsWith("## ")) {
            flushParagraph();
            flushList();
            blocks.push(`<h2>${renderInlineMarkdown(line.slice(3))}</h2>`);
            continue;
        }
        if (line.startsWith("### ")) {
            flushParagraph();
            flushList();
            blocks.push(`<h3>${renderInlineMarkdown(line.slice(4))}</h3>`);
            continue;
        }
        if (line.startsWith("> ")) {
            flushParagraph();
            flushList();
            blocks.push(`<blockquote>${renderInlineMarkdown(line.slice(2))}</blockquote>`);
            continue;
        }
        if (/^[-*] /.test(line)) {
            flushParagraph();
            listItems.push(line.slice(2));
            continue;
        }

        paragraph.push(renderInlineMarkdown(line));
    }

    flushParagraph();
    flushList();
    flushCode();
    return `<div class="diary-rendered">${blocks.join("")}</div>`;
}

function parseDiaryObservationEntries(content) {
    const text = String(content || "").replace(/\r\n/g, "\n").trim();
    if (!text) return [];

    const lines = text.split("\n");
    const entries = [];
    let current = null;

    function pushCurrent() {
        if (!current) return;
        current.body = current.body.map((line) => line.trimEnd()).join("\n").trim();
        entries.push(current);
        current = null;
    }

    for (const rawLine of lines) {
        const line = rawLine.trimEnd();
        const match = line.match(/^###\s+(\d{2}:\d{2}(?::\d{2})?)\s*-\s*(.+)$/);
        if (match) {
            pushCurrent();
            current = {
                time: match[1],
                windowTitle: match[2].trim(),
                body: [],
            };
            continue;
        }

        if (!current) {
            return [];
        }
        current.body.push(rawLine);
    }

    pushCurrent();
    return entries.filter((entry) => entry.body && entry.body.trim());
}

function renderDiaryObservationTimeline(entries) {
    if (!entries.length) return "";

    const items = entries.map((entry) => {
        const bodyHtml = renderDiaryMarkdown(entry.body)
            .replace('<div class="diary-rendered">', '<div class="diary-rendered diary-entry-body">');

        return `
            <article class="diary-observation-entry">
                <div class="diary-observation-marker" aria-hidden="true"></div>
                <div class="diary-observation-main">
                    <div class="diary-observation-head">
                        <span class="diary-observation-time">${escapeHtml(entry.time)}</span>
                        <span class="diary-observation-window">${escapeHtml(entry.windowTitle)}</span>
                    </div>
                    ${bodyHtml}
                </div>
            </article>
        `;
    });

    return `<div class="diary-observation-timeline">${items.join("")}</div>`;
}

function splitDiaryContent(content) {
    const text = String(content || "");
    const sections = {
        full: text.trim(),
        observation: "",
        reflection: "",
    };

    if (!text.trim()) {
        return sections;
    }

    const observationMatch = text.match(/##\s*今日观察\s*([\s\S]*?)(?=\n##\s*今日感想|\n##\s*[^\n]+|$)/);
    const reflectionMatch = text.match(/##\s*今日感想\s*([\s\S]*?)(?=\n##\s*[^\n]+|$)/);

    sections.observation = (observationMatch?.[1] || "").trim();
    sections.reflection = (reflectionMatch?.[1] || "").trim();

    if (!sections.reflection) {
        sections.reflection = text.trim();
    }

    return sections;
}

function renderDiaryList() {
    elements.diaryList.innerHTML = "";
    if (state.diaryDates.length === 0) {
        elements.diaryList.appendChild(cloneEmptyState());
        elements.diarySummary.textContent = "还没有生成任何日记。";
        return;
    }

    elements.diarySummary.textContent = `共 ${state.diaryDates.length} 篇日记，默认打开最近日期。`;
    state.diaryDates.slice(0, 14).forEach((entry) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "list-item-button";
        if (entry.date === state.selectedDiaryDate) button.classList.add("active");
        button.innerHTML = `
            <p class="list-item-title">${escapeHtml(formatDateLabel(entry.date))}</p>
            <p class="list-item-meta">文件名: ${escapeHtml(entry.filename)}</p>
        `;
        button.addEventListener("click", () => {
            elements.diaryDateInput.value = entry.date;
            loadDiaryDetail(entry.date);
        });
        elements.diaryList.appendChild(button);
    });
}

function renderDiaryDetail(date, content) {
    state.selectedDiaryDate = date;
    elements.diaryDateInput.value = date || "";
    renderDiaryList();
    elements.diaryTitle.textContent = date ? `${formatDateLabel(date)} 的日记` : "日记内容";
    elements.diaryMeta.textContent = content ? "已加载完整内容" : "这一天还没有写入内容";

    if (!content) {
        state.diaryObservationsExpanded = false;
        elements.toggleDiaryObservations.textContent = "展开";
        elements.toggleDiaryObservations.disabled = true;
        const empty = cloneEmptyState();
        empty.querySelector("strong").textContent = "这一天还没有日记";
        empty.querySelector("p").textContent = "等插件在当天生成记录后，这里会显示完整内容。";
        elements.diaryReflection.innerHTML = "";
        elements.diaryReflection.appendChild(empty);
        elements.diaryObservations.innerHTML = "";
        elements.diaryObservations.appendChild(cloneEmptyState());
        return;
    }

    const diary = splitDiaryContent(content);
    elements.diaryReflection.innerHTML = renderDiaryMarkdown(diary.reflection || diary.full);

    if (diary.observation) {
        const structuredEntries = parseDiaryObservationEntries(diary.observation);
        elements.diaryObservations.innerHTML = structuredEntries.length
            ? renderDiaryObservationTimeline(structuredEntries)
            : renderDiaryMarkdown(diary.observation);
        state.diaryObservationsExpanded = false;
        elements.diaryObservations.classList.add("diary-content-collapsed");
        elements.toggleDiaryObservations.disabled = false;
        elements.toggleDiaryObservations.textContent = "展开";
    } else {
        const emptyObservation = cloneEmptyState();
        emptyObservation.querySelector("strong").textContent = "今天没有单独整理观察段落";
        emptyObservation.querySelector("p").textContent = "如果后续日记模板保留“今日观察”标题，这里会自动拆分展示。";
        elements.diaryObservations.innerHTML = "";
        elements.diaryObservations.appendChild(emptyObservation);
        elements.diaryObservations.classList.remove("diary-content-collapsed");
        elements.toggleDiaryObservations.disabled = true;
        elements.toggleDiaryObservations.textContent = "展开";
    }
}

function syncObservationSelectionUi() {
    const visibleIndices = state.observations.map((item) => item.index);
    const selectedVisibleCount = visibleIndices.filter((index) => state.selectedObservationIndices.has(index)).length;
    elements.selectAllObservations.checked = Boolean(visibleIndices.length) && selectedVisibleCount === visibleIndices.length;
    elements.deleteSelectedButton.textContent = selectedVisibleCount
        ? `删除选中（${selectedVisibleCount}）`
        : "删除选中";
}

function renderObservationPagination() {
    elements.observationPagination.innerHTML = "";

    const summary = document.createElement("span");
    summary.className = "panel-subtle";
    summary.textContent = state.observationTotal
        ? `当前显示 ${state.observations.length} 条，已选 ${state.selectedObservationIndices.size} 条`
        : "暂无可分页内容";

    const controls = document.createElement("div");
    controls.className = "toolbar";

    const prevButton = document.createElement("button");
    prevButton.type = "button";
    prevButton.className = "page-button";
    prevButton.textContent = "上一页";
    prevButton.disabled = state.observationPage <= 1;
    prevButton.addEventListener("click", async () => {
        state.observationPage -= 1;
        await loadObservations();
    });

    const nextButton = document.createElement("button");
    nextButton.type = "button";
    nextButton.className = "page-button";
    nextButton.textContent = "下一页";
    nextButton.disabled = state.observationPage >= state.observationPages;
    nextButton.addEventListener("click", async () => {
        state.observationPage += 1;
        await loadObservations();
    });

    controls.append(prevButton, nextButton);
    elements.observationPagination.append(summary, controls);
}

async function deleteObservation(index) {
    await apiFetch(`/api/observations/${index}`, { method: "DELETE" });
    state.selectedObservationIndices.delete(index);
    await loadRuntime();
    await loadObservations();
    updateSummaryCards();
}

async function deleteSelectedObservations() {
    const indices = Array.from(state.selectedObservationIndices);
    if (!indices.length) return;
    await apiFetch("/api/observations/batch", {
        method: "DELETE",
        body: JSON.stringify({ indices }),
    });
    state.selectedObservationIndices.clear();
    await loadRuntime();
    await loadObservations();
    updateSummaryCards();
}

function renderObservationList() {
    elements.observationList.innerHTML = "";
    if (state.observations.length === 0) {
        elements.observationList.appendChild(cloneEmptyState());
        elements.observationMeta.textContent = "当前筛选条件下没有观察记录。";
        syncObservationSelectionUi();
        renderObservationPagination();
        return;
    }

    elements.observationMeta.textContent = `第 ${state.observationPage} / ${state.observationPages} 页，共 ${state.observationTotal} 条观察记录。`;

    state.observations.forEach((observation) => {
        const card = document.createElement("article");
        card.className = "observation-card";
        const selected = state.selectedObservationIndices.has(observation.index);
        const tags = [
            observation.scene ? `<span class="tag">${escapeHtml(observation.scene)}</span>` : "",
            observation.active_window ? `<span class="tag">${escapeHtml(observation.active_window)}</span>` : "",
            observation.time_period ? `<span class="tag">${escapeHtml(observation.time_period)}</span>` : "",
        ].filter(Boolean).join("");

        card.innerHTML = `
            <div class="observation-header">
                <div>
                    <h3 class="list-item-title">${escapeHtml(formatDateTime(observation.timestamp))}</h3>
                    <div class="observation-tags">${tags || "未标注场景"}</div>
                </div>
                <label class="observation-select">
                    <input type="checkbox" ${selected ? "checked" : ""}>
                    <span>选择</span>
                </label>
            </div>
            <p class="observation-content">${escapeHtml(observation.content || observation.recognition || "无内容")}</p>
            <div class="observation-footer">
                <span class="panel-subtle">索引 ${escapeHtml(observation.index)}</span>
                <button class="danger-button" type="button">删除这条</button>
            </div>
        `;

        const checkbox = card.querySelector('input[type="checkbox"]');
        checkbox.addEventListener("change", () => {
            if (checkbox.checked) state.selectedObservationIndices.add(observation.index);
            else state.selectedObservationIndices.delete(observation.index);
            syncObservationSelectionUi();
            renderObservationPagination();
        });

        const deleteButton = card.querySelector(".danger-button");
        deleteButton.addEventListener("click", async () => {
            deleteButton.disabled = true;
            try {
                await deleteObservation(observation.index);
            } catch (error) {
                deleteButton.disabled = false;
                elements.observationMeta.textContent = `删除失败: ${error.message}`;
            }
        });

        elements.observationList.appendChild(card);
    });

    syncObservationSelectionUi();
    renderObservationPagination();
}

function renderSceneOptions(observations) {
    const previousValue = state.sceneFilter;
    const scenes = [...new Set((observations || []).map((item) => item.scene).filter(Boolean))];
    elements.sceneFilter.innerHTML = '<option value="">全部场景</option>';
    scenes.forEach((scene) => {
        const option = document.createElement("option");
        option.value = scene;
        option.textContent = scene;
        elements.sceneFilter.appendChild(option);
    });
    elements.sceneFilter.value = scenes.includes(previousValue) ? previousValue : "";
    state.sceneFilter = elements.sceneFilter.value;
}

function renderMemories() {
    elements.memoryHighlights.innerHTML = "";
    elements.memoryGroups.innerHTML = "";
    if (state.memories.length === 0) {
        elements.memoryHighlights.appendChild(cloneEmptyState());
        return;
    }

    [...state.memories]
        .sort((a, b) => (b.priority || 0) - (a.priority || 0))
        .slice(0, 3)
        .forEach((item) => {
            const highlight = document.createElement("article");
            highlight.className = "highlight-card";
            highlight.innerHTML = `
                <p class="panel-label">${escapeHtml(item.category_label)}</p>
                <strong>${escapeHtml(item.title)}</strong>
                <p class="memory-content">${escapeHtml(item.summary)}</p>
            `;
            elements.memoryHighlights.appendChild(highlight);
        });

    const groups = new Map();
    state.memories.forEach((item) => {
        if (!groups.has(item.category_label)) groups.set(item.category_label, []);
        groups.get(item.category_label).push(item);
    });

    groups.forEach((items, categoryLabel) => {
        const panel = document.createElement("article");
        panel.className = "panel memory-card";
        const list = items
            .sort((a, b) => (b.priority || 0) - (a.priority || 0))
            .slice(0, 8)
            .map((item) => `
                <div>
                    <div class="memory-header">
                        <strong>${escapeHtml(item.title)}</strong>
                        <span class="tag">优先级 ${escapeHtml(item.priority ?? 0)}</span>
                    </div>
                    <p class="memory-content">${escapeHtml(item.summary)}</p>
                    <p class="memory-meta">${escapeHtml(item.meta || "")}</p>
                </div>
            `)
            .join("");
        panel.innerHTML = `
            <div class="panel-header">
                <h3>${escapeHtml(categoryLabel)}</h3>
                <span class="panel-subtle">${items.length} 条记录</span>
            </div>
            <div class="memory-list">${list}</div>
        `;
        elements.memoryGroups.appendChild(panel);
    });
}

function renderRuntime() {
    const runtime = state.runtime;
    elements.runtimeStats.innerHTML = "";
    elements.runtimeInsights.innerHTML = "";
    elements.runtimeMedia.innerHTML = "";
    if (!runtime) {
        elements.runtimeMeta.textContent = "尚未加载运行状态。";
        elements.runtimeStats.appendChild(cloneEmptyState());
        renderRuntimeMedia(null);
        return;
    }

    elements.runtimeMeta.textContent = `状态: ${runtime.state || "unknown"} | 自动任务 ${runtime.active_task_count || 0} 个`;
    const cards = [
        ["插件状态", runtime.enabled ? "已启用" : "已关闭"],
        ["运行中", runtime.is_running ? "是" : "否"],
        ["当前模式", runtime.interaction_mode || "未设置"],
        ["生效间隔", `${runtime.current_check_interval || 0} 秒`],
        ["触发概率", `${runtime.current_trigger_probability || 0}%`],
        ["观察记录", `${runtime.observation_count || 0} 条`],
        ["日记功能", runtime.enable_diary ? "开启" : "关闭"],
        ["学习功能", runtime.enable_learning ? "开启" : "关闭"],
        [
            "识屏模式",
            runtime.screen_recognition_mode
                ? "录屏视频"
                : runtime.use_shared_screenshot_dir
                    ? "共享截图"
                    : "实时截图",
        ],
        ["求助识屏", formatRuntimeSwitch(runtime.enable_natural_language_screen_assist)],
        ["窗口陪伴", formatRuntimeSwitch(runtime.enable_window_companion)],
        ["陪伴目标", runtime.window_companion_active_title || "待命中"],
    ];

    cards.forEach(([label, value]) => {
        const item = document.createElement("div");
        item.className = "runtime-stat";
        item.innerHTML = `<span class="panel-label">${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
        elements.runtimeStats.appendChild(item);
    });

    elements.enabledSelect.value = String(Boolean(runtime.enabled));
    elements.checkIntervalInput.value = runtime.check_interval ?? runtime.current_check_interval ?? 300;
    elements.triggerProbabilityInput.value = runtime.trigger_probability ?? runtime.current_trigger_probability ?? 30;
    elements.interactionFrequencyInput.value = runtime.interaction_frequency ?? 5;
    elements.enableDiarySelect.value = String(Boolean(runtime.enable_diary));
    elements.enableLearningSelect.value = String(Boolean(runtime.enable_learning));
    elements.enableMicMonitorSelect.value = String(Boolean(runtime.enable_mic_monitor));
    elements.debugSelect.value = String(Boolean(runtime.debug));

    elements.presetSelect.innerHTML = '<option value="-1">手动配置</option>';
    (runtime.presets || []).forEach((preset) => {
        const option = document.createElement("option");
        option.value = String(preset.index);
        option.textContent = `${preset.index}. ${preset.name} (${preset.check_interval}s / ${preset.trigger_probability}%)`;
        elements.presetSelect.appendChild(option);
    });
    elements.presetSelect.value = String(runtime.current_preset_index ?? -1);
    renderRuntimeInsights(runtime);
    renderRuntimeMedia(runtime);
}
async function loadConfig() {
    const data = await apiFetch("/api/config");
    elements.pluginVersion.textContent = data.plugin_version || "--";
    elements.webuiVersion.textContent = data.version || "--";
}

async function loadRuntime() {
    const data = await apiFetch("/api/runtime");
    state.runtime = data.runtime || null;
    renderRuntime();
}

async function loadHealth() {
    const data = await apiFetch("/api/health");
    state.health = data || null;
    renderHealthChecks();
}

async function loadSettings() {
    const data = await apiFetch("/api/settings");
    const settings = data.settings || {};
    state.settingsSchema = settings.schema || {};
    state.settingsValues = settings.values || {};
    state.settingsSnapshot = { ...(settings.values || {}) };
    state.settingsGroups = settings.groups || [];

    if (!state.settingsGroups.some((group) => group.id === state.activeSettingsGroup)) {
        state.activeSettingsGroup = state.settingsGroups[0]?.id || "";
    }

    renderSettingsGroups();
    renderSettingsForm();
}

async function loadWindowCandidates() {
    const data = await apiFetch("/api/windows");
    state.windowCandidates = (data.windows || []).filter(Boolean);
    renderSettingsForm();
}

async function loadDiaries() {
    renderLoading(elements.diaryList, "正在整理日记列表...");
    const data = await apiFetch("/api/diaries");
    state.diaryDates = data.diaries || [];
    if (!state.selectedDiaryDate) {
        state.selectedDiaryDate = state.diaryDates[0]?.date || new Date().toISOString().slice(0, 10);
    }
    renderDiaryList();
    await loadDiaryDetail(state.selectedDiaryDate);
}

async function loadDiaryDetail(date) {
    state.selectedDiaryDate = date;
    elements.diaryTitle.textContent = "正在载入日记...";
    renderLoading(elements.diaryReflection, "正在读取日记内容...");
    renderLoading(elements.diaryObservations, "正在整理观察记录...");
    const data = await apiFetch(`/api/diary/${date}`);
    renderDiaryDetail(data.date, data.content || "");
}

async function loadObservationScenes() {
    const data = await apiFetch("/api/observations?limit=200&sort=desc");
    renderSceneOptions(data.observations || []);
}

async function loadObservations() {
    renderLoading(elements.observationList, "正在读取观察记录...");
    const query = new URLSearchParams({
        page: String(state.observationPage),
        limit: String(state.observationLimit),
        sort: state.sortFilter,
    });
    if (state.sceneFilter) query.set("scene", state.sceneFilter);
    const data = await apiFetch(`/api/observations?${query.toString()}`);
    state.observations = data.observations || [];
    state.observationPage = data.page || 1;
    state.observationPages = data.pages || 1;
    state.observationTotal = data.total || 0;

    const visibleIndices = new Set(state.observations.map((item) => item.index));
    state.selectedObservationIndices.forEach((index) => {
        if (!Number.isInteger(index)) state.selectedObservationIndices.delete(index);
    });
    renderObservationList();
}

async function loadMemories() {
    renderLoading(elements.memoryGroups, "正在检索长期记忆...");
    const data = await apiFetch("/api/memories");
    state.memories = data.memories || [];
    renderMemories();
}

async function loadActivityStats() {
    renderLoading(elements.todayActivityStats, "正在加载活动统计...");
    renderLoading(elements.totalActivityStats, "正在加载活动统计...");
    renderLoading(elements.recentActivities, "正在加载活动统计...");
    try {
        const data = await apiFetch("/api/activity");
        state.activityStats = data;
        renderActivityStats();
    } catch (error) {
        console.error("加载活动统计失败:", error);
        elements.todayActivityStats.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法获取活动统计数据</p></div>";
        elements.totalActivityStats.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法获取活动统计数据</p></div>";
        elements.recentActivities.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法获取活动统计数据</p></div>";
    }
}

function renderActivityStats() {
    if (!state.activityStats) return;
    
    const today = state.activityStats.today || {};
    const total = state.activityStats.total || {};
    const recentActivities = state.activityStats.recent_activities || [];
    
    // 渲染今日统计
    elements.todayActivityStats.innerHTML = `
        <div class="activity-stat-item">
            <span class="panel-label">工作时间</span>
            <strong>${today.work_time || "0分0秒"}</strong>
        </div>
        <div class="activity-stat-item">
            <span class="panel-label">摸鱼时间</span>
            <strong>${today.play_time || "0分0秒"}</strong>
        </div>
        <div class="activity-stat-item">
            <span class="panel-label">其他时间</span>
            <strong>${today.other_time || "0分0秒"}</strong>
        </div>
        <div class="activity-stat-item">
            <span class="panel-label">总时间</span>
            <strong>${today.total_time || "0分0秒"}</strong>
        </div>
    `;
    
    // 渲染总计统计
    elements.totalActivityStats.innerHTML = `
        <div class="activity-stat-item">
            <span class="panel-label">工作时间</span>
            <strong>${total.work_time || "0分0秒"}</strong>
        </div>
        <div class="activity-stat-item">
            <span class="panel-label">摸鱼时间</span>
            <strong>${total.play_time || "0分0秒"}</strong>
        </div>
        <div class="activity-stat-item">
            <span class="panel-label">其他时间</span>
            <strong>${total.other_time || "0分0秒"}</strong>
        </div>
        <div class="activity-stat-item">
            <span class="panel-label">总时间</span>
            <strong>${total.total_time || "0分0秒"}</strong>
        </div>
    `;
    
    // 渲染最近活动
    if (recentActivities.length === 0) {
        elements.recentActivities.innerHTML = "<div class='empty-state'><strong>暂无活动记录</strong><p>开始使用插件后，这里会显示您的活动记录</p></div>";
        return;
    }
    
    elements.recentActivities.innerHTML = recentActivities.map(activity => `
        <article class="observation-card">
            <div class="observation-header">
                <div>
                    <h3 class="list-item-title">${escapeHtml(activity.type)} - ${escapeHtml(activity.scene)}</h3>
                    <div class="observation-tags">
                        <span class="tag">${escapeHtml(activity.window)}</span>
                        <span class="tag">${escapeHtml(activity.duration)}</span>
                    </div>
                </div>
            </div>
            <p class="observation-content">${escapeHtml(activity.start_time)} - ${escapeHtml(activity.end_time)}</p>
        </article>
    `).join("");
}

async function refreshActiveSection() {
    await loadConfig();
    await loadRuntime();
    await loadHealth();
    await loadSettings();
    await loadDiaries();
    await loadObservationScenes();
    await loadObservations();
    await loadMemories();
    await loadActivityStats();
    updateSummaryCards();
}

function collectVisibleSettingsUpdates() {
    const updates = {};
    const inputs = elements.settingsForm.querySelectorAll("[data-setting-key]");
    inputs.forEach((input) => {
        const key = input.dataset.settingKey;
        const meta = getSettingMeta(key);
        updates[key] = readSettingInputValue(input, meta);
    });
    return updates;
}

async function initialize() {
    const authInfo = await apiFetch("/auth/info");
    state.requiresAuth = Boolean(authInfo.requires_auth);
    state.isAuthenticated = Boolean(authInfo.authenticated) || !state.requiresAuth;
    elements.logoutButton.classList.toggle("hidden", !state.requiresAuth);
    if (state.requiresAuth && !state.isAuthenticated) {
        setConnectionState("error", "当前 WebUI 已启用访问保护，请先登录。");
        showLoginForm();
        return;
    }
    hideLoginForm();
    setConnectionState("online", "WebUI 服务连接正常。");
    await refreshActiveSection();
}

function readRuntimeFormValues() {
    return {
        enabled: elements.enabledSelect.value === "true",
        current_preset_index: Number(elements.presetSelect.value),
        check_interval: Number(elements.checkIntervalInput.value),
        trigger_probability: Number(elements.triggerProbabilityInput.value),
        interaction_frequency: Number(elements.interactionFrequencyInput.value),
        enable_diary: elements.enableDiarySelect.value === "true",
        enable_learning: elements.enableLearningSelect.value === "true",
        enable_mic_monitor: elements.enableMicMonitorSelect.value === "true",
        debug: elements.debugSelect.value === "true",
    };
}

elements.navLinks.forEach((link) => {
    link.addEventListener("click", async (event) => {
        event.preventDefault();
        switchSection(link.dataset.section);
        history.replaceState(null, "", `#${link.dataset.section}`);
        await refreshActiveSection();
    });
});

elements.refreshButton.addEventListener("click", async () => {
    setConnectionState("online", "正在刷新数据...");
    try {
        await refreshActiveSection();
        setConnectionState("online", "数据已刷新。");
    } catch (error) {
        setConnectionState("error", `鍒锋柊澶辫触: ${error.message}`);
    }
});

elements.diaryDateInput.addEventListener("change", async () => {
    if (elements.diaryDateInput.value) await loadDiaryDetail(elements.diaryDateInput.value);
});

elements.toggleDiaryObservations.addEventListener("click", () => {
    state.diaryObservationsExpanded = !state.diaryObservationsExpanded;
    elements.diaryObservations.classList.toggle("diary-content-collapsed", !state.diaryObservationsExpanded);
    elements.toggleDiaryObservations.textContent = state.diaryObservationsExpanded ? "收起" : "展开";
});

elements.sceneFilter.addEventListener("change", async () => {
    state.sceneFilter = elements.sceneFilter.value;
    state.observationPage = 1;
    await loadObservations();
    updateSummaryCards();
});

elements.sortFilter.addEventListener("change", async () => {
    state.sortFilter = elements.sortFilter.value;
    state.observationPage = 1;
    await loadObservations();
});

elements.selectAllObservations.addEventListener("change", () => {
    if (elements.selectAllObservations.checked) {
        state.observations.forEach((item) => state.selectedObservationIndices.add(item.index));
    } else {
        state.observations.forEach((item) => state.selectedObservationIndices.delete(item.index));
    }
    renderObservationList();
});

elements.clearSelectionsButton.addEventListener("click", () => {
    state.selectedObservationIndices.clear();
    renderObservationList();
});

elements.deleteSelectedButton.addEventListener("click", async () => {
    if (!state.selectedObservationIndices.size) {
        elements.observationMeta.textContent = "请先选择要删除的观察记录。";
        return;
    }
    try {
        await deleteSelectedObservations();
        elements.observationMeta.textContent = "已删除选中的观察记录。";
    } catch (error) {
        elements.observationMeta.textContent = `批量删除失败: ${error.message}`;
    }
});

elements.clearAllDataButton.addEventListener("click", async () => {
    const confirmed = confirm("确定要清空所有资料吗？\n这将删除：观察记录、学习数据、长期记忆、纠正数据、日记等。\n此操作不可恢复！");
    if (!confirmed) return;
    
    const doubleConfirmed = confirm("再次确认：此操作将永久删除所有数据，确定继续吗？");
    if (!doubleConfirmed) return;
    
    try {
        const result = await apiFetch("/api/data/clear", {
            method: "POST",
            body: JSON.stringify({ confirm: true }),
        });
        
        if (result.success) {
            alert(`已清空以下资料：${result.message}`);
            state.selectedObservationIndices.clear();
            await loadObservations();
        } else {
            alert(`清空失败：${result.error}`);
        }
    } catch (error) {
        alert(`清空失败：${error.message}`);
    }
});

elements.loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    elements.loginError.textContent = "";
    try {
        await apiFetch("/auth/login", {
            method: "POST",
            body: JSON.stringify({ password: elements.loginPassword.value }),
        });
        state.isAuthenticated = true;
        hideLoginForm();
        setConnectionState("online", "登录成功，正在加载数据。");
        await refreshActiveSection();
    } catch (error) {
        elements.loginError.textContent = `鐧诲綍澶辫触: ${error.message}`;
    }
});

elements.settingsHelper.addEventListener("click", async (event) => {
    const action = event.target.closest("[data-settings-action]")?.dataset.settingsAction;
    if (!action) return;

    if (action === "open-vision-group") {
        switchSettingsGroup("vision");
        return;
    }
    if (action === "open-runtime-group") {
        switchSettingsGroup("runtime");
        return;
    }
    if (action === "open-persona-group") {
        switchSettingsGroup("persona");
        return;
    }
    if (action === "toggle-screen-assist") {
        setSettingsValues({
            enable_natural_language_screen_assist: !Boolean(state.settingsValues.enable_natural_language_screen_assist),
        });
        return;
    }
    if (action === "vision-live") {
        setSettingsValues({
            use_shared_screenshot_dir: false,
            shared_screenshot_dir: "",
        });
        return;
    }
    if (action === "vision-docker") {
        setSettingsValues({
            use_shared_screenshot_dir: true,
        });
        return;
    }
    if (action === "toggle-window-companion") {
        setSettingsValues({
            enable_window_companion: !Boolean(state.settingsValues.enable_window_companion),
        });
        return;
    }
    if (action === "load-window-candidates") {
        elements.settingsFeedback.textContent = "正在读取当前窗口列表...";
        try {
            await loadWindowCandidates();
            elements.settingsFeedback.textContent = state.windowCandidates.length
                ? "已载入当前窗口列表，点按钮即可加入陪伴目标。"
                : "没有读取到可用窗口，请确认桌面环境和权限正常。";
        } catch (error) {
            elements.settingsFeedback.textContent = `读取窗口失败: ${error.message}`;
        }
        return;
    }
    if (action.startsWith("window-candidate::")) {
        const index = Number(action.split("::")[1]);
        const title = state.windowCandidates[index];
        appendWindowCompanionTarget(title);
        elements.settingsFeedback.textContent = title
            ? `已把“${title}”加入窗口陪伴目标。`
            : "这个窗口候选已经失效，请重新读取窗口列表。";
    }
});
elements.runtimeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    elements.runtimeFeedback.textContent = "";
    try {
        const data = await apiFetch("/api/runtime/config", {
            method: "POST",
            body: JSON.stringify(readRuntimeFormValues()),
        });
        state.runtime = data.runtime || null;
        renderRuntime();
        elements.runtimeFeedback.textContent = "运行设置已保存。";
    } catch (error) {
        elements.runtimeFeedback.textContent = `保存失败: ${error.message}`;
    }
});

    elements.settingsSearchInput.addEventListener("input", () => {
    state.settingsSearch = elements.settingsSearchInput.value || "";
    renderSettingsGroups();
    renderSettingsForm();
});

elements.resetSettingsButton.addEventListener("click", () => {
    state.settingsValues = { ...state.settingsSnapshot };
    renderSettingsForm();
    elements.settingsFeedback.textContent = "当前分组已恢复为最近一次加载到的值。";
});

elements.saveSettingsButton.addEventListener("click", async () => {
    elements.settingsFeedback.textContent = "";
    try {
        const updates = collectVisibleSettingsUpdates();
        const data = await apiFetch("/api/settings", {
            method: "POST",
            body: JSON.stringify({ updates }),
        });
        const settings = data.settings || {};
        state.settingsSchema = settings.schema || state.settingsSchema;
        state.settingsValues = settings.values || state.settingsValues;
        state.settingsSnapshot = { ...(settings.values || state.settingsValues) };
        state.settingsGroups = settings.groups || state.settingsGroups;
        renderSettingsGroups();
        renderSettingsForm();
        await loadRuntime();
        elements.settingsFeedback.textContent = "配置已保存，相关运行态已同步刷新。";
    } catch (error) {
        elements.settingsFeedback.textContent = `保存失败: ${error.message}`;
    }
});

elements.stopTasksButton.addEventListener("click", async () => {
    elements.runtimeFeedback.textContent = "";
    try {
        const data = await apiFetch("/api/runtime/stop", { method: "POST" });
        state.runtime = data.runtime || null;
        renderRuntime();
        elements.runtimeFeedback.textContent = "当前自动任务已停止。";
    } catch (error) {
        elements.runtimeFeedback.textContent = `鍋滄澶辫触: ${error.message}`;
    }
});

elements.logoutButton.addEventListener("click", async () => {
    try {
        await apiFetch("/auth/logout", { method: "POST" });
    } catch (error) {
        console.error(error);
    }
    state.isAuthenticated = false;
    showLoginForm("已退出登录。");
    setConnectionState("error", "已退出登录，请重新输入密码。");
});

window.addEventListener("DOMContentLoaded", async () => {
    const hash = window.location.hash.replace("#", "");
    if (["runtime", "settings", "diaries", "observations", "memories"].includes(hash)) {
        switchSection(hash);
    }

    try {
        await initialize();
    } catch (error) {
        setConnectionState("error", `初始化失败: ${error.message}`);
    }
});



