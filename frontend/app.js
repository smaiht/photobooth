const screens = {
    no_camera: document.getElementById("screen-no-camera"),
    idle: document.getElementById("screen-idle"),
    shooting: document.getElementById("screen-shooting"),
    template: document.getElementById("screen-template"),
    done: document.getElementById("screen-done"),
};

const liveView = document.getElementById("live-view");
const countdownNum = document.getElementById("countdown-number");
const photoCounter = document.getElementById("photo-counter");
const templateTimer = document.getElementById("template-timer");
const processingOverlay = null; // removed
const qrModal = document.getElementById("qr-modal");
const qrModalCode = document.getElementById("qr-modal-code");
const qrModalText = document.getElementById("qr-modal-text");

let ws = null;
let currentState = "idle";
let templateTimeout = null;

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
            switchScreen(s.state);
        }
    }).catch(() => {});
}, 1000);

function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
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
    if (!url || typeof qrcode === "undefined") return;
    const qr = qrcode(0, "M");
    qr.addData(url);
    qr.make();
    qrModalCode.innerHTML = qr.createSvgTag(8);
    qrModalText.textContent = text;
    qrModal.hidden = false;
}

function updateQrText(text) {
    qrModalText.textContent = text;
}

function hideQrModal() {
    qrModal.hidden = true;
}

// --- Message handler ---
function handleMessage(msg) {
    switch (msg.type) {
        case "state":
            switchScreen(msg.state, msg);
            break;
        case "countdown":
            showCountdown(msg.value);
            if (msg.value <= config.countdown_from) beep(440 + (config.countdown_from - msg.value) * 110, 500);
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
function switchScreen(state, data = {}) {
    currentState = state;
    Object.values(screens).forEach((s) => (s.hidden = true));

    const map = {
        no_camera: "no_camera",
        idle: "idle",
        countdown: "shooting",
        shooting: "shooting",
        template_select: "template",
        composing: "done",
        printing: "done",
        done: "done",
    };

    const key = map[state];
    if (key && screens[key]) screens[key].hidden = false;

    if (state === "countdown" || state === "shooting") {
        const idx = (data.photo_index ?? 0) + 1;
        photoCounter.textContent = `${idx} / ${data.total ?? 4}`;
    }

    // New session — hide QR
    if (state === "countdown" && data.photo_index === 0) {
        hideQrModal();
    }

    if (state === "template_select") {
        startTemplateTimer(data.timeout ?? 5);
    }

    // Composing — show QR immediately
    if (state === "composing") {
        if (data.session_url) {
            showQrModal(data.session_url, "Скачать оригиналы");
        }
    }

    // Idle — update QR text if visible
    if (state === "idle") {
        updateQrText("Прошлые фото");
    }
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
function startTemplateTimer(seconds) {
    let remaining = seconds;
    templateTimer.textContent = `Авто-выбор через ${remaining}с`;
    clearInterval(templateTimeout);
    templateTimeout = setInterval(() => {
        remaining--;
        if (remaining <= 0) {
            clearInterval(templateTimeout);
            templateTimer.textContent = "";
        } else {
            templateTimer.textContent = `Авто-выбор через ${remaining}с`;
        }
    }, 1000);
}

document.querySelectorAll(".template-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
        send({ type: "select_template", template: btn.dataset.template });
        clearInterval(templateTimeout);
    });
});

// --- Start session ---
screens.idle.addEventListener("click", () => {
    if (currentState === "idle") send({ type: "start_session" });
});

// --- Config ---
let config = {};
fetch("/api/config").then(r => r.json()).then(cfg => {
    config = cfg;
    if (cfg.mirror_live_view) liveView.style.transform = "scaleX(-1)";
});

connect();
