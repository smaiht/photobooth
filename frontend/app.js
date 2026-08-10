const screens = {
    no_camera: document.getElementById("screen-no-camera"),
    idle: document.getElementById("screen-idle"),
    shooting: document.getElementById("screen-shooting"),
    processing: document.getElementById("screen-processing"),
    template: document.getElementById("screen-template"),
    done: document.getElementById("screen-done"),
};

const previewController = window.photoboothPreview;
const previewMode = previewController?.isActive() === true;

const liveView = document.getElementById("live-view");
const countdownNum = document.getElementById("countdown-number");
const photoCounter = document.getElementById("photo-counter");
const poseRails = {
    left: document.getElementById("pose-rail-left"),
    right: document.getElementById("pose-rail-right"),
};
const idlePoseField = document.getElementById("idle-pose-field");
const idlePoseRows = Array.from(document.querySelectorAll(".idle-pose-row"));
const idleSessionInfo = document.getElementById("idle-session-info");
const idlePriceBadge = document.getElementById("idle-price-badge");
const idlePriceValue = document.getElementById("idle-price-value");
const idleStartButton = document.getElementById("idle-start-button");
const templateTimer = document.getElementById("template-timer");
const templateMain = document.getElementById("template-main");
const templateOptions = document.getElementById("template-options");
const templateSkip = document.getElementById("template-skip");
const photoChoicePanel = document.getElementById("photo-choice-panel");
const photoChoiceOptions = document.getElementById("photo-choice-options");
const frameOn = document.getElementById("frame-on");
const frameOff = document.getElementById("frame-off");
const templateZoom = document.getElementById("template-zoom");
const photoViewer = document.getElementById("photo-viewer");
const photoViewerViewport = document.getElementById("photo-viewer-viewport");
const photoViewerImage = document.getElementById("photo-viewer-image");
const photoViewerPrev = document.getElementById("photo-viewer-prev");
const photoViewerNext = document.getElementById("photo-viewer-next");
const photoViewerThumbs = document.getElementById("photo-viewer-thumbs");
const qrModal = document.getElementById("qr-modal");
const qrModalClose = document.getElementById("qr-modal-close");
const qrModalCode = document.getElementById("qr-modal-code");
const qrModalText = document.getElementById("qr-modal-text");
const resultQrPanel = document.getElementById("result-qr-panel");
const resultQrCode = document.getElementById("result-qr-code");
const cameraStatusTitle = document.getElementById("camera-status-title");
const cameraStatusSubtitle = document.getElementById("camera-status-subtitle");
const cameraRecoverButton = document.getElementById("camera-recover-button");
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
let photoChoiceWithFrame = false;
let photoPreviewCycle = null;
let currentShootingPhotoIndex = 0;
let technicalEventActive = false;
let technicalEventPriceRubles = 0;
let cameraRecoveryPending = false;
const sessionLinks = new Map();

let poseExampleUrls = [];
let poseExamplesPerSide = 0;
let poseImagePreloaders = [];
let idlePoseGroups = [];
let shootingPosePool = [];
const shootingPoseSelections = new Map();
let renderedPoseSignature = "";

const PHOTO_PREVIEW_CYCLE_MS = 500;
const IDLE_POSE_GROUP_COUNT = 3;

function shuffledCopy(items) {
    const shuffled = [...items];
    for (let index = shuffled.length - 1; index > 0; index--) {
        const swapIndex = Math.floor(Math.random() * (index + 1));
        [shuffled[index], shuffled[swapIndex]] = [
            shuffled[swapIndex],
            shuffled[index],
        ];
    }
    return shuffled;
}

function resetIdlePoseGroups() {
    idlePoseGroups = Array.from(
        { length: IDLE_POSE_GROUP_COUNT },
        () => [],
    );
    shuffledCopy(poseExampleUrls).forEach((url, index) => {
        idlePoseGroups[index % IDLE_POSE_GROUP_COUNT].push(url);
    });
}

