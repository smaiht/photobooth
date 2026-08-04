const screens = {
    no_camera: document.getElementById("screen-no-camera"),
    idle: document.getElementById("screen-idle"),
    shooting: document.getElementById("screen-shooting"),
    processing: document.getElementById("screen-processing"),
    template: document.getElementById("screen-template"),
    done: document.getElementById("screen-done"),
};

const liveView = document.getElementById("live-view");
const countdownNum = document.getElementById("countdown-number");
const photoCounter = document.getElementById("photo-counter");
const poseRails = {
    left: document.getElementById("pose-rail-left"),
    right: document.getElementById("pose-rail-right"),
};
const templateTimer = document.getElementById("template-timer");
const templateOptions = document.getElementById("template-options");
const templateSkip = document.getElementById("template-skip");
const photoChoicePanel = document.getElementById("photo-choice-panel");
const photoChoiceOptions = document.getElementById("photo-choice-options");
const frameOn = document.getElementById("frame-on");
const frameOff = document.getElementById("frame-off");
const qrModal = document.getElementById("qr-modal");
const qrModalClose = document.getElementById("qr-modal-close");
const qrModalCode = document.getElementById("qr-modal-code");
const qrModalText = document.getElementById("qr-modal-text");
const cameraStatusTitle = document.getElementById("camera-status-title");
const cameraStatusSubtitle = document.getElementById("camera-status-subtitle");
const tapLockStatus = document.querySelector(".tap-lock-status");

let ws = null;
let currentState = "idle";
let startLocked = true;
let templateTimeout = null;
let liveViewStarted = false;
let currentSessionId = "";
let displayedQrUrl = "";
let dismissedQrSessionId = "";
let renderedTemplateSignature = "";
let photoChoiceTemplate = null;
let photoChoiceWithFrame = true;
let photoPreviewCycle = null;
let currentShootingPhotoIndex = 0;
const sessionLinks = new Map();

let poseExampleUrls = [];
let poseExamplesPerSide = 0;
let poseImagePreloaders = [];
let renderedPoseSignature = "";

function renderPoseExamples(photoIndex = 0) {
    const parsedIndex = Number(photoIndex);
    const safeIndex = Number.isFinite(parsedIndex)
        ? Math.max(0, Math.floor(parsedIndex))
        : 0;
    const imagesPerShot = poseExamplesPerSide * 2;
    if (!imagesPerShot || !poseExampleUrls.length) return;

    const startIndex = (safeIndex * imagesPerShot) % poseExampleUrls.length;
    const signature = `${startIndex}:${poseExamplesPerSide}:${poseExampleUrls.length}`;
    if (signature === renderedPoseSignature) return;
    renderedPoseSignature = signature;

    Object.entries(poseRails).forEach(([side, rail]) => {
        const sideOffset = side === "left" ? 0 : poseExamplesPerSide;
        const cards = Array.from({ length: poseExamplesPerSide }, (_, index) => {
            const imageIndex = (
                startIndex + sideOffset + index
            ) % poseExampleUrls.length;
            const card = document.createElement("img");
            card.className = "pose-card";
            card.src = poseExampleUrls[imageIndex];
            card.alt = `Пример позы ${imageIndex + 1}`;
            card.draggable = false;
            card.decoding = "async";
            return card;
        });
        rail.replaceChildren(...cards);
    });
}

