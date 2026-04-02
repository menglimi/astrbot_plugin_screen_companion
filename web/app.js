const state = {
    isAuthenticated: false,
    requiresAuth: false,
    activeSection: "diaries",
    diaryDates: [],
    selectedDiaryDate: "",
    selectedDiaryDates: new Set(),
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
    settingsShowAdvanced: false,
    windowCandidates: [],
    activityStats: null,
    activityFilters: {
        search: "",
        bucket: "all",
        source: "all",
    },
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
    healthChecks: document.getElementById("healthChecks"),
    healthWarnings: document.getElementById("healthWarnings"),
    diaryList: document.getElementById("diaryList"),
    diaryOverview: document.getElementById("diaryOverview"),
    diaryReflection: document.getElementById("diaryReflection"),
    diaryObservations: document.getElementById("diaryObservations"),
    toggleDiaryObservations: document.getElementById("toggleDiaryObservations"),
    diaryTitle: document.getElementById("diaryTitle"),
    diaryMeta: document.getElementById("diaryMeta"),
    diarySummary: document.getElementById("diarySummary"),
    diaryDateInput: document.getElementById("diaryDateInput"),
    diarySelectionMeta: document.getElementById("diarySelectionMeta"),
    selectAllDiaries: document.getElementById("selectAllDiaries"),
    clearDiarySelectionsButton: document.getElementById("clearDiarySelectionsButton"),
    deleteSelectedDiariesButton: document.getElementById("deleteSelectedDiariesButton"),
    deleteCurrentDiaryButton: document.getElementById("deleteCurrentDiaryButton"),
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
    activityCharts: document.getElementById("activityCharts"),
    activityReview: document.getElementById("activityReview"),
    activityInsights: document.getElementById("activityInsights"),
    activityTopWindows: document.getElementById("activityTopWindows"),
    activityTrend: document.getElementById("activityTrend"),
    activityPulse: document.getElementById("activityPulse"),
    activitySessionSummary: document.getElementById("activitySessionSummary"),
    activitySessions: document.getElementById("activitySessions"),
    activityInputStats: document.getElementById("activityInputStats"),
    activityInputDays: document.getElementById("activityInputDays"),
    activitySurfaceSummary: document.getElementById("activitySurfaceSummary"),
    activityAppTrail: document.getElementById("activityAppTrail"),
    activitySiteTrail: document.getElementById("activitySiteTrail"),
    recentActivities: document.getElementById("recentActivities"),
    activitySearchInput: document.getElementById("activitySearchInput"),
    activityBucketFilter: document.getElementById("activityBucketFilter"),
    activitySourceFilter: document.getElementById("activitySourceFilter"),
    clearActivityFiltersButton: document.getElementById("clearActivityFiltersButton"),
    activityFilterSummary: document.getElementById("activityFilterSummary"),
    activityMethodology: document.getElementById("activityMethodology"),
    runtimeMeta: document.getElementById("runtimeMeta"),
    runtimeSummary: document.getElementById("runtimeSummary"),
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
    activityOverview: document.getElementById("activityOverview"),
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
    settingsModeToggle: document.getElementById("settingsModeToggle"),
    settingsSearchInput: document.getElementById("settingsSearchInput"),
    settingsForm: document.getElementById("settingsForm"),
    settingsFeedback: document.getElementById("settingsFeedback"),
    saveSettingsButton: document.getElementById("saveSettingsButton"),
    resetSettingsButton: document.getElementById("resetSettingsButton"),
    emptyStateTemplate: document.getElementById("emptyStateTemplate"),
    navLinks: Array.from(document.querySelectorAll(".nav-link")),
    sections: Array.from(document.querySelectorAll(".section")),
};

function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

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

    let response;
    try {
        response = await fetch(url, {
            credentials: "same-origin",
            ...options,
            headers,
        });
    } catch (error) {
        const method = String(options.method || "GET").toUpperCase();
        const networkError = new Error(
            method === "GET"
                ? `无法连接 WebUI 服务，请确认当前页面仍连着可用实例。(${method} ${url})`
                : `请求没有拿到响应，WebUI 可能正在重启或地址刚被改动。(${method} ${url})`
        );
        networkError.code = "NETWORK_ERROR";
        networkError.requestUrl = url;
        networkError.requestMethod = method;
        networkError.cause = error;
        throw networkError;
    }

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

function setFeedbackMessage(element, message, tone = "") {
    if (!element) return;
    element.textContent = message || "";
    element.dataset.tone = tone || "";
}

function isNetworkError(error) {
    return Boolean(error && error.code === "NETWORK_ERROR");
}

async function waitForWebUiRecovery({
    attempts = 6,
    delayMs = 900,
} = {}) {
    for (let index = 0; index < attempts; index += 1) {
        try {
            await sleep(index === 0 ? 250 : delayMs);
            const health = await apiFetch("/api/health", { method: "GET" });
            if (health?.success !== false) {
                return true;
            }
        } catch (error) {
            if (index === attempts - 1) return false;
        }
    }
    return false;
}

function buildSettingsSaveFailureMessage(error, context = {}) {
    const changedCount = Number(context.changedCount || 0);
    const touchesWebui = Boolean(context.touchesWebui);
    if (isNetworkError(error)) {
        return touchesWebui
            ? "保存请求已发出，WebUI 可能正在重启。"
            : `保存请求已发出，请刷新确认 ${changedCount || "这些"} 项是否生效。`;
    }
    return `保存失败: ${error.message}`;
}