function resetShootingPosePool() {
    shootingPosePool = shuffledCopy(poseExampleUrls);
    shootingPoseSelections.clear();
    renderedPoseSignature = "";
}

function takeShootingPoseSelection(photoIndex, count) {
    if (shootingPoseSelections.has(photoIndex)) {
        return shootingPoseSelections.get(photoIndex);
    }

    const selection = shootingPosePool.splice(0, count);
    shootingPoseSelections.set(photoIndex, selection);
    return selection;
}

function renderIdlePoseBackdrop() {
    if (!idlePoseField) return;
    const hidden = !poseExampleUrls.length;
    idlePoseField.hidden = hidden;
    if (hidden) {
        idlePoseRows.forEach(row => row.replaceChildren());
        return;
    }

    const sequenceCopies = 6;
    const centralRowStart = Math.max(
        0,
        Math.floor((idlePoseRows.length - IDLE_POSE_GROUP_COUNT) / 2),
    );
    idlePoseRows.forEach((row, rowIndex) => {
        const groupIndex = (
            (rowIndex - centralRowStart) % IDLE_POSE_GROUP_COUNT
            + IDLE_POSE_GROUP_COUNT
        ) % IDLE_POSE_GROUP_COUNT;
        const group = idlePoseGroups[groupIndex]?.length
            ? idlePoseGroups[groupIndex]
            : poseExampleUrls;
        const configuredOffset = Math.floor(Number(row.dataset.poseOffset)) || 0;
        const startIndex = configuredOffset % group.length;
        const urls = Array.from({ length: group.length }, (_, index) => (
            group[(startIndex + index) % group.length]
        ));
        const track = document.createElement("div");
        track.className = "idle-pose-track";
        for (let copyIndex = 0; copyIndex < sequenceCopies; copyIndex++) {
            const sequence = document.createElement("div");
            sequence.className = "idle-pose-sequence";
            urls.forEach(url => {
                const image = document.createElement("img");
                image.className = "idle-pose-tile";
                image.src = url;
                image.alt = "";
                image.draggable = false;
                image.decoding = "async";
                sequence.appendChild(image);
            });
            track.appendChild(sequence);
        }
        row.replaceChildren(track);
    });
}

function frameWord(count) {
    const mod100 = count % 100;
    const mod10 = count % 10;
    if (mod100 >= 11 && mod100 <= 14) return "КАДРОВ";
    if (mod10 === 1) return "КАДР";
    if (mod10 >= 2 && mod10 <= 4) return "КАДРА";
    return "КАДРОВ";
}

function secondWord(count) {
    const mod100 = count % 100;
    const mod10 = count % 10;
    if (mod100 >= 11 && mod100 <= 14) return "СЕКУНД";
    if (mod10 === 1) return "СЕКУНДА";
    if (mod10 >= 2 && mod10 <= 4) return "СЕКУНДЫ";
    return "СЕКУНД";
}

function configureIdleSessionInfo(cfg) {
    const configuredPhotos = Math.floor(Number(cfg.num_photos));
    const photoCount = Number.isFinite(configuredPhotos)
        ? Math.max(1, configuredPhotos)
        : 4;
    const configuredSeconds = Math.floor(Number(cfg.countdown_seconds));
    const countdownSeconds = Number.isFinite(configuredSeconds)
        ? Math.max(0, configuredSeconds)
        : 5;
    idleSessionInfo.textContent = (
        `${photoCount} ${frameWord(photoCount)} С ТАЙМЕРОМ `
        + `${countdownSeconds} ${secondWord(countdownSeconds)}`
    );
}

function renderTechnicalEventBadge() {
    const visible = technicalEventActive && technicalEventPriceRubles > 0;
    idlePriceBadge.hidden = !visible;
    if (visible) {
        idlePriceValue.textContent = (
            `${technicalEventPriceRubles.toLocaleString("ru-RU")} ₽`
        );
    }
}

function syncTechnicalEvent(data = {}) {
    if (typeof data.technical_event_active === "boolean") {
        technicalEventActive = data.technical_event_active;
        renderTechnicalEventBadge();
    }
}