function configurePoseExamples(cfg) {
    poseExampleUrls = Array.isArray(cfg.pose_example_urls)
        ? cfg.pose_example_urls.filter(url => typeof url === "string" && url)
        : [];
    poseImagePreloaders = poseExampleUrls.map(url => {
        const image = new Image();
        image.decoding = "async";
        image.src = url;
        return image;
    });
    const configuredCount = Math.floor(Number(cfg.pose_examples_per_side));
    poseExamplesPerSide = Number.isFinite(configuredCount)
        ? Math.max(0, configuredCount)
        : 3;
    const layoutCount = Math.max(1, poseExamplesPerSide);
    const gapVh = 0.8;
    document.documentElement.style.setProperty(
        "--pose-card-max-height",
        `calc((100% - ${(layoutCount - 1) * gapVh}vh) / ${layoutCount})`,
    );
    const hidden = !poseExamplesPerSide || !poseExampleUrls.length;
    Object.values(poseRails).forEach(rail => {
        rail.hidden = hidden;
        if (hidden) rail.replaceChildren();
    });
    renderedPoseSignature = "";
    if (!hidden) renderPoseExamples(currentShootingPhotoIndex);
}

// --- WebSocket ---
let wsReconnectTimer = null;
function connect() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onmessage = (e) => {
        handleMessage(JSON.parse(e.data));
    };

    ws.onclose = () => {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = setTimeout(connect, 1000);
    };
    ws.onerror = () => ws.close();
}

// State sync — catch missed WS messages
setInterval(() => {
    fetch(`/api/state?frontend=${currentState}`).then(r => r.json()).then(s => {
        if (s.state !== currentState) {
            console.warn(`State desync: frontend=${currentState} backend=${s.state}, fixing`);
            switchScreen(s.state, s);
        } else {
            syncStartLock(s);
            syncSessionContext(s.state, s);
            if (s.state === "template_select") {
                renderTemplateOptions(s.templates);
            }
            refreshQr();
        }
    }).catch(() => {});
}, 1000);

function send(msg) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(msg));
    return true;
}

// --- Sound ---
let audioCtx = null;
function beep(freq, duration) {
    if (!audioCtx) audioCtx = new AudioContext();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.frequency.value = freq;
    osc.type = "sine";
    gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + duration / 1000);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + duration / 1000);
}

// --- QR modal ---
function showQrModal(url, text) {
    if (!config.show_qr || !url || typeof qrcode === "undefined") return;
    if (displayedQrUrl !== url) {
        const qr = qrcode(0, "M");
        qr.addData(url);
        qr.make();
        qrModalCode.innerHTML = qr.createSvgTag(8);
        displayedQrUrl = url;
    }
    qrModalText.textContent = text;
    qrModal.hidden = false;
}

function hideQrModal() {
    qrModal.hidden = true;
}

qrModalClose.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    dismissedQrSessionId = currentSessionId;
    hideQrModal();
});

function syncSessionContext(state, data = {}) {
    const sessionId = typeof data.session_id === "string" ? data.session_id : "";
    if (sessionId) {
        if (sessionId !== currentSessionId) {
            currentSessionId = sessionId;
            sessionLinks.clear();
            displayedQrUrl = "";
            dismissedQrSessionId = "";
            hideQrModal();
        }
        if (data.session_link) sessionLinks.set(sessionId, data.session_link);
    }
}

function refreshQr() {
    const visibleStates = new Set(["composing", "printing", "done", "idle"]);
    const url = sessionLinks.get(currentSessionId);
    if (!url || !visibleStates.has(currentState)
            || dismissedQrSessionId === currentSessionId) {
        hideQrModal();
        return;
    }
    showQrModal(url, "Фото с последней съёмки загружаются сюда");
}

// --- Message handler ---
function handleMessage(msg) {
    switch (msg.type) {
        case "state":
            switchScreen(msg.state, msg);
            break;
        case "session_link":
            if (msg.session_id && msg.url) {
                sessionLinks.set(msg.session_id, msg.url);
                refreshQr();
            }
            break;
        case "countdown":
            showCountdown(msg.value);
            if (msg.beep) beep(440 + (msg.beep_index ?? 0) * 110, 500);
            break;
        case "flash":
            beep(880, 500);
            const flashEl = document.getElementById("flash-overlay");
            flashEl.style.opacity = "1";
            setTimeout(() => flashEl.style.opacity = "0", 150);
            break;
        case "error":
            console.error("Server:", msg.message);
            const errDiv = document.createElement("div");
            errDiv.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.9);display:flex;align-items:center;justify-content:center;font-size:3vw;z-index:999;color:#f55";
            errDiv.textContent = msg.message;
            document.body.appendChild(errDiv);
            setTimeout(() => errDiv.remove(), 3000);
            break;
    }
}

