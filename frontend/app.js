const screens = {
    idle: document.getElementById("screen-idle"),
    capture: document.getElementById("screen-capture"),
    freeze: document.getElementById("screen-freeze"),
    template: document.getElementById("screen-template"),
    printing: document.getElementById("screen-printing"),
};

const liveView = document.getElementById("live-view");
const countdownNum = document.getElementById("countdown-number");
const photoCounter = document.getElementById("photo-counter");
const freezeImg = document.getElementById("freeze-img");
const templateTimer = document.getElementById("template-timer");
const printOverlay = document.getElementById("print-overlay");

let ws = null;
let currentState = "idle";
let templateTimeout = null;
let liveViewFrozen = false;

// --- WebSocket ---
function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.binaryType = "blob";

    ws.onmessage = (e) => {
        if (e.data instanceof Blob) {
            if (!liveViewFrozen) {
                const url = URL.createObjectURL(e.data);
                liveView.onload = () => URL.revokeObjectURL(url);
                liveView.src = url;
            }
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

// --- Message handler ---
function handleMessage(msg) {
    switch (msg.type) {
        case "state":
            switchScreen(msg.state, msg);
            break;
        case "countdown":
            showCountdown(msg.value);
            break;
        case "error":
            console.error("Server error:", msg.message);
            break;
    }
}

// --- Screen management ---
function switchScreen(state, data = {}) {
    currentState = state;
    Object.values(screens).forEach((s) => (s.hidden = true));

    const stateScreenMap = {
        idle: "idle",
        countdown: "capture",
        capture: "capture",
        freeze: "freeze",
        template_select: "template",
        composing: "printing",
        printing: "printing",
    };

    const screenKey = stateScreenMap[state];
    if (screenKey && screens[screenKey]) {
        screens[screenKey].hidden = false;
    }

    if (state === "countdown") {
        liveViewFrozen = false;
        const idx = (data.photo_index ?? 0) + 1;
        const total = data.total ?? 4;
        photoCounter.textContent = `${idx} / ${total}`;
    }

    if (state === "freeze") {
        // Freeze = stop updating live view, copy current frame, flash
        liveViewFrozen = true;
        freezeImg.src = liveView.src;
        document.body.classList.add("flash");
        setTimeout(() => document.body.classList.remove("flash"), 200);
    }

    if (state === "template_select") {
        liveViewFrozen = false;
        startTemplateTimer(data.timeout ?? 5);
    }

    if (state === "printing") {
        setTimeout(() => { printOverlay.hidden = false; }, 500);
    }

    if (state === "idle") {
        liveViewFrozen = false;
        setTimeout(() => { printOverlay.hidden = true; }, 15000);
    }
}

// --- Countdown display ---
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

// --- Start session on tap ---
screens.idle.addEventListener("click", () => {
    if (currentState === "idle") {
        send({ type: "start_session" });
    }
});

// --- Admin panel: hold top-left corner 3s ---
const adminTrigger = document.getElementById("admin-trigger");
const adminPanel = document.getElementById("admin-panel");
let holdTimer = null;

adminTrigger.addEventListener("pointerdown", () => {
    holdTimer = setTimeout(() => { adminPanel.hidden = false; }, 3000);
});
adminTrigger.addEventListener("pointerup", () => clearTimeout(holdTimer));
adminTrigger.addEventListener("pointerleave", () => clearTimeout(holdTimer));

document.getElementById("btn-close-admin").addEventListener("click", () => {
    adminPanel.hidden = true;
});

document.getElementById("btn-exit").addEventListener("click", () => {
    fetch("/api/shutdown", { method: "POST" });
    document.body.innerHTML = "<div style='display:flex;height:100vh;align-items:center;justify-content:center;font-size:3vw'>Выключено. Закройте окно.</div>";
});

connect();