function renderPoseExamples(photoIndex = 0) {
    const parsedIndex = Number(photoIndex);
    const safeIndex = Number.isFinite(parsedIndex)
        ? Math.max(0, Math.floor(parsedIndex))
        : 0;
    const imagesPerShot = poseExamplesPerSide * 2;
    if (!imagesPerShot || !poseExampleUrls.length) return;

    const selectedUrls = takeShootingPoseSelection(safeIndex, imagesPerShot);
    const signature = `${safeIndex}:${poseExamplesPerSide}:${selectedUrls.join("\n")}`;
    if (signature === renderedPoseSignature) return;
    renderedPoseSignature = signature;

    Object.entries(poseRails).forEach(([side, rail]) => {
        const sideOffset = side === "left" ? 0 : poseExamplesPerSide;
        const cards = selectedUrls
            .slice(sideOffset, sideOffset + poseExamplesPerSide)
            .map((url, index) => {
                const card = document.createElement("img");
                card.className = "pose-card";
                card.src = url;
                card.alt = `Пример позы ${sideOffset + index + 1}`;
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
    resetIdlePoseGroups();
    resetShootingPosePool();
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
    if (!hidden) renderPoseExamples(currentShootingPhotoIndex);
    renderIdlePoseBackdrop();
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
if (!previewMode) {
    setInterval(() => {
        fetch(`/api/state?frontend=${currentState}`).then(r => r.json()).then(s => {
            if (s.state !== currentState) {
                console.warn(`State desync: frontend=${currentState} backend=${s.state}, fixing`);
                switchScreen(s.state, s);
            } else {
                syncStartLock(s);
                syncTechnicalEvent(s);
                syncSessionContext(s.state, s);
                if (s.state === "template_select") {
                    renderTemplateOptions(s.templates);
                }
                refreshQr();
            }
        }).catch(() => {});
    }, 1000);
}

function send(msg) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(msg));
    return true;
}

cameraRecoverButton.addEventListener("click", async () => {
    if (cameraRecoveryPending
            || !["no_camera", "camera_searching"].includes(currentState)) return;
    cameraRecoveryPending = true;
    cameraRecoverButton.disabled = true;
    cameraStatusTitle.textContent = "ПЕРЕПОДКЛЮЧАЕМ КАМЕРУ…";
    cameraStatusSubtitle.textContent = "Это может занять несколько секунд";
    try {
        const response = await fetch("/api/camera/recover", { method: "POST" });
        const result = await response.json();
        if (!response.ok || result.status !== "ok") {
            throw new Error(result.message || `HTTP ${response.status}`);
        }
        cameraStatusSubtitle.textContent = result.message;
    } catch (error) {
        cameraStatusTitle.textContent = "КАМЕРА НЕ ПЕРЕПОДКЛЮЧЕНА";
        cameraStatusSubtitle.textContent = error.message;
    } finally {
        cameraRecoveryPending = false;
        cameraRecoverButton.disabled = false;
    }
});

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
function renderQrCodes(url) {
    if (!config.show_qr || !url || typeof qrcode === "undefined") return;
    if (displayedQrUrl !== url) {
        const qr = qrcode(0, "M");
        qr.addData(url);
        qr.make();
        const markup = qr.createSvgTag(8);
        qrModalCode.innerHTML = markup;
        resultQrCode.innerHTML = markup;
        displayedQrUrl = url;
    }
    return true;
}

function showQrModal(url, text) {
    if (!renderQrCodes(url)) return;
    qrModalText.textContent = text;
    qrModal.hidden = false;
}

function hideQrModal() {
    qrModal.hidden = true;
}

function showResultQr(url) {
    if (!renderQrCodes(url)) return;
    resultQrPanel.hidden = false;
}

function hideResultQr() {
    resultQrPanel.hidden = true;
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
            resetShootingPosePool();
            sessionLinks.clear();
            displayedQrUrl = "";
            dismissedQrSessionId = "";
            hideQrModal();
            hideResultQr();
        }
        if (data.session_link) sessionLinks.set(sessionId, data.session_link);
    }
}

function refreshQr() {
    const visibleStates = new Set(["composing", "printing", "done", "idle"]);
    const resultStates = new Set(["composing", "printing", "done"]);
    const url = sessionLinks.get(currentSessionId);
    if (!config.show_qr || !url || typeof qrcode === "undefined") {
        hideQrModal();
        hideResultQr();
        return;
    }

    if (resultStates.has(currentState)) {
        showResultQr(url);
    } else {
        hideResultQr();
    }

    if (!visibleStates.has(currentState)
            || dismissedQrSessionId === currentSessionId) {
        hideQrModal();
        return;
    }
    showQrModal(url, "ФОТО И ВИДЕО С ПОСЛЕДНЕЙ СЪЕМКИ ЗАГРУЖАЮТСЯ СЮДА");
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
        case "template_timer":
            if (currentState === "template_select" && !templateSkip.disabled) {
                startTemplateTimer(msg.timeout ?? templateTimerSeconds);
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
    idleStartButton.disabled = startLocked;
}

function setLiveView(active) {
    if (active === liveViewStarted) return;
    liveViewStarted = active;
    if (active) {
        liveView.src = previewMode ? previewController.liveViewUrl : "/live";
    } else {
        liveView.removeAttribute("src");
    }
}

function switchScreen(state, data = {}) {
    syncStartLock(data);
    syncTechnicalEvent(data);
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
    const previousState = currentState;
    currentState = state;
    if (state === "idle" && previousState !== "idle") {
        resetIdlePoseGroups();
        renderIdlePoseBackdrop();
    }
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

    if (key === "no_camera" && !cameraRecoveryPending) {
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
        hideResultQr();
    }

    if (state === "template_select") {
        templateSkip.disabled = false;
        renderTemplateOptions(data.templates);
        startTemplateTimer(data.timeout ?? config.template_select_timeout ?? 5);
    } else {
        clearInterval(templateTimeout);
        setTemplateTimerText("");
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
let templateMainAnimation = null;

function animateTemplateMainFrom(previousTop) {
    templateMainAnimation?.cancel();

    const nextTop = templateMain.getBoundingClientRect().top;
    const offset = previousTop - nextTop;
    if (screens.template.hidden || Math.abs(offset) < 1) {
        templateMainAnimation = null;
        return;
    }

    const animation = templateMain.animate([
        { transform: `translateY(${offset}px)` },
        { transform: "translateY(0)" },
    ], {
        duration: 320,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
    });
    templateMainAnimation = animation;
    animation.addEventListener("finish", () => {
        if (templateMainAnimation === animation) templateMainAnimation = null;
    }, { once: true });
}

function lockTemplateSelection() {
    closePhotoViewer();
    clearInterval(templateTimeout);
    setTemplateTimerText("");
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

const SVG_NS = "http://www.w3.org/2000/svg";

// A stroked chevron drawn as SVG: round caps and joins read cleanly at kiosk
// size, unlike a rotated CSS border square.
function createChevron() {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "template-caption-chevron");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", "M5 9.5 12 16l7-6.5");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "2.6");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    svg.appendChild(path);
    return svg;
}

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
                preview.original_url,
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
        if (isPhotoChoice) {
            button.setAttribute("aria-expanded", "false");
            button.setAttribute("aria-controls", "photo-choice-panel");
        }

        const preview = document.createElement("img");
        preview.className = "template-preview";
        // A photo_choice tile must start on the same variant the cycle and the
        // chooser use, otherwise the first frame flips look inconsistent.
        preview.src = isPhotoChoice
            ? photoChoiceTileUrl(option.photo_previews[0])
            : option.preview_url;
        preview.alt = label;
        preview.draggable = false;

        const caption = document.createElement("span");
        caption.className = "template-caption";
        const captionLabel = document.createElement("span");
        captionLabel.className = "template-caption-label";
        // "1 фото" alone does not say there is anything to pick from, so the
        // number of available frames goes straight into the name.
        captionLabel.textContent = isPhotoChoice
            ? `${label} из ${option.photo_previews.length}`
            : label;
        caption.appendChild(captionLabel);
        if (isPhotoChoice) {
            const toggle = document.createElement("span");
            toggle.className = "template-caption-toggle";

            // Two short lines keep the control on the same row as the name:
            // only the verb changes between open and closed.
            const toggleText = document.createElement("span");
            toggleText.className = "template-caption-toggle-text";
            const toggleVerb = document.createElement("span");
            toggleVerb.className = "template-caption-toggle-verb";
            toggleVerb.dataset.openHint = "СКРЫТЬ";
            toggleVerb.dataset.closedHint = "РАСКРЫТЬ";
            toggleVerb.textContent = toggleVerb.dataset.closedHint;
            const toggleNoun = document.createElement("span");
            toggleNoun.textContent = "ВАРИАНТЫ";
            toggleText.append(toggleVerb, toggleNoun);

            toggle.append(toggleText, createChevron());
            caption.appendChild(toggle);
        }
        button.append(preview, caption);
        if (isPhotoChoice) {
            button.photoPreviews = option.photo_previews;
        }
        button.addEventListener("click", () => {
            if (isPhotoChoice) {
                const isOpen = photoChoiceTemplate?.name === option.name
                    && !photoChoicePanel.hidden;
                if (isOpen) {
                    closePhotoChoice();
                    return;
                }
                openPhotoChoice(option, button);
                return;
            }
            if (!send({ type: "select_template", template: option.name })) return;
            lockTemplateSelection();
        });
        templateOptions.appendChild(button);
    });
    configurePhotoViewer(options);
    startPhotoPreviewCycle();
}

// The frame default lives in config_app.json, so backend and frontend cannot
// drift apart. Missing config keeps the plain photo first.
function defaultWithFrame() {
    return config.photo_choice_default_with_frame === true;
}

function photoChoiceTileUrl(preview) {
    // The tile advertises the same variant the chooser opens on.
    const url = defaultWithFrame()
        ? preview.with_frame_url
        : preview.without_frame_url;
    return url ?? preview.with_frame_url;
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
            button.querySelector("img").src = photoChoiceTileUrl(preview);
        });
    }, PHOTO_PREVIEW_CYCLE_MS);
}