// --- Screen management ---
const tapPrompt = document.querySelector(".tap-prompt");
let sessionStarting = false;

function syncStartLock(data = {}) {
    if (typeof data.start_locked !== "boolean") return;
    startLocked = data.start_locked;
    tapLockStatus.hidden = !startLocked;
    screens.idle.classList.toggle("start-locked", startLocked);
    screens.idle.setAttribute("aria-disabled", String(startLocked));
}

function setLiveView(active) {
    if (active === liveViewStarted) return;
    liveViewStarted = active;
    if (active) {
        liveView.src = "/live";
    } else {
        liveView.removeAttribute("src");
    }
}

function switchScreen(state, data = {}) {
    syncStartLock(data);
    syncSessionContext(state, data);

    // First countdown of a new session — delay screen switch, animate tap prompt
    if (state === "countdown" && data.photo_index === 0 && !sessionStarting) {
        sessionStarting = true;
        setLiveView(true); // connect to /live in background while animating
        hideQrModal();
        tapPrompt.classList.add("exiting");
        const warmup = (config.live_view_warmup ?? 0.3) * 1000;
        setTimeout(() => {
            sessionStarting = false;
            tapPrompt.classList.remove("exiting");
            _doSwitch(state, data);
        }, warmup);
        return;
    }

    _doSwitch(state, data);
}

function _doSwitch(state, data) {
    currentState = state;
    Object.values(screens).forEach((s) => (s.hidden = true));

    const map = {
        no_camera: "no_camera",
        camera_searching: "no_camera",
        idle: "idle",
        countdown: "shooting",
        shooting: "shooting",
        processing: "processing",
        template_select: "template",
        composing: "done",
        printing: "done",
        done: "done",
    };

    const key = map[state];
    if (key && screens[key]) screens[key].hidden = false;
    setLiveView(key === "shooting");

    if (key === "no_camera") {
        const searching = state === "camera_searching";
        cameraStatusTitle.textContent = searching
            ? "ИЩЕМ КАМЕРУ…"
            : "КАМЕРА НЕДОСТУПНА";
        cameraStatusSubtitle.textContent = searching
            ? "Подключите камеру — поиск идёт автоматически"
            : "Проверьте установку Canon EDSDK";
    }

    if (state === "countdown" || state === "shooting") {
        const photoIndex = data.photo_index ?? 0;
        currentShootingPhotoIndex = photoIndex;
        const idx = photoIndex + 1;
        photoCounter.textContent = `${idx} / ${data.total ?? 4}`;
        renderPoseExamples(photoIndex);
    }

    // New session — hide QR
    if (state === "countdown" && data.photo_index === 0) {
        hideQrModal();
    }

    if (state === "template_select") {
        templateSkip.disabled = false;
        renderTemplateOptions(data.templates);
        startTemplateTimer(data.timeout ?? config.template_select_timeout ?? 5);
    } else {
        clearInterval(templateTimeout);
        templateTimer.textContent = "";
        resetTemplateSelection();
    }

    refreshQr();
}

// --- Countdown ---
function showCountdown(value) {
    countdownNum.textContent = value;
    countdownNum.classList.add("visible");
    countdownNum.style.transform = "scale(1.3)";
    setTimeout(() => { countdownNum.style.transform = "scale(1)"; }, 100);
    setTimeout(() => { countdownNum.classList.remove("visible"); }, 800);
}

