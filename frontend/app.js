const screens = {
    no_camera: document.getElementById("screen-no-camera"),
    idle: document.getElementById("screen-idle"),
    shooting: document.getElementById("screen-shooting"),
    template: document.getElementById("screen-template"),
    printing: document.getElementById("screen-printing"),
};

const liveView = document.getElementById("live-view");
const countdownNum = document.getElementById("countdown-number");
const photoCounter = document.getElementById("photo-counter");
const templateTimer = document.getElementById("template-timer");
const printOverlay = document.getElementById("print-overlay");

let ws = null;
let currentState = "idle";
let templateTimeout = null;

// --- WebSocket ---
function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.binaryType = "blob";

    ws.onmessage = (e) => {
        if (e.data instanceof Blob) {
            // Live view frame — just update img, nothing else
            const url = URL.createObjectURL(e.data);
            liveView.onload = () => URL.revokeObjectURL(url);
            liveView.src = url;
            return;
        }
        handleMessage(JSON.parse(e.data));
    };

    ws.onclose = () => setTimeout(connect, 1000);
    ws.onerror = () => ws.close();
}

function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg));
    }
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

// --- Message handler ---
function handleMessage(msg) {
    switch (msg.type) {
        case "state":
            switchScreen(msg.state, msg);
            break;
        case "countdown":
            showCountdown(msg.value);
            if (msg.value <= 3) beep(440 + (3 - msg.value) * 110, 500);
            break;
        case "flash":
            beep(880, 500);
            document.body.classList.add("flash");
            setTimeout(() => document.body.classList.remove("flash"), 200);
            break;
        case "error":
            console.error("Server:", msg.message);
            // Show error on screen for 3s
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
        composing: "printing",
        printing: "printing",
    };

    const key = map[state];
    if (key && screens[key]) screens[key].hidden = false;

    if (state === "countdown" || state === "shooting") {
        const idx = (data.photo_index ?? 0) + 1;
        photoCounter.textContent = `${idx} / ${data.total ?? 4}`;
    }

    if (state === "template_select") {
        startTemplateTimer(data.timeout ?? 5);
    }

    if (state === "printing") {
        setTimeout(() => { printOverlay.hidden = false; }, 500);
    }

    if (state === "idle") {
        setTimeout(() => { printOverlay.hidden = true; }, 15000);
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

// --- Load config and apply settings ---
fetch("/api/config").then(r => r.json()).then(cfg => {
    if (cfg.mirror_live_view) {
        liveView.style.transform = "scaleX(-1)";
    }
});

connect();