function syncTemplateHint(button) {
    const verb = button.querySelector(".template-caption-toggle-verb");
    if (!verb) return;
    const expanded = button.getAttribute("aria-expanded") === "true";
    verb.textContent = expanded ? verb.dataset.openHint : verb.dataset.closedHint;
}

function closePhotoChoice() {
    const wasOpen = !photoChoicePanel.hidden;
    const previousTop = wasOpen
        ? templateMain.getBoundingClientRect().top
        : null;
    photoChoiceTemplate = null;
    photoChoiceWithFrame = defaultWithFrame();
    photoChoicePanel.hidden = true;
    photoChoiceOptions.replaceChildren();
    templateOptions.querySelectorAll(".template-btn").forEach((button) => {
        button.classList.remove("active");
        if (button.dataset.photoChoice === "true") {
            button.setAttribute("aria-expanded", "false");
            syncTemplateHint(button);
        }
    });
    updateFrameSegments();
    if (previousTop !== null) animateTemplateMainFrom(previousTop);
}

function resetPhotoChoice() {
    closePhotoChoice();
}

function resetTemplateSelection() {
    clearInterval(photoPreviewCycle);
    photoPreviewCycle = null;
    renderedTemplateSignature = "";
    closePhotoViewer();
    viewerFrames = [];
    templateZoom.hidden = true;
    resetPhotoChoice();
    templateOptions.replaceChildren();
}