// --- Template selection ---
function lockTemplateSelection() {
    clearInterval(templateTimeout);
    templateTimer.textContent = "";
    templateSkip.disabled = true;
    templateOptions.querySelectorAll("button").forEach((item) => {
        item.disabled = true;
    });
    photoChoiceOptions.querySelectorAll("button").forEach((item) => {
        item.disabled = true;
    });
    frameOn.disabled = true;
    frameOff.disabled = true;
}

templateSkip.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (currentState !== "template_select" || !send({ type: "skip_print" })) return;
    lockTemplateSelection();
});

function renderTemplateOptions(options) {
    if (!Array.isArray(options)) return;
    const signature = JSON.stringify(options.map((option) => [
        option.name,
        option.label,
        option.preview_url,
        option.photo_choice === true,
        Array.isArray(option.photo_previews)
            ? option.photo_previews.map((preview) => [
                preview.photo_index,
                preview.with_frame_url,
                preview.without_frame_url,
            ])
            : [],
    ]));
    if (signature === renderedTemplateSignature) return;

    renderedTemplateSignature = signature;
    resetPhotoChoice();
    templateOptions.replaceChildren();
    options.forEach((option) => {
        if (!option || typeof option.name !== "string"
                || typeof option.preview_url !== "string") return;

        const label = typeof option.label === "string" && option.label
            ? option.label
            : option.name;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "template-btn";
        const isPhotoChoice = option.photo_choice === true
            && Array.isArray(option.photo_previews)
            && option.photo_previews.length > 0;
        button.dataset.photoChoice = String(isPhotoChoice);

        const preview = document.createElement("img");
        preview.className = "template-preview";
        preview.src = option.preview_url;
        preview.alt = label;
        preview.draggable = false;

        const caption = document.createElement("span");
        caption.textContent = label;
        button.append(preview, caption);
        if (isPhotoChoice) {
            button.photoPreviews = option.photo_previews;
        }
        button.addEventListener("click", () => {
            if (isPhotoChoice) {
                openPhotoChoice(option, button);
                return;
            }
            if (!send({ type: "select_template", template: option.name })) return;
            lockTemplateSelection();
        });
        templateOptions.appendChild(button);
    });
    startPhotoPreviewCycle();
}

function startPhotoPreviewCycle() {
    clearInterval(photoPreviewCycle);
    const buttons = [...templateOptions.querySelectorAll(
        '.template-btn[data-photo-choice="true"]',
    )];
    if (!buttons.length) return;
    let index = 0;
    photoPreviewCycle = setInterval(() => {
        index++;
        buttons.forEach((button) => {
            const previews = button.photoPreviews;
            if (!Array.isArray(previews) || !previews.length) return;
            const preview = previews[index % previews.length];
            button.querySelector("img").src = preview.with_frame_url;
        });
    }, 1000);
}

function resetPhotoChoice() {
    photoChoiceTemplate = null;
    photoChoiceWithFrame = true;
    photoChoicePanel.hidden = true;
    photoChoiceOptions.replaceChildren();
    screens.template.classList.remove("photo-choice-open");
    templateOptions.querySelectorAll(".template-btn").forEach((button) => {
        button.classList.remove("active");
    });
    updateFrameSegments();
}

function resetTemplateSelection() {
    clearInterval(photoPreviewCycle);
    photoPreviewCycle = null;
    renderedTemplateSignature = "";
    resetPhotoChoice();
    templateOptions.replaceChildren();
}

function openPhotoChoice(option, selectedButton) {
    const alreadyOpen = photoChoiceTemplate?.name === option.name
        && !photoChoicePanel.hidden;
    photoChoiceTemplate = option;
    if (!alreadyOpen) photoChoiceWithFrame = true;
    screens.template.classList.add("photo-choice-open");
    photoChoicePanel.hidden = false;
    templateOptions.querySelectorAll(".template-btn").forEach((button) => {
        button.classList.toggle("active", button === selectedButton);
    });
    updateFrameSegments();
    renderPhotoChoices();
}