function buildRuntimeSaveFailureMessage(error) {
    if (isNetworkError(error)) {
        return "保存请求已发出，请刷新确认是否生效。";
    }
    return `保存失败: ${error.message}`;
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

function renderUiIcon(name) {
    const icons = {
        work: `
            <svg viewBox="0 0 24 24">
                <path d="M8 6.5V5.8A1.8 1.8 0 0 1 9.8 4h4.4A1.8 1.8 0 0 1 16 5.8v.7"></path>
                <rect x="4" y="6.5" width="16" height="11.5" rx="2"></rect>
                <path d="M4 11.5h16"></path>
            </svg>`,
        play: `
            <svg viewBox="0 0 24 24">
                <path d="M8 8.5 16.5 12 8 15.5Z"></path>
                <circle cx="12" cy="12" r="8.5"></circle>
            </svg>`,
        other: `
            <svg viewBox="0 0 24 24">
                <rect x="5" y="5" width="14" height="14" rx="3"></rect>
                <path d="M9 9h6"></path>
                <path d="M9 12h6"></path>
                <path d="M9 15h3"></path>
            </svg>`,
        total: `
            <svg viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="8.5"></circle>
                <path d="M12 7.5v5l3 2"></path>
            </svg>`,
    };
    return icons[name] || icons.total;
}

function renderActivityMetricItem(type, label, value, hint) {
    return `
        <div class="activity-stat-item activity-stat-item--${type}">
            <span class="activity-stat-icon" aria-hidden="true">${renderUiIcon(type)}</span>
            <div class="activity-stat-copy">
                <span class="panel-label">${escapeHtml(label)}</span>
                <span class="activity-stat-hint">${escapeHtml(hint)}</span>
            </div>
            <strong>${escapeHtml(value || "0分钟")}</strong>
        </div>
    `;
}

function renderActivityMetricGrid(stats) {
    const hasInputEstimate = Boolean(stats?.has_input_estimate);
    const workValue = hasInputEstimate ? getActivityDisplayWorkTime(stats) : (stats?.work_time || "0分钟");
    const workHint = hasInputEstimate
        ? `已扣除 ${stats?.idle_trimmed_time || "0分钟"} 空闲`
        : "专注投入";
    const totalValue = hasInputEstimate ? getActivityDisplayTotalTime(stats) : (stats?.total_time || "0分钟");
    const totalHint = hasInputEstimate ? "工作时段已按输入在场感折算" : "当前统计周期";
    return [
        renderActivityMetricItem("work", hasInputEstimate ? "有效工作" : "工作时间", workValue, workHint),
        renderActivityMetricItem("play", "摸鱼时间", stats.play_time || "0分钟", "娱乐放松"),
        renderActivityMetricItem("other", "其他时间", stats.other_time || "0分钟", "零散切换"),
        renderActivityMetricItem("total", "总时间", totalValue, totalHint),
    ].join("");
}

function formatPercent(part, total) {
    const base = Number(total || 0);
    if (!base) return "0%";
    return `${Math.round((Number(part || 0) / base) * 100)}%`;
}

function renderOverviewPill(label, value, tone = "") {
    const toneClass = tone ? ` overview-pill--${tone}` : "";
    return `
        <article class="overview-pill${toneClass}">
            <span class="panel-label">${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
        </article>
    `;
}

function getActivityDisplayTotalSeconds(stats) {
    const hasInputEstimate = Boolean(stats?.has_input_estimate);
    if (!hasInputEstimate) return Number(stats?.total_seconds || 0);
    return Number(stats?.display_total_seconds ?? stats?.total_seconds ?? 0);
}

function getActivityDisplayTotalTime(stats) {
    const hasInputEstimate = Boolean(stats?.has_input_estimate);
    if (!hasInputEstimate) return stats?.total_time || "0分钟";
    return stats?.display_total_time || stats?.total_time || "0分钟";
}

function getActivityDisplayWorkSeconds(stats) {
    const hasInputEstimate = Boolean(stats?.has_input_estimate);
    if (!hasInputEstimate) return Number(stats?.work_seconds || 0);
    return Number(stats?.effective_work_seconds ?? stats?.work_seconds ?? 0);
}

function getActivityDisplayWorkTime(stats) {
    const hasInputEstimate = Boolean(stats?.has_input_estimate);
    if (!hasInputEstimate) return stats?.work_time || "0分钟";
    return stats?.effective_work_time || stats?.work_time || "0分钟";
}

function buildActivitySegments(stats) {
    const hasInputEstimate = Boolean(stats?.has_input_estimate);
    const totalSeconds = getActivityDisplayTotalSeconds(stats);
    const segments = [
        { key: "work", label: hasInputEstimate ? "有效工作" : "工作", seconds: getActivityDisplayWorkSeconds(stats), value: getActivityDisplayWorkTime(stats) },
        { key: "play", label: "摸鱼", seconds: Number(stats.play_seconds || 0), value: stats.play_time || "0分钟" },
        { key: "other", label: "其他", seconds: Number(stats.other_seconds || 0), value: stats.other_time || "0分钟" },
    ];
    const barHtml = totalSeconds > 0
        ? segments
            .filter((segment) => segment.seconds > 0)
            .map((segment) => `<span class="activity-bar-segment activity-bar-segment--${segment.key}" style="width:${(segment.seconds / totalSeconds) * 100}%"></span>`)
            .join("")
        : '<span class="activity-bar-segment activity-bar-segment--empty" style="width:100%"></span>';
    return { totalSeconds, segments, barHtml };
}

function buildActivityChartCard(title, stats) {
    const hasInputEstimate = Boolean(stats?.has_input_estimate);
    const totalLabel = getActivityDisplayTotalTime(stats);
    const { totalSeconds, segments, barHtml } = buildActivitySegments(stats);
    const legendHtml = segments.map((segment) => {
        const ratio = totalSeconds > 0 ? `${Math.round((segment.seconds / totalSeconds) * 100)}%` : "0%";
        return `
            <li class="activity-legend-item">
                <span class="activity-legend-dot activity-legend-dot--${segment.key}"></span>
                <span>${escapeHtml(segment.label)}</span>
                <strong>${escapeHtml(segment.value)}</strong>
                <em>${escapeHtml(ratio)}</em>
            </li>
        `;
    }).join("");
    const summaryLabel = hasInputEstimate
        ? `总计 ${totalLabel} · 已扣空闲 ${stats?.idle_trimmed_time || "0分钟"}`
        : `总计 ${totalLabel}`;
    return `
        <article class="activity-breakdown-card">
            <div class="activity-breakdown-head">
                <strong>${escapeHtml(title)}</strong>
                <span class="panel-subtle">${escapeHtml(summaryLabel)}</span>
            </div>
            <div class="activity-breakdown-bar">${barHtml}</div>
            <ul class="activity-legend">${legendHtml}</ul>
        </article>
    `;
}

function renderActivityCharts(today, total) {
    if (!elements.activityCharts) return;
    elements.activityCharts.innerHTML = [
        buildActivityChartCard("今日配比", today),
        buildActivityChartCard("累计配比", total),
    ].join("");
}

function renderActivityReviewSection(review) {
    const summaryCards = review.summary_cards || [];
    const insights = review.insights || [];

    if (!elements.activityReview || !elements.activityInsights) return;

    if (summaryCards.length === 0) {
        elements.activityReview.innerHTML = "<div class='empty-state'><strong>暂无回顾</strong><p>积累出更多活动片段后，这里会给出专注与切换总结</p></div>";
        elements.activityInsights.innerHTML = "";
        return;
    }

    elements.activityReview.innerHTML = summaryCards.map((item) => {
        const toneClass = item.tone ? ` activity-review-card--${item.tone}` : "";
        return `
            <article class="activity-review-card${toneClass}">
                <span class="panel-label">${escapeHtml(item.label || "指标")}</span>
                <strong>${escapeHtml(item.value || "暂无")}</strong>
                <p>${escapeHtml(item.detail || "")}</p>
            </article>
        `;
    }).join("");

    elements.activityInsights.innerHTML = insights.map((item) => `
        <article class="activity-insight-card">
            <p>${escapeHtml(item)}</p>
        </article>
    `).join("");
}

function renderActivityTopWindows(review) {
    if (!elements.activityTopWindows) return;
    const topWindows = review.top_windows || [];
    const rangeLabel = review.range_label || "今天";

    if (topWindows.length === 0) {
        elements.activityTopWindows.innerHTML = "<div class='empty-state'><strong>暂无窗口分布</strong><p>有了更多活动样本后，这里会显示时间主要花在哪些窗口</p></div>";
        return;
    }

    elements.activityTopWindows.innerHTML = topWindows.map((item, index) => `
        <article class="activity-window-card">
            <div class="activity-window-rank">${index + 1}</div>
            <div class="activity-window-main">
                <h3 class="list-item-title">${escapeHtml(item.window || "未命名窗口")}</h3>
                <p class="memory-meta">${escapeHtml(rangeLabel)} · ${escapeHtml(item.type || "其他")} · ${escapeHtml(String(item.sessions || 0))} 段活动 · ${escapeHtml(item.share || "0%")}</p>
            </div>
            <strong>${escapeHtml(item.duration || "0分钟")}</strong>
        </article>
    `).join("");
}

function renderActivityTrend(review) {
    if (!elements.activityTrend) return;
    const trend = review.trend || [];

    if (trend.length === 0) {
        elements.activityTrend.innerHTML = "<div class='empty-state'><strong>暂无趋势数据</strong><p>开始使用插件后，这里会生成最近几天的活动节奏图</p></div>";
        return;
    }

    elements.activityTrend.innerHTML = trend.map((day) => {
        const { barHtml } = buildActivitySegments(day);
        const sessionCount = Number(day.session_count || 0);
        const hasInputEstimate = Boolean(day.has_input_estimate);
        const totalLabel = getActivityDisplayTotalTime(day);
        const ratioLabel = hasInputEstimate ? (day.effective_work_ratio || day.work_ratio || "0%") : (day.work_ratio || "0%");
        const metaLabel = hasInputEstimate
            ? `有效工作 ${ratioLabel} · ${String(sessionCount)} 段活动 · 扣空闲 ${day.idle_trimmed_time || "0分钟"}`
            : `工作 ${ratioLabel} · ${String(sessionCount)} 段活动`;
        return `
            <article class="activity-trend-row">
                <div class="activity-trend-head">
                    <strong>${escapeHtml(day.label || day.date || "--")}</strong>
                    <span class="activity-trend-total">${escapeHtml(totalLabel)}</span>
                </div>
                <div class="activity-breakdown-bar activity-breakdown-bar--compact">${barHtml}</div>
                <p class="activity-trend-meta">${escapeHtml(metaLabel)}</p>
            </article>
        `;
    }).join("");
}

function renderInputStatsSection(inputStats) {
    if (!elements.activityInputStats || !elements.activityInputDays) return;

    if (!inputStats || !inputStats.enabled) {
        elements.activityInputStats.innerHTML = "<div class='empty-state'><strong>未启用本地输入统计</strong><p>如果你想看更细的键鼠节奏，可以在配置中心开启这个可选功能。</p></div>";
        elements.activityInputDays.innerHTML = "";
        return;
    }

    if (!inputStats.available && ["missing_dependency", "error"].includes(String(inputStats.status || ""))) {
        elements.activityInputStats.innerHTML = `<div class='empty-state'><strong>输入统计暂不可用</strong><p>${escapeHtml(inputStats.detail || "本地输入统计没有成功启动。")}</p></div>`;
        elements.activityInputDays.innerHTML = "";
        return;
    }

    const today = inputStats.today || {};
    const recentDays = inputStats.recent_days || [];
    const statusText = inputStats.detail || "等待输入统计状态";

    const cards = [
        { label: "今日按键", value: today.keys_label || "0 次", detail: "键盘按下次数" },
        { label: "今日点击", value: today.clicks_label || "0 次", detail: "鼠标点击次数" },
        { label: "滚轮步数", value: today.scroll_steps_label || "0 格", detail: "滚轮滚动累计" },
        { label: "鼠标移动", value: today.move_pixels_label || "0 px", detail: `活跃 ${today.active_minutes_label || "0 分钟"}` },
        { label: "高峰时段", value: today.peak_hour_label || "暂无", detail: today.last_event_time_label ? `最近输入 ${today.last_event_time_label}` : statusText },
        { label: "近 7 天输入", value: inputStats.window_total_inputs_label || "0 次", detail: `累计活跃 ${inputStats.window_active_minutes_label || "0 分钟"}` },
    ];

    elements.activityInputStats.innerHTML = cards.map((item) => `
        <article class="activity-input-card">
            <span class="panel-label">${escapeHtml(item.label)}</span>
            <strong>${escapeHtml(item.value)}</strong>
            <p>${escapeHtml(item.detail)}</p>
        </article>
    `).join("");

    if (recentDays.length === 0) {
        elements.activityInputDays.innerHTML = "";
        return;
    }

    elements.activityInputDays.innerHTML = recentDays.map((item) => {
        const activeMinutes = Number(item.active_minutes || 0);
        const activeWidth = activeMinutes > 0 ? Math.max(6, Math.min(100, activeMinutes * 2)) : 0;
        return `
            <article class="activity-input-day">
                <div class="activity-input-day-head">
                    <strong>${escapeHtml(item.label || item.date || "--")}</strong>
                    <span>${escapeHtml(item.total_inputs_label || "0 次")}</span>
                </div>
                <div class="activity-input-day-bar">
                    <span class="activity-input-day-bar-fill" style="width:${activeWidth}%"></span>
                </div>
                <p>${escapeHtml(`按键 ${item.keys_label || "0 次"} / 点击 ${item.clicks_label || "0 次"} / 活跃 ${item.active_minutes_label || "0 分钟"}`)}</p>
            </article>
        `;
    }).join("");
}

function renderActivityPulse(pulse) {
    if (!elements.activityPulse) return;

    if (!pulse || !pulse.summary) {
        elements.activityPulse.innerHTML = "<div class='empty-state'><strong>等待活动脉搏</strong><p>开始使用插件后，这里会把活动、输入和隐私状态自动串成一个更清晰的当前视角。</p></div>";
        return;
    }

    const toneClass = pulse.tone ? ` activity-pulse-card--${escapeHtml(pulse.tone)}` : "";
    const meta = Array.isArray(pulse.meta) ? pulse.meta.filter(Boolean) : [];
    const metaHtml = meta.length
        ? `<div class="observation-tags">${meta.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>`
        : "";

    elements.activityPulse.innerHTML = `
        <article class="activity-pulse-card${toneClass}">
            <div class="activity-pulse-head">
                <span class="activity-pulse-badge">${escapeHtml(pulse.label || "工作脉搏")}</span>
                <strong>${escapeHtml(pulse.summary || "等待活动脉搏")}</strong>
            </div>
            <p class="activity-pulse-detail">${escapeHtml(pulse.detail || "")}</p>
            ${metaHtml}
        </article>
    `;
}

function renderActivitySessions(sessionData) {
    if (!elements.activitySessionSummary || !elements.activitySessions) return;

    const sessions = Array.isArray(sessionData?.filtered_items)
        ? sessionData.filtered_items
        : (Array.isArray(sessionData?.items) ? sessionData.items : []);
    const summaryPills = [
        renderOverviewPill("工作段", sessionData?.count_label || "0 段", "good"),
        renderOverviewPill("深度专注", sessionData?.focus_count_label || "0 段", "good"),
        renderOverviewPill("最长工作段", sessionData?.longest_duration || "0分钟", ""),
        renderOverviewPill("隐私模式", sessionData?.privacy_masked ? "窗口脱敏" : "原始标题", sessionData?.privacy_masked ? "muted" : ""),
    ];
    if (sessionData?.has_input_estimate) {
        summaryPills.splice(
            3,
            0,
            renderOverviewPill("有效总计", sessionData?.total_time || "0分钟", "good"),
            renderOverviewPill("扣除空闲", sessionData?.idle_trimmed_total_time || "0分钟", "muted"),
        );
    }
    elements.activitySessionSummary.innerHTML = summaryPills.join("");

    if (sessions.length === 0) {
        elements.activitySessions.innerHTML = "<div class='empty-state'><strong>当前筛选下没有工作段</strong><p>可以换个关键词、类型或来源，看看别的工作轨迹。</p></div>";
        return;
    }

    elements.activitySessions.innerHTML = sessions.map((item) => {
        const toneClass = item.tone ? ` activity-session-card--${escapeHtml(item.tone)}` : "";
        const tags = [
            item.top_window
                ? renderWindowCompanionTag(truncateLabel(item.top_window, 24), item.top_window, "activity")
                : "",
            item.top_app ? `<span class="tag">${escapeHtml(item.top_app)}</span>` : "",
            item.top_site,
            item.source_mix_label,
            item.switch_count_label,
            item.entry_count_label,
        ].filter(Boolean).map((tag) => (
            tag.startsWith("<") ? tag : `<span class="tag">${escapeHtml(tag)}</span>`
        ));
        const effectiveNote = item.effective_note
            ? `<p class="memory-meta">${escapeHtml(item.effective_note)}</p>`
            : "";
        return `
            <article class="activity-session-card${toneClass}">
                <div class="activity-session-head">
                    <div>
                        <h3 class="list-item-title">${escapeHtml(item.state_label || "工作段")}</h3>
                        <p class="memory-meta">${escapeHtml(`${item.range_label || "时间未知"} · ${item.dominant_label || "其他"} · 工作占比 ${item.work_ratio || "0%"}`)}</p>
                    </div>
                    <strong>${escapeHtml(item.duration || "0分钟")}</strong>
                </div>
                <div class="observation-tags">${tags.join("")}</div>
                <p class="memory-meta">${escapeHtml(item.summary || "")}</p>
                ${effectiveNote}
                <p class="memory-meta">${escapeHtml(item.continuation_label || "")}</p>
            </article>
        `;
    }).join("");
}

function renderActivitySurfaceTrail(surfaceData) {
    if (!elements.activitySurfaceSummary || !elements.activityAppTrail || !elements.activitySiteTrail) return;

    const summary = surfaceData?.summary || {};
    elements.activitySurfaceSummary.innerHTML = [
        renderOverviewPill("应用数", summary.app_count_label || "0 个应用", ""),
        renderOverviewPill("站点数", summary.site_count_label || "0 个站点", ""),
        renderOverviewPill("轨迹总计", summary.effective_time || "0分钟", "good"),
        renderOverviewPill("扣除空闲", summary.idle_trimmed_time || "0分钟", summary.estimate_enabled ? "muted" : ""),
    ].join("");

    const renderRows = (rows, emptyTitle, emptyBody) => {
        if (!Array.isArray(rows) || rows.length === 0) {
            return `<div class="empty-state"><strong>${escapeHtml(emptyTitle)}</strong><p>${escapeHtml(emptyBody)}</p></div>`;
        }
        return rows.map((item) => {
            const tags = [
                item.type,
                item.share,
                `${item.sessions || 0} 段`,
                item.domain || "",
            ].filter(Boolean);
            const note = item.idle_trimmed_time && item.idle_trimmed_time !== "0分0秒"
                ? `，其中扣除了约 ${item.idle_trimmed_time} 空闲`
                : "";
            return `
                <article class="activity-surface-card">
                    <div class="activity-surface-head">
                        <div>
                            <h3 class="list-item-title">${escapeHtml(item.label || "未命名")}</h3>
                            <p class="memory-meta">${escapeHtml(`${item.duration || "0分钟"} · 最近出现 ${item.last_seen || "未知"}${note}`)}</p>
                        </div>
                        <strong>${escapeHtml(item.duration || "0分钟")}</strong>
                    </div>
                    <div class="observation-tags">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
                </article>
            `;
        }).join("");
    };

    elements.activityAppTrail.innerHTML = renderRows(
        surfaceData?.apps,
        "今天还没有明显的应用轨迹",
        "继续积累活动记录后，这里会收束出主力应用。"
    );
    elements.activitySiteTrail.innerHTML = renderRows(
        surfaceData?.sites,
        "今天还没有明显的网站轨迹",
        "如果你主要在浏览器里工作，这里会逐渐显出主力站点。"
    );
}

function normalizeSearchText(value) {
    return String(value ?? "").trim().toLowerCase();
}

function getActivitySourceLabel(source) {
    const mapping = {
        screen_analysis: "识屏轨迹",
        background_tracker: "独立轨迹",
    };
    return mapping[String(source || "").trim()] || "其他来源";
}

function activityRecordMatchesFilters(activity, filters) {
    const bucket = String(filters?.bucket || "all");
    const source = String(filters?.source || "all");
    const search = normalizeSearchText(filters?.search);
    const activityBucket = String(activity?.bucket_key || "other");
    const activitySource = String(activity?.capture_source || "");
    if (bucket !== "all" && activityBucket !== bucket) return false;
    if (source !== "all" && activitySource !== source) return false;
    if (!search) return true;

    const haystacks = [
        activity?.type,
        activity?.scene,
        activity?.window,
        activity?.app_name,
        activity?.site_label,
        activity?.site_domain,
        activity?.page_title,
        activity?.resource_label,
        activity?.capture_source_label,
    ];
    return haystacks.some((item) => normalizeSearchText(item).includes(search));
}

function activitySessionMatchesFilters(session, filters) {
    const bucket = String(filters?.bucket || "all");
    const source = String(filters?.source || "all");
    const search = normalizeSearchText(filters?.search);
    const sessionBucket = String(session?.dominant_bucket || "other");
    const sessionSource = String(session?.primary_capture_source || "");
    if (bucket !== "all" && sessionBucket !== bucket) return false;
    if (source !== "all" && sessionSource !== source) return false;
    if (!search) return true;

    const haystacks = [
        session?.state_label,
        session?.dominant_label,
        session?.top_window,
        session?.top_app,
        session?.top_site,
        session?.summary,
        session?.primary_capture_source_label,
        session?.source_mix_label,
    ];
    return haystacks.some((item) => normalizeSearchText(item).includes(search));
}

function getFilteredActivityView(data) {
    const recentActivities = Array.isArray(data?.recent_activities) ? data.recent_activities : [];
    const sessionItems = Array.isArray(data?.sessions?.items) ? data.sessions.items : [];
    const filters = state.activityFilters || {};
    return {
        recentActivities,
        sessionItems,
        filteredRecentActivities: recentActivities.filter((item) => activityRecordMatchesFilters(item, filters)),
        filteredSessionItems: sessionItems.filter((item) => activitySessionMatchesFilters(item, filters)),
    };
}

function renderActivityMethodology(review, activityView) {
    if (!elements.activityMethodology) return;
    const cards = Array.isArray(review?.methodology) ? review.methodology : [];
    const filteredActivityCount = Number(activityView?.filteredRecentActivities?.length || 0);
    const filteredSessionCount = Number(activityView?.filteredSessionItems?.length || 0);
    const totalActivityCount = Number(activityView?.recentActivities?.length || 0);
    const totalSessionCount = Number(activityView?.sessionItems?.length || 0);

    const summaryCard = `
        <article class="helper-card">
            <strong>当前筛选结果</strong>
            <p>最近活动显示 ${filteredActivityCount} / ${totalActivityCount} 条，工作段显示 ${filteredSessionCount} / ${totalSessionCount} 段。筛选只影响回顾浏览，不会改动原始统计。</p>
        </article>
    `;

    const detailCards = cards.map((item) => `
        <article class="helper-card">
            <strong>${escapeHtml(item.title || "统计说明")}</strong>
            <p>${escapeHtml(item.detail || "")}</p>
        </article>
    `).join("");

    elements.activityMethodology.innerHTML = summaryCard + detailCards;
}

function getSettingMeta(key) {
    return state.settingsSchema[key] || {};
}

function loadSettingsModePreference() {
    try {
        return window.localStorage.getItem("screenCompanion.settings.showAdvanced") === "true";
    } catch (error) {
        return false;
    }
}

function persistSettingsModePreference() {
    try {
        window.localStorage.setItem(
            "screenCompanion.settings.showAdvanced",
            state.settingsShowAdvanced ? "true" : "false"
        );
    } catch (error) {
        // ignore storage failures
    }
}

function renderSettingsModeToggle() {
    if (!elements.settingsModeToggle) return;
    elements.settingsModeToggle.textContent = state.settingsShowAdvanced
        ? "切回基础设置"
        : "显示高级设置";
    elements.settingsModeToggle.classList.toggle("active", state.settingsShowAdvanced);
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

function getSettingsTemplatePresets() {
    return [
        {
            id: "game",
            label: "游戏陪伴",
            description: "更适合游戏、排队、结算、重开这类节奏快又会短暂切窗的场景。",
            preferredGroup: "runtime",
            updates: {
                enabled: true,
                use_companion_mode: true,
                check_interval: 180,
                trigger_probability: 45,
                screen_recognition_mode: true,
                enable_window_companion: true,
                window_companion_check_interval: 5,
                window_companion_reattach_grace_seconds: 300,
            },
        },
        {
            id: "work",
            label: "工作陪伴",
            description: "更偏向稳定观察和轻提醒，适合 IDE、文档、浏览器、多窗口工作流。",
            preferredGroup: "runtime",
            updates: {
                enabled: true,
                use_companion_mode: true,
                check_interval: 300,
                trigger_probability: 25,
                capture_active_window: true,
                screen_recognition_mode: false,
                enable_window_companion: false,
                enable_input_stats: true,
                enable_background_activity_tracking: true,
                enable_away_auto_pause: true,
            },
        },
        {
            id: "quiet",
            label: "低打扰",
            description: "尽量少打断你，只有比较值得说的时候才会出声。",
            preferredGroup: "runtime",
            updates: {
                enabled: true,
                use_companion_mode: true,
                check_interval: 480,
                trigger_probability: 12,
                enable_window_companion: false,
                enable_natural_language_screen_assist: false,
                enable_background_activity_tracking: false,
                enable_input_stats: false,
            },
        },
        {
            id: "journal",
            label: "轻量记录",
            description: "更偏向记录和回顾，减少主动打扰，保留日记和轻量轨迹。",
            preferredGroup: "diary",
            updates: {
                enabled: true,
                use_companion_mode: false,
                check_interval: 900,
                trigger_probability: 5,
                enable_window_companion: false,
                enable_diary: true,
                enable_learning: true,
                enable_background_activity_tracking: true,
                enable_input_stats: true,
                enable_away_auto_pause: false,
            },
        },
    ];
}

function findSettingsTemplatePreset(presetId) {
    return getSettingsTemplatePresets().find((item) => item.id === presetId) || null;
}

function applySettingsPayload(settings) {
    const nextSettings = settings || {};
    state.settingsSchema = nextSettings.schema || state.settingsSchema;
    state.settingsValues = nextSettings.values || state.settingsValues;
    state.settingsSnapshot = { ...(nextSettings.values || state.settingsValues) };
    state.settingsGroups = nextSettings.groups || state.settingsGroups;

    if (!state.settingsGroups.some((group) => group.id === state.activeSettingsGroup)) {
        state.activeSettingsGroup = state.settingsGroups[0]?.id || "";
    }

    renderSettingsModeToggle();
    renderSettingsGroups();
    renderSettingsForm();
}

function canQuickAddWindowCompanionTitle(title) {
    const text = String(title ?? "").trim();
    if (!text) return false;
    if (["未命名窗口", "当前窗口"].includes(text)) return false;
    if (text.startsWith("已脱敏")) return false;
    return true;
}

function collectWindowCompanionTargets() {
    return String(state.settingsValues.window_companion_targets || "")
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);
}

function isWindowCompanionTargetConfigured(title) {
    const target = String(title ?? "").trim().toLowerCase();
    if (!target) return false;
    return collectWindowCompanionTargets().some(
        (item) => item.split("|", 1)[0].trim().toLowerCase() === target
    );
}

function buildWindowCompanionTargetUpdate(title) {
    const target = String(title ?? "").trim();
    if (!target) return null;

    const current = collectWindowCompanionTargets();
    const exists = current.some(
        (item) => item.split("|", 1)[0].trim().toLowerCase() === target.toLowerCase()
    );
    if (!exists) current.push(target);

    return {
        target,
        exists,
        updates: {
            enable_window_companion: true,
            window_companion_targets: current.join("\n"),
        },
    };
}

function appendWindowCompanionTarget(title) {
    const payload = buildWindowCompanionTargetUpdate(title);
    if (!payload) return null;
    setSettingsValues(payload.updates);
    return payload;
}

function renderWindowCompanionTag(label, title, feedbackScope = "activity") {
    const displayLabel = String(label ?? "").trim();
    const target = String(title ?? "").trim();
    if (!displayLabel) return "";
    if (!canQuickAddWindowCompanionTitle(target)) {
        return `<span class="tag">${escapeHtml(displayLabel)}</span>`;
    }

    const configured = isWindowCompanionTargetConfigured(target);
    const buttonTitle = configured
        ? "这个窗口已经在窗口陪伴目标里，点一下可确保窗口陪伴已开启。"
        : "将这个窗口加入窗口陪伴目标并立即生效。";
    return `
        <button
            type="button"
            class="tag tag-button${configured ? " tag-button--active" : ""}"
            data-window-companion-title="${escapeHtml(target)}"
            data-window-companion-feedback="${escapeHtml(feedbackScope)}"
            title="${escapeHtml(buttonTitle)}"
        >
            <span>${escapeHtml(displayLabel)}</span>
            <span class="tag-action-mark">${configured ? "已陪伴" : "+陪伴"}</span>
        </button>
    `;
}

function setWindowCompanionQuickAddFeedback(scope, message, tone = "success") {
    if (!message) return;

    if (scope === "observations" && elements.observationMeta) {
        elements.observationMeta.textContent = message;
        return;
    }
    if (scope === "activity" && elements.activityFilterSummary) {
        elements.activityFilterSummary.textContent = message;
        return;
    }
    if (scope === "diary" && elements.diarySummary) {
        elements.diarySummary.textContent = message;
        return;
    }

    setFeedbackMessage(elements.settingsFeedback, message, tone);
}

async function quickAddWindowCompanionTarget(title, feedbackScope = "activity") {
    const payload = buildWindowCompanionTargetUpdate(title);
    if (!payload) {
        throw new Error("窗口标题不可用");
    }

    const alreadyEnabled = payload.exists && Boolean(state.settingsValues.enable_window_companion);
    if (alreadyEnabled) {
        return { ...payload, alreadyEnabled: true };
    }

    const data = await apiFetch("/api/settings", {
        method: "POST",
        body: JSON.stringify({ updates: payload.updates }),
    });
    applySettingsPayload(data.settings || {});
    await loadRuntime();
    await loadHealth();
    return { ...payload, alreadyEnabled: false };
}

function switchSettingsGroup(groupId) {
    state.activeSettingsGroup = groupId;
    renderSettingsGroups();
    renderSettingsForm();
}

function openSettingsGroup(groupId) {
    switchSection("settings");
    history.replaceState(null, "", "#settings");
    switchSettingsGroup(groupId);
}

function shouldShowSettingField(fieldKey, currentValues) {
    const meta = getSettingMeta(fieldKey);
    if (meta.advanced && !state.settingsShowAdvanced) {
        return false;
    }
    const condition = meta.condition || {};
    return Object.entries(condition).every(([key, expected]) => currentValues[key] === expected);
}

function getVisibleFieldsForGroup(group, currentValues, query = "") {
    const normalizedQuery = String(query || "").trim().toLowerCase();
    return (group?.fields || []).filter((fieldKey) => {
        if (!shouldShowSettingField(fieldKey, currentValues)) {
            return false;
        }
        if (!normalizedQuery) {
            return true;
        }
        const meta = getSettingMeta(fieldKey);
        const haystacks = [
            fieldKey,
            meta.description || "",
            meta.hint || "",
        ];
        return haystacks.some((item) => String(item).toLowerCase().includes(normalizedQuery));
    });
}

function getVisibleSettingsGroups() {
    const currentValues = { ...state.settingsValues };
    const query = state.settingsSearch.trim().toLowerCase();
    return state.settingsGroups
        .map((group) => ({
            ...group,
            fields: getVisibleFieldsForGroup(group, currentValues, query),
        }))
        .filter((group) => group.fields.length > 0);
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

    if (meta.type === "password") {
        input.autocomplete = "new-password";
        if (meta.sensitive && meta.configured) {
            input.placeholder = "Leave blank to keep current value";
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
            title: "工作脉搏",
            body: runtime.activity_pulse?.summary
                ? `${runtime.activity_pulse.summary} ${runtime.activity_pulse.detail || ""}`.trim()
                : "活动页会把当前活动、输入在场感和隐私状态整合成一个更完整的工作脉搏视角。",
            actions: [],
        },
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
        {
            title: "\u672c\u5730\u8f93\u5165\u7edf\u8ba1",
            body: runtime.input_stats?.enabled
                ? `${runtime.input_stats?.detail || "\u672c\u5730\u8f93\u5165\u7edf\u8ba1\u5df2\u5f00\u542f\u3002"}${runtime.input_stats?.presence_label ? ` \u5f53\u524d${runtime.input_stats.presence_label}\u3002` : ""}${runtime.input_stats?.today?.keys_label ? ` \u4eca\u65e5\u6309\u952e ${runtime.input_stats.today.keys_label}\uff0c\u70b9\u51fb ${runtime.input_stats.today.clicks_label || "0 \u6b21"}\u3002` : ""}`
                : "\u9ed8\u8ba4\u5173\u95ed\u3002\u5f00\u542f\u540e\u4f1a\u8bb0\u5f55\u952e\u76d8\u548c\u9f20\u6807\u8f93\u5165\uff0c\u7528\u6765\u751f\u6210\u8f7b\u91cf\u7684\u8f93\u5165\u56de\u987e\u3002",
            actions: [{ label: "\u524d\u5f80\u672c\u5730\u7edf\u8ba1\u8bbe\u7f6e", action: "open-analytics-group" }],
        },
        {
            title: "\u72ec\u7acb\u6d3b\u52a8\u8f68\u8ff9\u91c7\u96c6",
            body: runtime.background_activity_tracking?.enabled
                ? runtime.background_activity_tracking?.active
                    ? `\u5df2\u542f\u7528\uff0c\u5f53\u524d\u6b63\u5728\u4ee5 ${runtime.background_activity_tracking.interval || 15} \u79d2\u7684\u8282\u594f\u91c7\u6837\u6d3b\u52a8\u7a97\u53e3\u3002`
                    : "\u5df2\u542f\u7528\uff0c\u4f46\u76ee\u524d\u8bc6\u5c4f\u6216\u7a97\u53e3\u966a\u4f34\u6b63\u5728\u8fd0\u884c\uff0c\u6240\u4ee5\u72ec\u7acb\u8f68\u8ff9\u6682\u65f6\u8ba9\u4f4d\u7ed9\u66f4\u4e30\u5bcc\u7684\u8bc6\u5c4f\u8f68\u8ff9\u3002"
                : "\u9ed8\u8ba4\u5173\u95ed\u3002\u6253\u5f00\u540e\uff0c\u5373\u4f7f\u6ca1\u6709\u542f\u52a8\u81ea\u52a8\u89c2\u5bdf\uff0c\u4e5f\u4f1a\u6301\u7eed\u8bb0\u5f55\u5e94\u7528 / \u7ad9\u70b9 / \u9875\u9762\u8f68\u8ff9\u3002",
            actions: [{ label: "\u8c03\u6574\u8f68\u8ff9\u91c7\u96c6", action: "open-analytics-group" }],
        },
        {
            title: "离开自动挂起",
            body: runtime.away_pause?.enabled
                ? runtime.away_pause?.active
                    ? `${runtime.away_pause.detail || "当前已自动挂起自动观察。"}${runtime.away_pause.scene_label ? ` 离开前场景：${runtime.away_pause.scene_label}。` : ""}`
                    : "已启用。非观影场景下，如果较长时间没有键鼠输入，会先暂停自动观察；检测到你回来继续操作后再自动恢复。"
                : "默认关闭。适合需要长时间挂着自动观察、但又希望用户离开工位时先退到旁边的场景。",
            actions: [{ label: "调整挂起设置", action: "open-analytics-group" }],
        },
        {
            title: "活动隐私",
            body: runtime.mask_activity_window_titles
                ? "已开启窗口标题脱敏。活动统计、主力窗口和工作轨迹会统一隐藏敏感标题，更适合日常一直挂着用。"
                : "当前会显示原始窗口标题。如果你更在意隐私，可以在本地统计设置里开启统一脱敏。",
            actions: [{ label: "调整统计设置", action: "open-analytics-group" }],
        },
    ];

    const activityRuleSummary = runtime.activity_recognition_rules || {};
    const activityRuleCount = Number(activityRuleSummary.total_rules || 0);
    const invalidRuleLines = Number(activityRuleSummary.invalid_lines || 0);
    if (activityRuleCount > 0 || invalidRuleLines > 0) {
        const baseBody = activityRuleCount > 0
            ? `已启用 ${activityRuleCount} 条自定义规则（应用 ${Number(activityRuleSummary.app_rules || 0)} 条，站点 ${Number(activityRuleSummary.site_rules || 0)} 条）。改完规则后，旧活动也会按新规则重新归类。`
            : "当前还没有生效的自定义规则。";
        const detailBody = invalidRuleLines > 0
            ? `${baseBody} 另有 ${invalidRuleLines} 行格式未生效，请检查是否写成 app|关键词|显示名 或 site|关键词|显示名。`
            : baseBody;
        insights.push({
            title: "轨迹识别规则",
            body: detailBody,
            actions: [{ label: "调整统计设置", action: "open-analytics-group" }],
        });
    }

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

    const recentAnalyses = Array.isArray(runtime.recent_screen_analyses) ? runtime.recent_screen_analyses : [];
    recentAnalyses.slice(0, 3).forEach((trace) => {
        const card = document.createElement("article");
        card.className = "helper-card";
        const meta = [
            trace.trigger_reason ? `触发：${trace.trigger_reason}` : "",
            trace.analysis_material_kind ? `识别素材：${trace.analysis_material_kind}` : "",
            trace.sampling_strategy ? `采样：${trace.sampling_strategy}` : "",
            trace.scene ? `场景：${trace.scene}` : "",
            trace.status ? `状态：${trace.status}` : "",
        ].filter(Boolean);
        const summary = [
            trace.recognition_summary ? `识别摘要：${trace.recognition_summary}` : "",
            trace.reply_preview ? `最终回复：${trace.reply_preview}` : "",
            trace.stored_as_observation ? "已写入观察" : "未写入观察",
            trace.stored_in_diary ? "已进入日记候选" : "未进入日记候选",
        ].filter(Boolean);
        card.innerHTML = `
            <strong>最近一次识屏解释</strong>
            <p>${escapeHtml(meta.join(" / ") || "暂无识屏解释信息。")}</p>
            <p>${escapeHtml(summary.join(" | "))}</p>
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
    if (elements.healthChecks) elements.healthChecks.innerHTML = "";
    if (elements.healthWarnings) elements.healthWarnings.innerHTML = "";
    if (!state.health) {
        elements.healthMeta.textContent = "尚未完成服务自检。";
        elements.healthGrid.appendChild(cloneEmptyState());
        return;
    }

    const health = state.health;
    const warningCount = Number(health.warning_count || 0);
    const errorCount = Number(health.error_count || 0);
    const issueSummary = errorCount > 0
        ? `发现 ${errorCount} 个高优先问题`
        : warningCount > 0
            ? `发现 ${warningCount} 个需要关注的提醒`
            : "当前自检未发现明显异常";
    elements.healthMeta.textContent = `最近检查 ${formatDateTime(health.checked_at)} | 服务: ${health.service || "unknown"} | ${issueSummary}`;
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

    const statusOrder = { error: 0, warn: 1, ok: 2 };
    const checks = (Array.isArray(health.checks) ? health.checks : []).slice().sort((left, right) => {
        const leftRank = statusOrder[String(left?.status || "ok")] ?? 9;
        const rightRank = statusOrder[String(right?.status || "ok")] ?? 9;
        return leftRank - rightRank;
    });
    if (elements.healthChecks) {
        if (!checks.length) {
            elements.healthChecks.innerHTML = "<div class='empty-state'><strong>暂无详细检查项</strong><p>刷新后会重新收集静态资源、目录、轨迹和输入状态。</p></div>";
        } else {
            elements.healthChecks.innerHTML = checks.map((item) => `
                <article class="health-check-card health-check-card--${escapeHtml(item.status || "ok")}">
                    <div class="health-check-head">
                        <strong>${escapeHtml(item.title || "检查项")}</strong>
                        <span class="settings-badge">${escapeHtml(item.status_label || item.status || "ok")}</span>
                    </div>
                    <p>${escapeHtml(item.detail || "")}</p>
                </article>
            `).join("");
        }
    }

    const recommendations = Array.isArray(health.recommendations) ? health.recommendations : [];
    if (elements.healthWarnings) {
        if (!recommendations.length) {
            elements.healthWarnings.innerHTML = "";
        } else {
            elements.healthWarnings.innerHTML = recommendations.map((item) => `
                <article class="helper-card">
                    <strong>${escapeHtml(item.title || "建议")}</strong>
                    <p>${escapeHtml(item.body || "")}</p>
                </article>
            `).join("");
        }
    }
}

function renderSettingsHelper(activeGroup, currentValues) {
    elements.settingsHelper.innerHTML = "";
    if (!activeGroup) return;

    const cards = [];
    const templatePresets = getSettingsTemplatePresets();

    if (["persona", "runtime", "diary"].includes(activeGroup.id)) {
        cards.push({
            title: "常用场景模板",
            body: "这些模板只会改动陪伴节奏、识屏方式、记录强度这类常用开关，不会覆盖你已经填好的窗口目标、API Key、提示词和密码。",
            actions: templatePresets.map((preset) => ({
                label: preset.label,
                action: `apply-template::${preset.id}`,
            })),
        });
    }

    if (activeGroup.id === "vision") {
        cards.push({
            title: currentValues.screen_recognition_mode
                ? "\u5f53\u524d\u662f\u5f55\u5c4f\u8bc6\u5c4f"
                : currentValues.use_shared_screenshot_dir
                    ? "Docker / \u5171\u4eab\u622a\u56fe\u6a21\u5f0f"
                    : "\u5f53\u524d\u662f\u5b9e\u65f6\u622a\u56fe",
            body: currentValues.screen_recognition_mode
                ? "\u63d2\u4ef6\u4f1a\u5728\u672c\u5730\u7528 ffmpeg \u5f55\u4e00\u5c0f\u6bb5 mp4\uff0c\u518d\u628a\u8fd9\u6bb5\u64cd\u4f5c\u8fc7\u7a0b\u62ff\u53bb\u8bc6\u522b\u3002\u9002\u5408\u6e38\u620f\u3001\u64cd\u4f5c\u901f\u5ea6\u5feb\u3001\u5355\u5f20\u622a\u56fe\u4fe1\u606f\u4e0d\u591f\u7684\u573a\u666f\u3002"
                : currentValues.use_shared_screenshot_dir
                    ? `\u5f53\u524d\u4f18\u5148\u8bfb\u53d6\u5171\u4eab\u76ee\u5f55\u91cc\u7684\u622a\u56fe\u3002${currentValues.shared_screenshot_dir ? `\u76ee\u5f55\uff1a${currentValues.shared_screenshot_dir}` : "\u8fd8\u6ca1\u586b\u5171\u4eab\u76ee\u5f55\u8def\u5f84\uff0c\u5efa\u8bae\u8865\u4e0a\u3002"}`
                    : "\u666e\u901a Windows \u684c\u9762\u73af\u5883\u63a8\u8350\u4fdd\u6301\u8fd9\u4e2a\u6a21\u5f0f\uff0c\u4e0d\u9700\u8981 ffmpeg\uff0c\u4e5f\u66f4\u4e0d\u5bb9\u6613\u8bfb\u5230\u65e7\u622a\u56fe\u3002",
            actions: currentValues.screen_recognition_mode
                ? []
                : currentValues.use_shared_screenshot_dir
                    ? [{ label: "\u6539\u56de\u5b9e\u65f6\u622a\u56fe\u63a8\u8350\u503c", action: "vision-live" }]
                    : [{ label: "\u5207\u5230 Docker \u6a21\u5f0f", action: "vision-docker" }],
        });
        cards.push({
            title: currentValues.use_external_vision ? "\u5916\u90e8\u89c6\u89c9 API + AstrBot \u4e24\u6bb5\u94fe\u8def" : "\u76f4\u63a5 AstrBot \u591a\u6a21\u6001",
            body: currentValues.use_external_vision
                ? "\u4f1a\u5148\u628a\u56fe\u50cf\u6216\u5f55\u5c4f\u4ea4\u7ed9\u5916\u90e8\u89c6\u89c9 API \u505a\u8bc6\u522b\uff0c\u518d\u7531 AstrBot \u751f\u6210\u6700\u7ec8\u56de\u590d\u3002\u4e00\u822c\u66f4\u7a33\uff0c\u4e5f\u66f4\u9002\u5408\u8bc6\u5c4f\u573a\u666f\u3002"
                : "\u4e0d\u4f1a\u5148\u8d70\u5916\u90e8\u89c6\u89c9 API\uff0c\u800c\u662f\u76f4\u63a5\u628a\u622a\u56fe\u6216\u5f55\u5c4f\u4f5c\u4e3a\u591a\u6a21\u6001\u8f93\u5165\u53d1\u7ed9 AstrBot \u5f53\u524d provider\u3002\u53ea\u6709\u5f53\u524d provider \u771f\u6b63\u652f\u6301\u5bf9\u5e94\u56fe\u50cf/\u89c6\u9891\u8f93\u5165\u65f6\u624d\u9002\u5408\u8fd9\u4e48\u914d\u3002",
            actions: [],
        });
        cards.push({
            title: "\u8bc6\u5c4f\u8c03\u53c2\u5efa\u8bae",
            body: "\u60f3\u8981\u770b\u5f97\u66f4\u7a33\uff0c\u4f18\u5148\u5148\u51b3\u5b9a\u201c\u622a\u56fe or \u5f55\u5c4f\u201d\uff0c\u518d\u51b3\u5b9a\u201c\u5916\u90e8\u89c6\u89c9 API or \u76f4\u63a5 provider\u201d\u3002\u60f3\u8981\u7701 token\uff0c\u5c31\u8ba9 image_prompt \u5c3d\u91cf\u53ea\u8981\u6c42\u8f93\u51fa\u4efb\u52a1\u3001\u9636\u6bb5\u3001\u5f02\u5e38\u7ebf\u7d22\u548c\u4e00\u4e2a\u5efa\u8bae\u70b9\u3002",
            actions: [],
        });
    }

    if (activeGroup.id === "persona") {
        cards.push({
            title: currentValues.enable_natural_language_screen_assist ? "\u81ea\u7136\u8bed\u8a00\u8bc6\u5c4f\u6c42\u52a9\u5df2\u5f00\u542f" : "\u81ea\u7136\u8bed\u8a00\u8bc6\u5c4f\u6c42\u52a9\u5df2\u5173\u95ed",
            body: currentValues.enable_natural_language_screen_assist
                ? "\u73b0\u5728\u53ea\u8981\u7ba1\u7406\u5458\u5728\u81ea\u7136\u5bf9\u8bdd\u91cc\u660e\u786e\u8868\u793a\u201c\u5e2e\u6211\u770b\u770b\u201d\u8fd9\u7c7b\u6c42\u52a9\uff0cBot \u5c31\u4f1a\u4e3b\u52a8\u8bc6\u5c4f\u540e\u518d\u56de\u7b54\u3002"
                : "\u9ed8\u8ba4\u5173\u95ed\u66f4\u7a33\uff0c\u80fd\u51cf\u5c11\u666e\u901a\u804a\u5929\u88ab\u8bef\u5224\u4e3a\u8bc6\u5c4f\u6c42\u52a9\u3002\u53ea\u6709\u4f60\u786e\u5b9e\u60f3\u5728\u5bf9\u8bdd\u91cc\u76f4\u63a5\u53eb\u5b83\u5e2e\u4f60\u770b\u5c4f\u65f6\u518d\u6253\u5f00\u3002",
            actions: [
                { label: currentValues.enable_natural_language_screen_assist ? "\u5173\u95ed\u5b83" : "\u5f00\u542f\u5b83", action: "toggle-screen-assist" },
                { label: "\u67e5\u770b\u8bc6\u5c4f\u8bbe\u7f6e", action: "open-vision-group" },
            ],
        });
        cards.push({
            title: "\u4eba\u683c\u4e0e\u8bf4\u8bdd\u98ce\u683c",
            body: "\u5982\u679c\u4f60\u53ea\u60f3\u8c03\u8bed\u6c14\uff0c\u4f18\u5148\u6539 system_prompt \u548c user_preferences\uff1b\u5982\u679c\u4f60\u60f3\u8c03\u884c\u4e3a\u8fb9\u754c\uff0c\u518d\u53bb\u6539\u81ea\u7136\u8bed\u8a00\u8bc6\u5c4f\u3001\u5f00\u59cb/\u7ed3\u675f\u6587\u6848\u8fd9\u4e9b\u5f00\u5173\u3002",
            actions: [],
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
            title: "WebUI \u914d\u7f6e\u5efa\u8bae",
            body: "host\u3001port\u3001\u5bc6\u7801\u548c\u5916\u90e8 API \u6743\u9650\u90fd\u5c5e\u4e8e\u201c\u6539\u9519\u4e86\u5c31\u53ef\u80fd\u8fde\u4e0d\u4e0a\u201d\u7684\u8bbe\u7f6e\u3002\u5982\u679c\u4f60\u53ea\u5728\u672c\u673a\u7528\uff0c\u4f18\u5148\u4fdd\u6301 127.0.0.1 / \u5f00\u542f\u5bc6\u7801 / \u5173\u95ed\u5916\u90e8 API \u8fd9\u5957\u66f4\u7a33\u3002",
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

    const modeLabel = state.settingsShowAdvanced ? "高级模式" : "基础模式";
    elements.settingsSummary.textContent = visibleGroups.length
        ? `${modeLabel} · 当前可见 ${visibleGroups.length} 个配置分组，待保存 ${dirtyCount} 项。`
        : `${modeLabel} · 没有匹配到配置项。`;

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
        updateSettingsActionButtons(null);
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
        updateSettingsActionButtons(activeGroup);
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

    updateSettingsActionButtons(activeGroup);
}

function getActiveSettingsGroup() {
    const visibleGroups = getVisibleSettingsGroups();
    return visibleGroups.find((group) => group.id === state.activeSettingsGroup) || null;
}

function updateSettingsActionButtons(activeGroup = null) {
    const group = activeGroup || getActiveSettingsGroup();
    const groupFields = Array.isArray(group?.fields) ? group.fields : [];
    const dirtyFields = groupFields.filter((fieldKey) => isSettingDirty(fieldKey));
    const hasDirtyFields = dirtyFields.length > 0;

    if (elements.saveSettingsButton) {
        elements.saveSettingsButton.disabled = !hasDirtyFields;
        elements.saveSettingsButton.textContent = hasDirtyFields
            ? `保存配置 (${dirtyFields.length})`
            : "保存配置";
    }
    if (elements.resetSettingsButton) {
        elements.resetSettingsButton.disabled = !hasDirtyFields;
    }
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
        const match = line.match(
            /^###\s+(\d{2}:\d{2}(?::\d{2})?(?:\s*-\s*\d{2}:\d{2}(?::\d{2})?)?)\s*-\s*(.+)$/
        );
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
                        ${renderWindowCompanionTag(entry.windowTitle, entry.windowTitle, "diary")}
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

    const lines = text.replace(/\r\n/g, "\n").split("\n");
    const buffers = {
        overview: [],
        observation: [],
        reflection: [],
    };
    let currentSection = "";

    for (const rawLine of lines) {
        const line = rawLine.trim();
        if (/^##\s*今日概览\s*$/.test(line)) {
            currentSection = "overview";
            continue;
        }
        if (/^##\s*今日观察\s*$/.test(line)) {
            currentSection = "observation";
            continue;
        }
        if (/^##\s*今日感想\s*$/.test(line)) {
            currentSection = "reflection";
            continue;
        }
        if (/^##(?!#)\s+/.test(line)) {
            currentSection = "";
            continue;
        }
        if (currentSection && Object.prototype.hasOwnProperty.call(buffers, currentSection)) {
            buffers[currentSection].push(rawLine);
        }
    }

    const cleanedFull = text
        .replace(/^#\s*.+日记\s*$/m, "")
        .replace(/^##\s*\d{4}年\d{1,2}月\d{1,2}日(?:\s+\S+)?\s*$/m, "")
        .replace(/^\*\*天气\*\*:\s*.*$/m, "")
        .replace(/^天气[:：]\s*.*$/m, "")
        .replace(/^##\s*今日概览\s*$/m, "")
        .replace(/^##\s*今日观察\s*$/m, "")
        .replace(/^##\s*今日感想\s*$/m, "")
        .replace(/^[—-]{1,2}\s*\d{4}年\d{1,2}月\d{1,2}日.*$/m, "")
        .trim();

    sections.observation = buffers.observation.join("\n").trim();
    sections.reflection = buffers.reflection.join("\n").trim();
    sections.full = cleanedFull || text.trim();

    if (!sections.reflection) {
        sections.reflection = sections.full;
    }

    return sections;
}

function pruneDiarySelections() {
    const availableDates = new Set((state.diaryDates || []).map((entry) => entry.date).filter(Boolean));
    Array.from(state.selectedDiaryDates).forEach((date) => {
        if (!availableDates.has(date)) state.selectedDiaryDates.delete(date);
    });
}

function pickDiaryFallbackDate(removedDates = []) {
    const removed = new Set((removedDates || []).filter(Boolean));
    const remainingDates = (state.diaryDates || [])
        .map((entry) => entry.date)
        .filter((date) => date && !removed.has(date));
    if (state.selectedDiaryDate && !removed.has(state.selectedDiaryDate) && remainingDates.includes(state.selectedDiaryDate)) {
        return state.selectedDiaryDate;
    }
    return remainingDates[0] || new Date().toISOString().slice(0, 10);
}

function buildDiaryDeleteConfirmMessage(dates) {
    const validDates = (dates || []).filter(Boolean);
    if (!validDates.length) return "";
    if (validDates.length === 1) {
        return `确定删除 ${formatDateLabel(validDates[0])} 的日记吗？\n对应正文和概览摘要会一起删除，且无法恢复。`;
    }
    const preview = validDates.slice(0, 3).map((date) => formatDateLabel(date)).join("、");
    const suffix = validDates.length > 3 ? " 等" : "";
    return `确定批量删除这 ${validDates.length} 篇日记吗？\n${preview}${suffix}\n对应正文和概览摘要会一起删除，且无法恢复。`;
}

function syncDiarySelectionUi() {
    const total = state.diaryDates.length;
    const selectedCount = state.selectedDiaryDates.size;
    const hasDiaries = total > 0;
    const allSelected = hasDiaries && selectedCount === total;

    elements.selectAllDiaries.checked = allSelected;
    elements.selectAllDiaries.indeterminate = selectedCount > 0 && selectedCount < total;
    elements.selectAllDiaries.disabled = !hasDiaries;
    elements.clearDiarySelectionsButton.disabled = selectedCount === 0;
    elements.deleteSelectedDiariesButton.disabled = selectedCount === 0;

    const currentDiaryExists = state.diaryDates.some((entry) => entry.date === state.selectedDiaryDate);
    elements.deleteCurrentDiaryButton.disabled = !currentDiaryExists;

    if (!hasDiaries) {
        elements.diarySelectionMeta.textContent = "还没有可删除的日记。";
        return;
    }
    if (!selectedCount) {
        elements.diarySelectionMeta.textContent = "还没有选择要删除的日记。";
        return;
    }
    elements.diarySelectionMeta.textContent = `已选择 ${selectedCount} / ${total} 篇日记。`;
}

function renderDiaryList() {
    elements.diaryList.innerHTML = "";
    pruneDiarySelections();
    syncDiarySelectionUi();
    if (state.diaryDates.length === 0) {
        elements.diaryList.appendChild(cloneEmptyState());
        elements.diarySummary.textContent = "还没有生成任何日记。";
        return;
    }

    elements.diarySummary.textContent = `共 ${state.diaryDates.length} 篇日记，默认打开最近日期。`;
    state.diaryDates.forEach((entry) => {
        const card = document.createElement("article");
        card.className = "diary-list-item";
        if (entry.date === state.selectedDiaryDate) card.classList.add("active");
        const selected = state.selectedDiaryDates.has(entry.date);
        card.innerHTML = `
            <div class="diary-list-item-top">
                <label class="observation-select diary-select">
                    <input type="checkbox" ${selected ? "checked" : ""}>
                    <span>选择</span>
                </label>
                <button class="danger-button diary-delete-button" type="button">删除</button>
            </div>
            <button class="list-item-button diary-open-button ${entry.date === state.selectedDiaryDate ? "active" : ""}" type="button">
                <p class="list-item-title">${escapeHtml(formatDateLabel(entry.date))}</p>
                <p class="list-item-meta">文件名 ${escapeHtml(entry.filename)}</p>
            </button>
        `;
        const checkbox = card.querySelector('input[type="checkbox"]');
        checkbox.addEventListener("change", () => {
            if (checkbox.checked) state.selectedDiaryDates.add(entry.date);
            else state.selectedDiaryDates.delete(entry.date);
            syncDiarySelectionUi();
        });

        const openButton = card.querySelector(".diary-open-button");
        openButton.addEventListener("click", () => {
            elements.diaryDateInput.value = entry.date;
            loadDiaryDetail(entry.date);
        });

        const deleteButton = card.querySelector(".diary-delete-button");
        deleteButton.addEventListener("click", async () => {
            const confirmed = confirm(buildDiaryDeleteConfirmMessage([entry.date]));
            if (!confirmed) return;
            deleteButton.disabled = true;
            try {
                await deleteDiary(entry.date);
                elements.diarySelectionMeta.textContent = `已删除 ${formatDateLabel(entry.date)} 的日记。`;
            } catch (error) {
                deleteButton.disabled = false;
                elements.diarySelectionMeta.textContent = `删除失败: ${error.message}`;
            }
        });

        elements.diaryList.appendChild(card);
    });
}

function buildDiarySummaryText(summary) {
    if (!summary || typeof summary !== "object") {
        return state.diaryDates.length ? `共 ${state.diaryDates.length} 篇日记，默认打开最近日期。` : "还没有生成任何日记。";
    }

    const mainWindowCount = Array.isArray(summary.main_windows) ? summary.main_windows.length : 0;
    const repeatedFocusCount = Array.isArray(summary.repeated_focuses) ? summary.repeated_focuses.length : 0;
    const suggestionCount = Array.isArray(summary.suggestion_items) ? summary.suggestion_items.length : 0;
    const parts = [`共 ${state.diaryDates.length} 篇日记`];
    if (mainWindowCount) parts.push(`主要窗口 ${mainWindowCount} 项`);
    if (repeatedFocusCount) parts.push(`重复卡点 ${repeatedFocusCount} 项`);
    if (suggestionCount) parts.push(`建议 ${suggestionCount} 项`);
    return parts.join("，");
}

function renderDiaryStructuredSummary(summary) {
    if (!summary || typeof summary !== "object") return "";

    const blocks = [];
    const mainWindows = Array.isArray(summary.main_windows) ? summary.main_windows : [];
    if (mainWindows.length) {
        blocks.push(`
            <div class="diary-overview-item">
                <strong>今日主要窗口</strong>
                <p>${escapeHtml(mainWindows.slice(0, 3).map((item) => `${item.window_title || "当前窗口"}（约 ${item.duration_minutes || 0} 分钟）`).join("；"))}</p>
            </div>
        `);
    }

    const longestTask = summary.longest_task && typeof summary.longest_task === "object" ? summary.longest_task : null;
    if (longestTask?.window_title) {
        blocks.push(`
            <div class="diary-overview-item">
                <strong>最长停留任务</strong>
                <p>${escapeHtml(`${longestTask.window_title}（约 ${longestTask.duration_minutes || 0} 分钟${longestTask.focus ? `，主要在：${longestTask.focus}` : ""}）`)}</p>
            </div>
        `);
    }

    const repeatedFocuses = Array.isArray(summary.repeated_focuses) ? summary.repeated_focuses : [];
    if (repeatedFocuses.length) {
        blocks.push(`
            <div class="diary-overview-item">
                <strong>重复卡点</strong>
                <p>${escapeHtml(repeatedFocuses.slice(0, 3).map((item) => `${item.window_title || "当前窗口"}：${item.note || "重复出现"}`).join("；"))}</p>
            </div>
        `);
    }

    const suggestionItems = Array.isArray(summary.suggestion_items) ? summary.suggestion_items : [];
    if (suggestionItems.length) {
        blocks.push(`
            <div class="diary-overview-item">
                <strong>建议事项</strong>
                <ul>${suggestionItems.slice(0, 3).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
            </div>
        `);
    }

    if (!blocks.length) return "";
    return `
        <section class="helper-card diary-overview-card">
            <div class="diary-overview-head"><strong>今日概览</strong></div>
            <div class="diary-overview-grid">${blocks.join("")}</div>
        </section>
    `;
}

function buildObservationExplainability(observation) {
    const detailLines = [
        observation.trigger_reason ? `触发原因：${observation.trigger_reason}` : "",
        observation.material_kind ? `原始素材：${observation.material_kind}` : "",
        observation.analysis_material_kind ? `识别素材：${observation.analysis_material_kind}` : "",
        observation.sampling_strategy ? `采样策略：${observation.sampling_strategy}` : "",
        observation.frame_count ? `采样帧数：${observation.frame_count}` : "",
        Array.isArray(observation.frame_labels) && observation.frame_labels.length ? `关键帧：${observation.frame_labels.join("、")}` : "",
        typeof observation.used_full_video === "boolean" && observation.material_kind === "video"
            ? `全量视频复判：${observation.used_full_video ? "是" : "否"}`
            : "",
        observation.recognition_summary ? `识别摘要：${observation.recognition_summary}` : "",
        observation.reply_preview ? `最终回复：${observation.reply_preview}` : "",
    ].filter(Boolean);
    if (!detailLines.length) return "";
    return `<div class="observation-explainability">${detailLines.map((line) => `<p class="panel-subtle">${escapeHtml(line)}</p>`).join("")}</div>`;
}

function renderDiaryDetail(date, content, structuredSummary = {}) {
    state.selectedDiaryDate = date;
    elements.diaryDateInput.value = date || "";
    renderDiaryList();
    syncDiarySelectionUi();
    elements.diaryTitle.textContent = date ? `${formatDateLabel(date)} 的日记` : "日记内容";
    elements.diaryMeta.textContent = content ? "已加载完整内容" : "这一天还没有写入内容";
    elements.diarySummary.textContent = buildDiarySummaryText(structuredSummary);

    if (!content) {
        state.diaryObservationsExpanded = false;
        elements.toggleDiaryObservations.textContent = "展开";
        elements.toggleDiaryObservations.disabled = true;
        const empty = cloneEmptyState();
        empty.querySelector("strong").textContent = "这一天还没有日记";
        empty.querySelector("p").textContent = "等插件在当天生成记录后，这里会显示完整内容。";
        elements.diaryReflection.innerHTML = "";
        elements.diaryReflection.appendChild(empty);
        elements.diaryOverview.innerHTML = "";
        elements.diaryObservations.innerHTML = "";
        elements.diaryObservations.appendChild(cloneEmptyState());
        elements.diarySummary.textContent = state.diaryDates.length ? `共 ${state.diaryDates.length} 篇日记，默认打开最近日期。` : "还没有生成任何日记。";
        return;
    }

    const diary = splitDiaryContent(content);
    const structuredSummaryHtml = renderDiaryStructuredSummary(structuredSummary);
    elements.diaryOverview.innerHTML = structuredSummaryHtml;
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

async function deleteDiary(date) {
    await apiFetch(`/api/diary/${date}`, { method: "DELETE" });
    state.selectedDiaryDates.delete(date);
    const fallbackDate = pickDiaryFallbackDate([date]);
    if (state.selectedDiaryDate === date) {
        state.selectedDiaryDate = fallbackDate;
    }
    await loadRuntime();
    await loadDiaries(fallbackDate);
    updateSummaryCards();
}

async function deleteSelectedDiaries() {
    const dates = Array.from(state.selectedDiaryDates);
    if (!dates.length) return { deletedCount: 0, deletedDates: [] };
    const fallbackDate = pickDiaryFallbackDate(dates);
    const data = await apiFetch("/api/diaries/batch", {
        method: "DELETE",
        body: JSON.stringify({ dates }),
    });
    dates.forEach((date) => state.selectedDiaryDates.delete(date));
    state.selectedDiaryDate = fallbackDate;
    await loadRuntime();
    await loadDiaries(fallbackDate);
    updateSummaryCards();
    return {
        deletedCount: Number(data.deleted_count || 0),
        deletedDates: Array.isArray(data.deleted_dates) ? data.deleted_dates : [],
    };
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
            observation.active_window
                ? renderWindowCompanionTag(
                    truncateLabel(observation.active_window, 24),
                    observation.active_window,
                    "observations"
                )
                : "",
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
            ${buildObservationExplainability(observation)}
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
                        <span class="tag">优先级${escapeHtml(item.priority ?? 0)}</span>
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
    elements.runtimeSummary.innerHTML = "";
    elements.runtimeStats.innerHTML = "";
    elements.runtimeInsights.innerHTML = "";
    elements.runtimeMedia.innerHTML = "";
    if (!runtime) {
        elements.runtimeMeta.textContent = "尚未加载运行状态。";
        elements.runtimeSummary.appendChild(cloneEmptyState());
        elements.runtimeStats.appendChild(cloneEmptyState());
        renderRuntimeMedia(null);
        return;
    }

    elements.runtimeMeta.textContent = `状态 ${runtime.state || "unknown"} · 自动任务 ${runtime.active_task_count || 0} 个 · 观察 ${runtime.observation_count || 0} 条`;
    const runtimeSummaryCards = [
        ["插件状态", runtime.enabled ? "已启用" : "已关闭", runtime.enabled ? "good" : "muted"],
        ["自动观察", runtime.is_running ? "运行中" : "待机中", runtime.is_running ? "good" : "muted"],
        ["当前模式", runtime.interaction_mode || "未设置", ""],
        [
            "识屏链路",
            runtime.screen_recognition_mode
                ? "录屏视频"
                : runtime.use_shared_screenshot_dir
                    ? "共享截图"
                    : "实时截图",
            "",
        ],
        ["窗口陪伴", formatRuntimeSwitch(runtime.enable_window_companion, "开启", "关闭"), runtime.enable_window_companion ? "good" : "muted"],
        ["学习功能", formatRuntimeSwitch(runtime.enable_learning, "开启", "关闭"), runtime.enable_learning ? "good" : "muted"],
    ];
    elements.runtimeSummary.innerHTML = runtimeSummaryCards
        .map(([label, value, tone]) => renderOverviewPill(label, value, tone))
        .join("");
    const cards = [
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
        [
            "陪伴触发",
            `${runtime.window_companion_effective_check_interval || runtime.current_check_interval || 0} 秒 / ${runtime.window_companion_effective_trigger_probability ?? runtime.current_trigger_probability ?? 0}%`,
        ],
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
    applySettingsPayload(data.settings || {});
}

async function loadWindowCandidates() {
    const data = await apiFetch("/api/windows");
    state.windowCandidates = (data.windows || []).filter(Boolean);
    renderSettingsForm();
}

async function loadDiaries(preferredDate = "") {
    renderLoading(elements.diaryList, "正在整理日记列表...");
    const data = await apiFetch("/api/diaries");
    state.diaryDates = data.diaries || [];
    pruneDiarySelections();
    const desiredDate = preferredDate || state.selectedDiaryDate;
    const hasDesiredDate = state.diaryDates.some((entry) => entry.date === desiredDate);
    state.selectedDiaryDate = hasDesiredDate
        ? desiredDate
        : state.diaryDates[0]?.date || desiredDate || new Date().toISOString().slice(0, 10);
    renderDiaryList();
    await loadDiaryDetail(state.selectedDiaryDate);
}

async function loadDiaryDetail(date) {
    state.selectedDiaryDate = date;
    elements.diaryTitle.textContent = "正在载入日记...";
    renderLoading(elements.diaryReflection, "正在读取日记内容...");
    renderLoading(elements.diaryObservations, "正在整理观察记录...");
    const data = await apiFetch(`/api/diary/${date}`);
    renderDiaryDetail(data.date, data.content || "", data.structured_summary || {});
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
    if (elements.activityMethodology) renderLoading(elements.activityMethodology, "正在整理统计说明...");
    if (elements.activityOverview) renderLoading(elements.activityOverview, "正在加载活动摘要...");
    if (elements.activityPulse) renderLoading(elements.activityPulse, "正在分析当前工作脉搏...");
    if (elements.activitySessionSummary) renderLoading(elements.activitySessionSummary, "正在整理工作轨迹...");
    if (elements.activitySessions) renderLoading(elements.activitySessions, "正在聚合连续工作段...");
    renderLoading(elements.todayActivityStats, "正在加载活动统计...");
    renderLoading(elements.totalActivityStats, "正在加载活动统计...");
    if (elements.activityReview) renderLoading(elements.activityReview, "正在生成工作回顾...");
    if (elements.activityInsights) renderLoading(elements.activityInsights, "正在整理回顾摘要...");
    if (elements.activityTopWindows) renderLoading(elements.activityTopWindows, "正在汇总主力窗口...");
    if (elements.activityCharts) renderLoading(elements.activityCharts, "正在生成活动图表...");
    if (elements.activityTrend) renderLoading(elements.activityTrend, "正在生成最近趋势...");
    if (elements.activityInputStats) renderLoading(elements.activityInputStats, "正在汇总本地输入统计...");
    if (elements.activityInputDays) renderLoading(elements.activityInputDays, "正在生成输入趋势...");
    if (elements.activitySurfaceSummary) renderLoading(elements.activitySurfaceSummary, "正在整理应用与网站轨迹...");
    if (elements.activityAppTrail) renderLoading(elements.activityAppTrail, "正在汇总主力应用...");
    if (elements.activitySiteTrail) renderLoading(elements.activitySiteTrail, "正在汇总主力网站...");
    renderLoading(elements.recentActivities, "正在加载活动统计...");
    try {
        const data = await apiFetch("/api/activity");
        state.activityStats = data;
        renderActivityStats();
    } catch (error) {
        console.error("加载活动统计失败:", error);
        if (elements.activityOverview) {
            elements.activityOverview.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法获取活动摘要</p></div>";
        }
        if (elements.activityMethodology) {
            elements.activityMethodology.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法生成统计说明</p></div>";
        }
        if (elements.activityPulse) {
            elements.activityPulse.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法生成当前工作脉搏</p></div>";
        }
        if (elements.activitySessionSummary) {
            elements.activitySessionSummary.innerHTML = "";
        }
        if (elements.activitySessions) {
            elements.activitySessions.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法整理今日工作轨迹</p></div>";
        }
        elements.todayActivityStats.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法获取活动统计数据</p></div>";
        elements.totalActivityStats.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法获取活动统计数据</p></div>";
        if (elements.activityReview) {
            elements.activityReview.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法生成工作回顾</p></div>";
        }
        if (elements.activityInsights) {
            elements.activityInsights.innerHTML = "";
        }
        if (elements.activityTopWindows) {
            elements.activityTopWindows.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法汇总主力窗口</p></div>";
        }
        if (elements.activityCharts) {
            elements.activityCharts.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法生成活动图表</p></div>";
        }
        if (elements.activityTrend) {
            elements.activityTrend.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法生成最近趋势</p></div>";
        }
        if (elements.activityInputStats) {
            elements.activityInputStats.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法加载本地输入统计</p></div>";
        }
        if (elements.activityInputDays) {
            elements.activityInputDays.innerHTML = "";
        }
        if (elements.activitySurfaceSummary) {
            elements.activitySurfaceSummary.innerHTML = "";
        }
        if (elements.activityAppTrail) {
            elements.activityAppTrail.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法整理应用轨迹</p></div>";
        }
        if (elements.activitySiteTrail) {
            elements.activitySiteTrail.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法整理网站轨迹</p></div>";
        }
        elements.recentActivities.innerHTML = "<div class='empty-state'><strong>加载失败</strong><p>无法获取活动统计数据</p></div>";
    }
}

function renderActivityStats() {
    if (!state.activityStats) return;
    if (elements.activitySearchInput) elements.activitySearchInput.value = state.activityFilters.search || "";
    if (elements.activityBucketFilter) elements.activityBucketFilter.value = state.activityFilters.bucket || "all";
    if (elements.activitySourceFilter) elements.activitySourceFilter.value = state.activityFilters.source || "all";

    const today = state.activityStats.today || {};
    const total = state.activityStats.total || {};
    const review = state.activityStats.review || {};
    const pulse = state.activityStats.pulse || {};
    const sessions = state.activityStats.sessions || {};
    const inputStats = state.activityStats.input_stats || {};
    const surfaceTrail = state.activityStats.surface_trail || {};
    const activityView = getFilteredActivityView(state.activityStats);
    const recentActivities = activityView.filteredRecentActivities;
    const filteredSessions = {
        ...sessions,
        filtered_items: activityView.filteredSessionItems,
    };
    const activeFilters = state.activityFilters || {};
    const appliedFilterLabels = [
        activeFilters.search ? `关键词“${activeFilters.search}”` : "",
        activeFilters.bucket && activeFilters.bucket !== "all"
            ? `类型 ${elements.activityBucketFilter?.selectedOptions?.[0]?.textContent || activeFilters.bucket}`
            : "",
        activeFilters.source && activeFilters.source !== "all"
            ? `来源 ${getActivitySourceLabel(activeFilters.source)}`
            : "",
    ].filter(Boolean);
    const hasActiveFilters = appliedFilterLabels.length > 0;
    if (elements.clearActivityFiltersButton) {
        elements.clearActivityFiltersButton.disabled = !hasActiveFilters;
    }

    elements.activityOverview.innerHTML = [
        renderOverviewPill("今日总计", getActivityDisplayTotalTime(today), "warm"),
        renderOverviewPill("今日工作占比", today.has_input_estimate ? (today.effective_work_ratio || formatPercent(today.work_seconds, today.total_seconds)) : formatPercent(today.work_seconds, today.total_seconds), "good"),
        renderOverviewPill("有效工作", getActivityDisplayWorkTime(today), "good"),
        renderOverviewPill("今日专注段数", today.focus_session_label || "0 段", "good"),
        renderOverviewPill("今日切换", today.switch_count_label || "0 次", ""),
        renderOverviewPill("当前状态", pulse.label || inputStats.presence_label || "等待样本", pulse.tone || ""),
        renderOverviewPill("隐私模式", sessions.privacy_masked ? "窗口脱敏" : "原始标题", sessions.privacy_masked ? "muted" : ""),
        renderOverviewPill("累计总计", getActivityDisplayTotalTime(total), ""),
        renderOverviewPill("累计工作占比", total.has_input_estimate ? (total.effective_work_ratio || formatPercent(total.work_seconds, total.total_seconds)) : formatPercent(total.work_seconds, total.total_seconds), ""),
    ].join("");
    if (elements.activityFilterSummary) {
        elements.activityFilterSummary.textContent = appliedFilterLabels.length
            ? `已应用 ${appliedFilterLabels.join(" / ")}，当前显示 ${recentActivities.length} 条最近活动、${activityView.filteredSessionItems.length} 段工作轨迹。`
            : "按关键词、类型和来源快速聚焦回顾内容。筛选只影响浏览视角，不会改动原始统计。";
    }
    renderActivityPulse(pulse);
    renderActivitySessions(filteredSessions);
    elements.todayActivityStats.innerHTML = renderActivityMetricGrid(today);
    elements.totalActivityStats.innerHTML = renderActivityMetricGrid(total);
    renderActivityReviewSection(review);
    renderActivityTopWindows(review);
    renderActivityCharts(today, total);
    renderActivityTrend(review);
    renderInputStatsSection(inputStats);
    renderActivitySurfaceTrail(surfaceTrail);
    renderActivityMethodology(review, activityView);

    if (recentActivities.length === 0) {
        elements.recentActivities.innerHTML = appliedFilterLabels.length
            ? "<div class='empty-state'><strong>当前筛选下没有活动</strong><p>可以放宽关键词、类型或来源，查看完整轨迹。</p></div>"
            : "<div class='empty-state'><strong>暂无活动记录</strong><p>开始使用插件后，这里会显示您的活动记录</p></div>";
        return;
    }

    elements.recentActivities.innerHTML = recentActivities.map((activity) => {
        const title = [activity.type, activity.scene].filter(Boolean).join(" · ") || "未标注活动";
        const timeRange = [activity.start_time, activity.end_time].filter(Boolean).join(" - ") || "时间未知";
        const windowName = activity.window || "未命名窗口";
        const pageTitle = activity.page_title ? truncateLabel(activity.page_title, 22) : "";
        const tags = [
            canQuickAddWindowCompanionTitle(windowName)
                ? renderWindowCompanionTag(truncateLabel(windowName, 24), windowName, "activity")
                : "",
            activity.app_name ? `<span class="tag">${escapeHtml(activity.app_name)}</span>` : "",
            activity.site_label ? `<span class="tag">${escapeHtml(activity.site_label)}</span>` : "",
            pageTitle ? `<span class="tag">${escapeHtml(`页面 ${pageTitle}`)}</span>` : "",
            activity.capture_source_label ? `<span class="tag">${escapeHtml(activity.capture_source_label)}</span>` : "",
            activity.duration ? `<span class="tag">${escapeHtml(activity.duration)}</span>` : "",
            activity.has_input_estimate
                ? `<span class="tag">${escapeHtml(`有效 ${activity.effective_duration || activity.duration || "0分钟"}`)}</span>`
                : "",
        ].filter(Boolean);
        const surfaceDetail = activity.page_title
            ? `${activity.site_label || activity.app_name || "当前应用"} 的 ${activity.page_title}`
            : (activity.site_label || activity.app_name || windowName);
        const detail = activity.has_input_estimate
            ? `${activity.duration || "0分钟"} 内主要停留在 ${surfaceDetail}，其中有效工作约 ${activity.effective_duration || "0分钟"}`
            : `${activity.duration || "0分钟"} 内主要停留在 ${surfaceDetail}`;
        return `
            <article class="activity-record-card">
                <div class="activity-record-head">
                    <div>
                        <h3 class="list-item-title">${escapeHtml(title)}</h3>
                        <div class="observation-tags">
                            ${tags.join("")}
                        </div>
                    </div>
                    <span class="activity-record-range">${escapeHtml(timeRange)}</span>
                </div>
                <p class="memory-meta">${escapeHtml(detail)}</p>
            </article>
        `;
    }).join("");
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
    const activeGroup = getActiveSettingsGroup();
    const fieldKeys = Array.isArray(activeGroup?.fields) ? activeGroup.fields : [];
    fieldKeys.forEach((key) => {
        const meta = getSettingMeta(key);
        const nextValue = state.settingsValues[key];
        if (meta.sensitive && !String(nextValue || "").trim()) {
            return;
        }
        if (!areSettingValuesEqual(nextValue, state.settingsSnapshot[key])) {
            updates[key] = nextValue;
        }
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
        setConnectionState("error", `刷新失败: ${error.message}`);
    }
});

elements.diaryDateInput.addEventListener("change", async () => {
    if (elements.diaryDateInput.value) await loadDiaryDetail(elements.diaryDateInput.value);
});

elements.selectAllDiaries.addEventListener("change", () => {
    if (elements.selectAllDiaries.checked) {
        state.diaryDates.forEach((entry) => state.selectedDiaryDates.add(entry.date));
    } else {
        state.selectedDiaryDates.clear();
    }
    renderDiaryList();
});

elements.clearDiarySelectionsButton.addEventListener("click", () => {
    state.selectedDiaryDates.clear();
    renderDiaryList();
});

elements.deleteSelectedDiariesButton.addEventListener("click", async () => {
    const dates = Array.from(state.selectedDiaryDates);
    if (!dates.length) {
        elements.diarySelectionMeta.textContent = "请先选择要删除的日记。";
        return;
    }
    const confirmed = confirm(buildDiaryDeleteConfirmMessage(dates));
    if (!confirmed) return;
    try {
        const result = await deleteSelectedDiaries();
        elements.diarySelectionMeta.textContent = result.deletedCount > 0
            ? `已删除 ${result.deletedCount} 篇日记。`
            : "没有找到可删除的日记。";
    } catch (error) {
        elements.diarySelectionMeta.textContent = `批量删除失败: ${error.message}`;
    }
});

elements.deleteCurrentDiaryButton.addEventListener("click", async () => {
    const currentDiaryExists = state.diaryDates.some((entry) => entry.date === state.selectedDiaryDate);
    if (!currentDiaryExists) {
        elements.diarySelectionMeta.textContent = "当前没有可删除的日记。";
        return;
    }
    const targetDate = state.selectedDiaryDate;
    const confirmed = confirm(buildDiaryDeleteConfirmMessage([targetDate]));
    if (!confirmed) return;
    const originalDisabled = elements.deleteCurrentDiaryButton.disabled;
    elements.deleteCurrentDiaryButton.disabled = true;
    try {
        await deleteDiary(targetDate);
        elements.diarySelectionMeta.textContent = `已删除 ${formatDateLabel(targetDate)} 的日记。`;
    } catch (error) {
        elements.deleteCurrentDiaryButton.disabled = originalDisabled;
        elements.diarySelectionMeta.textContent = `删除失败: ${error.message}`;
    }
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

if (elements.activitySearchInput) {
    elements.activitySearchInput.addEventListener("input", () => {
        state.activityFilters.search = elements.activitySearchInput.value || "";
        renderActivityStats();
    });
}

if (elements.activityBucketFilter) {
    elements.activityBucketFilter.addEventListener("change", () => {
        state.activityFilters.bucket = elements.activityBucketFilter.value || "all";
        renderActivityStats();
    });
}

if (elements.activitySourceFilter) {
    elements.activitySourceFilter.addEventListener("change", () => {
        state.activityFilters.source = elements.activitySourceFilter.value || "all";
        renderActivityStats();
    });
}

if (elements.clearActivityFiltersButton) {
    elements.clearActivityFiltersButton.addEventListener("click", () => {
        state.activityFilters = {
            search: "",
            bucket: "all",
            source: "all",
        };
        renderActivityStats();
    });
}

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

async function handleWindowCompanionQuickAddClick(event) {
    const button = event.target.closest("[data-window-companion-title]");
    if (!button) return;

    event.preventDefault();
    const title = button.dataset.windowCompanionTitle || "";
    const feedbackScope = button.dataset.windowCompanionFeedback || "activity";
    const originalDisabled = button.disabled;
    button.disabled = true;

    try {
        const result = await quickAddWindowCompanionTarget(title, feedbackScope);
        if (feedbackScope === "observations") {
            renderObservationList();
        } else if (feedbackScope === "diary") {
            if (state.selectedDiaryDate) {
                await loadDiaryDetail(state.selectedDiaryDate);
            }
        } else {
            renderActivityStats();
        }
        setWindowCompanionQuickAddFeedback(
            feedbackScope,
            result.alreadyEnabled
                ? `“${result.target}” 已经在窗口陪伴目标中。`
                : `已把“${result.target}”加入窗口陪伴，后续命中时会自动陪伴。`,
            result.alreadyEnabled ? "warn" : "success"
        );
    } catch (error) {
        setWindowCompanionQuickAddFeedback(
            feedbackScope,
            `加入窗口陪伴失败: ${error.message}`,
            "error"
        );
    } finally {
        button.disabled = originalDisabled;
    }
}

elements.diaryObservations.addEventListener("click", handleWindowCompanionQuickAddClick);
elements.observationList.addEventListener("click", handleWindowCompanionQuickAddClick);
elements.activitySessions.addEventListener("click", handleWindowCompanionQuickAddClick);
elements.recentActivities.addEventListener("click", handleWindowCompanionQuickAddClick);

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
        elements.loginError.textContent = `登录失败: ${error.message}`;
    }
});

async function handleSettingsActionClick(event) {
    const action = event.target.closest("[data-settings-action]")?.dataset.settingsAction;
    if (!action) return;

    if (action.startsWith("apply-template::")) {
        const presetId = action.split("::")[1] || "";
        const preset = findSettingsTemplatePreset(presetId);
        if (!preset) return;
        if (preset.preferredGroup) {
            openSettingsGroup(preset.preferredGroup);
        }
        setSettingsValues(preset.updates || {});
        setFeedbackMessage(
            elements.settingsFeedback,
            `已套用“${preset.label}”模板。确认没问题后再点保存配置。`,
            "warn"
        );
        return;
    }

    if (action === "open-vision-group") {
        openSettingsGroup("vision");
        return;
    }
    if (action === "open-runtime-group") {
        openSettingsGroup("runtime");
        return;
    }
    if (action === "open-persona-group") {
        openSettingsGroup("persona");
        return;
    }
    if (action === "open-analytics-group") {
        openSettingsGroup("analytics");
        return;
    }
    if (action === "toggle-screen-assist") {
        openSettingsGroup("persona");
        setSettingsValues({
            enable_natural_language_screen_assist: !Boolean(state.settingsValues.enable_natural_language_screen_assist),
        });
        setFeedbackMessage(elements.settingsFeedback, "已切换自然语言求助开关。", "warn");
        return;
    }
    if (action === "vision-live") {
        openSettingsGroup("vision");
        setSettingsValues({
            use_shared_screenshot_dir: false,
            shared_screenshot_dir: "",
        });
        setFeedbackMessage(elements.settingsFeedback, "已切回实时截图模式。", "warn");
        return;
    }
    if (action === "vision-docker") {
        openSettingsGroup("vision");
        setSettingsValues({
            use_shared_screenshot_dir: true,
        });
        setFeedbackMessage(elements.settingsFeedback, "已切到共享截图目录模式。", "warn");
        return;
    }
    if (action === "toggle-window-companion") {
        openSettingsGroup("runtime");
        setSettingsValues({
            enable_window_companion: !Boolean(state.settingsValues.enable_window_companion),
        });
        setFeedbackMessage(elements.settingsFeedback, "已切换窗口自动陪伴开关。", "warn");
        return;
    }
    if (action === "load-window-candidates") {
        openSettingsGroup("runtime");
        setFeedbackMessage(elements.settingsFeedback, "正在读取当前窗口列表...", "warn");
        try {
            await loadWindowCandidates();
            setFeedbackMessage(
                elements.settingsFeedback,
                state.windowCandidates.length
                    ? "已载入窗口列表。"
                    : "没有读取到可用窗口。",
                state.windowCandidates.length ? "success" : "warn"
            );
        } catch (error) {
            setFeedbackMessage(elements.settingsFeedback, `读取窗口失败: ${error.message}`, "error");
        }
        return;
    }
    if (action.startsWith("window-candidate::")) {
        openSettingsGroup("runtime");
        const index = Number(action.split("::")[1]);
        const title = state.windowCandidates[index];
        appendWindowCompanionTarget(title);
        setFeedbackMessage(
            elements.settingsFeedback,
            title
                ? `已把“${title}”加入窗口陪伴目标。`
                : "这个窗口候选已经失效，请重新读取窗口列表。",
            title ? "success" : "warn"
        );
    }
}

elements.settingsHelper.addEventListener("click", handleSettingsActionClick);
elements.runtimeInsights.addEventListener("click", handleSettingsActionClick);
elements.runtimeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitButton = elements.runtimeForm.querySelector('button[type="submit"]');
    setFeedbackMessage(elements.runtimeFeedback, "");
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = "保存中...";
    }
    try {
        const data = await apiFetch("/api/runtime/config", {
            method: "POST",
            body: JSON.stringify(readRuntimeFormValues()),
        });
        state.runtime = data.runtime || null;
        renderRuntime();
        await loadHealth();
        setFeedbackMessage(elements.runtimeFeedback, "已保存。", "success");
    } catch (error) {
        const recovered = isNetworkError(error) ? await waitForWebUiRecovery() : false;
        if (recovered) {
            await loadRuntime();
            await loadHealth();
            setFeedbackMessage(elements.runtimeFeedback, "WebUI 已重新连上。", "warn");
        } else {
            setFeedbackMessage(elements.runtimeFeedback, buildRuntimeSaveFailureMessage(error), "error");
        }
    } finally {
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = "保存设置";
        }
    }
});

if (elements.settingsSearchInput) {
    elements.settingsSearchInput.addEventListener("input", () => {
        state.settingsSearch = elements.settingsSearchInput.value || "";
        renderSettingsGroups();
        renderSettingsForm();
    });
}

if (elements.settingsModeToggle) {
    elements.settingsModeToggle.addEventListener("click", () => {
        state.settingsShowAdvanced = !state.settingsShowAdvanced;
        persistSettingsModePreference();
        renderSettingsModeToggle();
        renderSettingsGroups();
        renderSettingsForm();
    });
}

elements.resetSettingsButton.addEventListener("click", () => {
    const visibleGroups = getVisibleSettingsGroups();
    const activeGroup = visibleGroups.find((group) => group.id === state.activeSettingsGroup);
    const nextValues = { ...state.settingsValues };
    (activeGroup?.fields || []).forEach((fieldKey) => {
        nextValues[fieldKey] = state.settingsSnapshot[fieldKey];
    });
    state.settingsValues = nextValues;
    renderSettingsGroups();
    renderSettingsForm();
    setFeedbackMessage(elements.settingsFeedback, "已恢复当前分组。", "success");
});

elements.saveSettingsButton.addEventListener("click", async () => {
    const updates = collectVisibleSettingsUpdates();
    const changedKeys = Object.keys(updates);
    if (!changedKeys.length) {
        setFeedbackMessage(elements.settingsFeedback, "没有可保存的改动。", "warn");
        return;
    }

    const saveButton = elements.saveSettingsButton;
    const originalLabel = saveButton.textContent;
    saveButton.disabled = true;
    saveButton.textContent = "保存中...";
    setFeedbackMessage(elements.settingsFeedback, "");
    try {
        const data = await apiFetch("/api/settings", {
            method: "POST",
            body: JSON.stringify({ updates }),
        });
        applySettingsPayload(data.settings || {});
        await loadRuntime();
        await loadHealth();
        setFeedbackMessage(
            elements.settingsFeedback,
            `已保存 ${Number(data.meta?.applied_count || changedKeys.length)} 项配置。`,
            "success"
        );
    } catch (error) {
        const touchesWebui = changedKeys.some((key) => key.startsWith("webui."));
        const recovered = isNetworkError(error) ? await waitForWebUiRecovery() : false;
        if (recovered) {
            await loadSettings();
            await loadRuntime();
            await loadHealth();
            setFeedbackMessage(
                elements.settingsFeedback,
                touchesWebui ? "配置已提交，WebUI 已重新连上。" : "WebUI 已重新连上。",
                "warn"
            );
        } else {
            setFeedbackMessage(
                elements.settingsFeedback,
                buildSettingsSaveFailureMessage(error, {
                    changedCount: changedKeys.length,
                    touchesWebui,
                }),
                "error"
            );
        }
    } finally {
        saveButton.disabled = false;
        saveButton.textContent = originalLabel;
    }
});

elements.stopTasksButton.addEventListener("click", async () => {
    setFeedbackMessage(elements.runtimeFeedback, "");
    try {
        const data = await apiFetch("/api/runtime/stop", { method: "POST" });
        state.runtime = data.runtime || null;
        renderRuntime();
        setFeedbackMessage(elements.runtimeFeedback, "当前自动任务已停止。", "success");
    } catch (error) {
        setFeedbackMessage(elements.runtimeFeedback, `停止失败: ${error.message}`, "error");
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
    state.settingsShowAdvanced = loadSettingsModePreference();
    renderSettingsModeToggle();
    const hash = window.location.hash.replace("#", "");
    if (["runtime", "settings", "diaries", "observations", "memories", "activity"].includes(hash)) {
        switchSection(hash);
    }

    try {
        await initialize();
    } catch (error) {
        setConnectionState("error", `初始化失败: ${error.message}`);
    }
});