function openPhotoChoice(option, selectedButton) {
    const previousTop = templateMain.getBoundingClientRect().top;
    photoChoiceTemplate = option;
    photoChoiceWithFrame = defaultWithFrame();
    photoChoicePanel.hidden = false;
    templateOptions.querySelectorAll(".template-btn").forEach((button) => {
        button.classList.toggle("active", button === selectedButton);
        if (button.dataset.photoChoice === "true") {
            button.setAttribute("aria-expanded", String(button === selectedButton));
            syncTemplateHint(button);
        }
    });
    updateFrameSegments();
    renderPhotoChoices();
    animateTemplateMainFrom(previousTop);
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

screens.template.addEventListener("click", (event) => {
    if (photoChoicePanel.hidden) return;
    const target = event.target instanceof Element ? event.target : null;
    // The viewer sits on top of this screen, so its own clicks must not
    // collapse the chooser underneath it.
    if (!target || target.closest(
        ".template-btn, .photo-choice-panel, #template-skip,"
        + " #template-zoom, .photo-viewer",
    )) {
        return;
    }
    closePhotoChoice();
});

// --- Photo viewer (magnifier) ---
// Frames come from the photo_choice template: it is the only one that produces
// per-photo previews, and those previews are what makes the viewer open
// instantly. Without such a template the magnifier stays hidden.
let viewerFrames = [];
let viewerIndex = 0;

function showViewerFrame(index) {
    if (!viewerFrames.length) return;
    viewerIndex = (index + viewerFrames.length) % viewerFrames.length;
    const frame = viewerFrames[viewerIndex];
    // Every frame starts unzoomed, so a leftover pan cannot hide the new photo.
    resetViewerTransform();

    // Show the cached preview immediately, then swap in the original once it
    // has decoded. Only one full-size bitmap is ever held.
    photoViewerImage.src = frame.previewUrl;
    photoViewerImage.alt = `Кадр ${viewerIndex + 1}`;
    if (frame.originalUrl) {
        const original = new Image();
        original.decoding = "async";
        original.onload = () => {
            if (!photoViewer.hidden && viewerFrames[viewerIndex] === frame) {
                photoViewerImage.src = frame.originalUrl;
            }
        };
        original.src = frame.originalUrl;
    }
    photoViewerThumbs.querySelectorAll("button").forEach((thumb, position) => {
        thumb.classList.toggle("active", position === viewerIndex);
        thumb.setAttribute("aria-current", String(position === viewerIndex));
    });
}

function renderViewerThumbs() {
    photoViewerThumbs.replaceChildren();
    viewerFrames.forEach((frame, position) => {
        const thumb = document.createElement("button");
        thumb.type = "button";
        thumb.className = "photo-viewer-thumb";
        thumb.setAttribute("aria-label", `Кадр ${position + 1}`);
        const image = document.createElement("img");
        image.src = frame.previewUrl;
        image.alt = "";
        image.draggable = false;
        thumb.appendChild(image);
        thumb.addEventListener("click", () => showViewerFrame(position));
        photoViewerThumbs.appendChild(thumb);
    });
}

function openPhotoViewer() {
    if (!viewerFrames.length) return;
    photoViewer.hidden = false;
    templateZoom.setAttribute("aria-expanded", "true");
    renderViewerThumbs();
    showViewerFrame(0);
}

function closePhotoViewer() {
    if (photoViewer.hidden) return;
    photoViewer.hidden = true;
    templateZoom.setAttribute("aria-expanded", "false");
    resetViewerTransform();
    // Drop the full-size bitmap instead of keeping it alive behind the screen.
    photoViewerImage.removeAttribute("src");
    photoViewerThumbs.replaceChildren();
}

function togglePhotoViewer() {
    if (photoViewer.hidden) {
        openPhotoViewer();
    } else {
        closePhotoViewer();
    }
}

function configurePhotoViewer(options) {
    const source = Array.isArray(options)
        ? options.find((option) => option?.photo_choice === true
            && Array.isArray(option.photo_previews)
            && option.photo_previews.length > 0)
        : null;
    viewerFrames = source
        ? source.photo_previews.map((preview) => ({
            previewUrl: preview.without_frame_url ?? preview.with_frame_url,
            originalUrl: preview.original_url,
        }))
        : [];
    templateZoom.hidden = viewerFrames.length === 0;
}

templateZoom.addEventListener("click", togglePhotoViewer);
photoViewerPrev.addEventListener("click", () => showViewerFrame(viewerIndex - 1));
photoViewerNext.addEventListener("click", () => showViewerFrame(viewerIndex + 1));

// --- Pinch zoom and swipe ---
// Pointer Events are tracked only inside the viewport, so the rest of the kiosk
// UI keeps its normal single-tap behaviour and never scales.
const VIEWER_MAX_SCALE = 4;
const VIEWER_SWIPE_RATIO = 0.08;
const viewerPointers = new Map();
let viewerScale = 1;
let viewerOffsetX = 0;
let viewerOffsetY = 0;
let gestureStart = null;

function applyViewerTransform() {
    photoViewerImage.style.transform =
        `translate(${viewerOffsetX}px, ${viewerOffsetY}px) scale(${viewerScale})`;
    // Panning only makes sense once the photo is larger than the viewport.
    photoViewerViewport.classList.toggle("zoomed", viewerScale > 1);
}

function resetViewerTransform() {
    viewerScale = 1;
    viewerOffsetX = 0;
    viewerOffsetY = 0;
    gestureStart = null;
    viewerPointers.clear();
    applyViewerTransform();
}

// Keep the photo from being dragged away from the viewport: at scale 1 it stays
// centred, and beyond that it may travel only over its own hidden overflow.
function clampViewerOffset() {
    const frame = photoViewerViewport.getBoundingClientRect();
    const width = photoViewerImage.clientWidth * viewerScale;
    const height = photoViewerImage.clientHeight * viewerScale;
    const limitX = Math.max(0, (width - frame.width) / 2);
    const limitY = Math.max(0, (height - frame.height) / 2);
    viewerOffsetX = Math.min(limitX, Math.max(-limitX, viewerOffsetX));
    viewerOffsetY = Math.min(limitY, Math.max(-limitY, viewerOffsetY));
}

function pointerCentroid() {
    const points = [...viewerPointers.values()];
    const total = points.reduce(
        (sum, point) => ({ x: sum.x + point.x, y: sum.y + point.y }),
        { x: 0, y: 0 },
    );
    return { x: total.x / points.length, y: total.y / points.length };
}

function pointerSpread() {
    const [first, second] = [...viewerPointers.values()];
    if (!second) return 0;
    return Math.hypot(second.x - first.x, second.y - first.y);
}

function beginGesture() {
    gestureStart = {
        centroid: pointerCentroid(),
        spread: pointerSpread(),
        scale: viewerScale,
        offsetX: viewerOffsetX,
        offsetY: viewerOffsetY,
        pointers: viewerPointers.size,
    };
}

photoViewerViewport.addEventListener("pointerdown", (event) => {
    photoViewerViewport.setPointerCapture(event.pointerId);
    viewerPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    beginGesture();
});

photoViewerViewport.addEventListener("pointermove", (event) => {
    if (!viewerPointers.has(event.pointerId) || !gestureStart) return;
    viewerPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });

    const centroid = pointerCentroid();
    if (gestureStart.spread > 0 && viewerPointers.size >= 2) {
        // Two fingers: scale around the point between them, so the spot the
        // guest pinched stays under their fingers.
        const ratio = pointerSpread() / gestureStart.spread;
        viewerScale = Math.min(
            VIEWER_MAX_SCALE, Math.max(1, gestureStart.scale * ratio));
        const growth = viewerScale / gestureStart.scale;
        const frame = photoViewerViewport.getBoundingClientRect();
        const anchorX = gestureStart.centroid.x - frame.left - frame.width / 2;
        const anchorY = gestureStart.centroid.y - frame.top - frame.height / 2;
        viewerOffsetX = centroid.x - frame.left - frame.width / 2
            - (anchorX - gestureStart.offsetX) * growth;
        viewerOffsetY = centroid.y - frame.top - frame.height / 2
            - (anchorY - gestureStart.offsetY) * growth;
    } else if (viewerScale > 1) {
        // One finger on a zoomed photo pans it.
        viewerOffsetX = gestureStart.offsetX + centroid.x - gestureStart.centroid.x;
        viewerOffsetY = gestureStart.offsetY + centroid.y - gestureStart.centroid.y;
    } else {
        return;
    }
    clampViewerOffset();
    applyViewerTransform();
});