function updateFrameSegments() {
    frameOn.classList.toggle("active", photoChoiceWithFrame);
    frameOff.classList.toggle("active", !photoChoiceWithFrame);
    frameOn.setAttribute("aria-pressed", String(photoChoiceWithFrame));
    frameOff.setAttribute("aria-pressed", String(!photoChoiceWithFrame));
    frameOn.disabled = photoChoiceTemplate === null;
    frameOff.disabled = photoChoiceTemplate === null;
}

function renderPhotoChoices() {
    photoChoiceOptions.replaceChildren();
    if (!photoChoiceTemplate) return;

    photoChoiceTemplate.photo_previews.forEach((choice) => {
        const photoNumber = choice.photo_index + 1;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "photo-choice-btn";
        button.setAttribute("aria-label", `Напечатать фото ${photoNumber}`);

        const preview = document.createElement("img");
        preview.src = photoChoiceWithFrame
            ? choice.with_frame_url
            : choice.without_frame_url;
        preview.alt = `Фото ${photoNumber}`;
        preview.draggable = false;

        const number = document.createElement("span");
        number.className = "photo-choice-number";
        number.textContent = photoNumber;
        button.append(preview, number);
        button.addEventListener("click", () => {
            const sent = send({
                type: "select_template",
                template: photoChoiceTemplate.name,
                photo_index: choice.photo_index,
                with_frame: photoChoiceWithFrame,
            });
            if (sent) lockTemplateSelection();
        });
        photoChoiceOptions.appendChild(button);
    });
}

frameOn.addEventListener("click", () => {
    photoChoiceWithFrame = true;
    updateFrameSegments();
    renderPhotoChoices();
});

frameOff.addEventListener("click", () => {
    photoChoiceWithFrame = false;
    updateFrameSegments();
    renderPhotoChoices();
});

function startTemplateTimer(seconds) {
    let remaining = seconds;
    const renderRemaining = () => {
        const mod100 = remaining % 100;
        const mod10 = remaining % 10;
        const unit = mod100 >= 11 && mod100 <= 14
            ? "секунд"
            : mod10 === 1
                ? "секунда"
                : mod10 >= 2 && mod10 <= 4
                    ? "секунды"
                    : "секунд";
        templateTimer.textContent = `Осталось ${remaining} ${unit}`;
    };
    renderRemaining();
    clearInterval(templateTimeout);
    templateTimeout = setInterval(() => {
        remaining--;
        if (remaining <= 0) {
            clearInterval(templateTimeout);
            templateTimer.textContent = "";
            lockTemplateSelection();
        } else {
            renderRemaining();
        }
    }, 1000);
}

// --- Start session ---
screens.idle.addEventListener("click", () => {
    if (currentState !== "idle" || startLocked) return;
    send({ type: "start_session" });
});

// --- Config ---
let config = {};
fetch("/api/config").then(r => r.json()).then(cfg => {
    config = cfg;
    if (cfg.mirror_live_view) liveView.style.transform = "scaleX(-1)";
    const rootStyle = document.documentElement.style;
    const fit = cfg.live_view_fit === "cover" ? "cover" : "contain";
    const safeMargin = (value, fallback) => {
        const parsed = Number(value);
        return Number.isFinite(parsed)
            ? Math.min(25, Math.max(0, parsed))
            : fallback;
    };
    rootStyle.setProperty("--live-view-fit", fit);
    rootStyle.setProperty(
        "--live-view-margin-top",
        `${safeMargin(cfg.live_view_margin_top_percent, 5)}vh`,
    );
    rootStyle.setProperty(
        "--live-view-margin-bottom",
        `${safeMargin(cfg.live_view_margin_bottom_percent, 12)}vh`,
    );
    configurePoseExamples(cfg);
    rootStyle.setProperty("--warmup", (cfg.live_view_warmup || 0.3) + "s");
    refreshQr();
});

connect();