function endViewerPointer(event) {
    if (!viewerPointers.has(event.pointerId)) return;
    const start = gestureStart;
    const wasSingleTouch = viewerPointers.size === 1 && start?.pointers === 1;
    viewerPointers.delete(event.pointerId);

    if (wasSingleTouch && viewerScale === 1 && event.type === "pointerup") {
        const travel = event.clientX - start.centroid.x;
        const drift = Math.abs(event.clientY - start.centroid.y);
        const swipe = window.innerWidth * VIEWER_SWIPE_RATIO;
        if (Math.abs(travel) > swipe && Math.abs(travel) > drift) {
            // A horizontal swipe flips frames, but only while not zoomed in:
            // otherwise the same movement is a pan.
            showViewerFrame(viewerIndex + (travel < 0 ? 1 : -1));
        } else if (Math.abs(travel) < 10 && drift < 10) {
            // A plain tap anywhere over the photo area closes the viewer, so
            // the whole dark overlay behaves the same way.
            closePhotoViewer();
            return;
        }
    }

    if (viewerPointers.size === 0) {
        gestureStart = null;
        if (viewerScale === 1) resetViewerTransform();
    } else {
        // Lifting one finger of a pinch continues as a pan without a jump.
        beginGesture();
    }
}

photoViewerViewport.addEventListener("pointerup", endViewerPointer);
photoViewerViewport.addEventListener("pointercancel", endViewerPointer);

// Any tap on the dark backdrop closes the viewer; the magnifier button itself
// toggles it back. Taps over the photo are handled by the gesture code, which
// tells a tap apart from a swipe or a pan.
photoViewer.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target || target.closest(
        ".photo-viewer-viewport, .photo-viewer-nav, .photo-viewer-thumbs",
    )) return;
    closePhotoViewer();
});

function setTemplateTimerText(text) {
    templateTimer.textContent = text;
}

let templateTimerSeconds = 0;

function startTemplateTimer(seconds) {
    templateTimerSeconds = seconds;
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
        setTemplateTimerText(`Осталось ${remaining} ${unit}`);
    };
    renderRemaining();
    clearInterval(templateTimeout);
    templateTimeout = setInterval(() => {
        remaining--;
        if (remaining <= 0) {
            clearInterval(templateTimeout);
            setTemplateTimerText("");
            lockTemplateSelection();
        } else {
            renderRemaining();
        }
    }, 1000);
}

// Any touch anywhere on the template screen restarts the selection timeout.
// There is no button: the backend is told to extend, and the visible countdown
// restarts from the same configured value.
function requestTemplateExtension() {
    if (currentState !== "template_select" || templateSkip.disabled) return;
    if (previewMode) {
        startTemplateTimer(templateTimerSeconds);
        return;
    }
    send({ type: "template_activity" });
}

screens.template.addEventListener("pointerdown", requestTemplateExtension);

// --- Start session ---
idleStartButton.addEventListener("click", () => {
    if (currentState !== "idle" || startLocked || idleStartButton.disabled) return;
    if (send({ type: "start_session" })) idleStartButton.disabled = true;
});

// --- Config ---
let config = {};

function applyConfig(cfg) {
    config = cfg;
    configureIdleSessionInfo(cfg);
    const configuredPrice = Math.floor(Number(cfg.technical_event_price_rubles));
    technicalEventPriceRubles = Number.isFinite(configuredPrice)
        ? Math.max(0, configuredPrice)
        : 0;
    renderTechnicalEventBadge();
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
}

window.addEventListener("hashchange", () => location.reload());

if (previewMode) {
    previewController.render({ applyConfig, switchScreen });
} else {
    fetch("/api/config").then(response => response.json()).then(applyConfig);
    connect();
}
