(function () {
    const routes = {
        "no-camera": "no_camera",
        "camera-searching": "camera_searching",
        idle: "idle",
        "idle-locked": "idle_locked",
        shooting: "shooting",
        processing: "processing",
        template: "template",
        "photo-choice": "photo_choice",
        done: "done",
    };

    const scriptUrl = new URL(document.currentScript.src);
    const devAssetsUrl = new URL("./", scriptUrl);
    const frontendUrl = new URL("../../", scriptUrl);
    const projectUrl = new URL("../../../", scriptUrl);

    function currentRoute() {
        const hash = location.hash.slice(1).trim().toLowerCase();
        return routes[hash] ?? null;
    }

    async function readJson(url) {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
        return response.json();
    }

    async function discoverPoseUrls() {
        const posesUrl = new URL("assets/poses/", frontendUrl);
        try {
            const response = await fetch(posesUrl);
            if (!response.ok) return [];
            const listing = new DOMParser().parseFromString(
                await response.text(),
                "text/html",
            );
            return Array.from(listing.querySelectorAll("a[href]"))
                .map(link => new URL(link.getAttribute("href"), posesUrl).href)
                .filter(url => /\.(?:jpe?g|png|webp)$/i.test(new URL(url).pathname))
                .sort((left, right) => left.localeCompare(
                    right,
                    undefined,
                    { numeric: true, sensitivity: "base" },
                ));
        } catch (error) {
            console.warn("Could not discover preview pose images:", error);
            return [];
        }
    }

    async function loadData() {
        if (location.protocol !== "http:" && location.protocol !== "https:") {
            throw new Error("preview requires Live Server");
        }
        const appConfig = await readJson(
            new URL("config_app.json", projectUrl),
        );
        const pack = typeof appConfig.template_pack === "string"
            ? appConfig.template_pack
            : "default";
        const [templateConfig, poseUrls] = await Promise.all([
            readJson(new URL(
                `templates/${encodeURIComponent(pack)}/config.json`,
                projectUrl,
            )),
            discoverPoseUrls(),
        ]);
        return {
            appConfig: {
                ...appConfig,
                pose_example_urls: poseUrls,
            },
            templateConfig,
        };
    }

    function assetUrl(filename) {
        return new URL(filename, devAssetsUrl).href;
    }

    function photoUrl(index, withFrame) {
        const number = index % 4 + 1;
        const variant = withFrame ? "framed" : "unframed";
        return assetUrl(`photo-${number}-${variant}.svg`);
    }

    function buildTemplateOptions(appConfig, templateConfig) {
        const definitions = templateConfig.templates;
        if (!definitions || typeof definitions !== "object") {
            throw new Error("template config has no templates");
        }
        const photoCount = Math.max(
            1,
            Math.floor(Number(appConfig.num_photos)) || 1,
        );

        return Object.entries(definitions).map(([name, definition]) => {
            const photoChoice = definition.photo_choice === true;
            const option = {
                name,
                label: typeof definition.label === "string" && definition.label
                    ? definition.label
                    : name,
                preview_url: photoChoice
                    ? photoUrl(0, true)
                    : assetUrl(
                        definition.preview_split === "horizontal"
                            ? "template-strips.svg"
                            : "template-grid.svg",
                    ),
            };
            if (photoChoice) {
                option.photo_choice = true;
                option.photo_previews = Array.from(
                    { length: photoCount },
                    (_, photoIndex) => ({
                        photo_index: photoIndex,
                        with_frame_url: photoUrl(photoIndex, true),
                        without_frame_url: photoUrl(photoIndex, false),
                    }),
                );
            }
            return option;
        });
    }

    function showError(error) {
        console.error("Could not open photobooth preview:", error);
        document.querySelectorAll(".screen").forEach(screen => {
            screen.hidden = true;
        });
        let message = document.getElementById("preview-config-error");
        if (!message) {
            message = document.createElement("div");
            message.id = "preview-config-error";
            message.style.cssText = "position:fixed;inset:0;padding:10vw;display:flex;align-items:center;justify-content:center;text-align:center;font-size:2.5vw;line-height:1.45;background:#fff;color:#b42318;z-index:999";
            document.body.appendChild(message);
        }
        message.textContent = (
            "Не удалось загрузить боевые конфиги. "
            + "Запустите Live Server от корня проекта photobooth."
        );
    }

    async function render(api) {
        try {
            const route = currentRoute();
            if (!route) return;
            const { appConfig, templateConfig } = await loadData();

            document.getElementById("preview-config-error")?.remove();
            api.applyConfig(appConfig);

            const countdown = document.getElementById("countdown-number");
            countdown.classList.remove("visible");
            countdown.textContent = "";

            if (route === "no_camera" || route === "camera_searching") {
                api.switchScreen(route, { start_locked: false });
            } else if (route === "idle" || route === "idle_locked") {
                const locked = route === "idle_locked";
                api.switchScreen("idle", {
                    start_locked: locked,
                    technical_event_active: locked,
                });
            } else if (route === "shooting") {
                const total = Math.max(
                    1,
                    Math.floor(Number(appConfig.num_photos)) || 1,
                );
                api.switchScreen("shooting", {
                    photo_index: Math.min(1, total - 1),
                    total,
                });
                countdown.textContent = String(Math.max(
                    1,
                    Math.floor(Number(appConfig.countdown_seconds)) || 1,
                ));
                countdown.classList.add("visible");
            } else if (route === "processing") {
                api.switchScreen("processing", {});
            } else if (route === "template" || route === "photo_choice") {
                api.switchScreen("template_select", {
                    templates: buildTemplateOptions(appConfig, templateConfig),
                    timeout: appConfig.template_select_timeout,
                });
                if (route === "photo_choice") {
                    document.querySelector(
                        '.template-btn[data-photo-choice="true"]',
                    )?.click();
                }
            } else if (route === "done") {
                api.switchScreen("done", {
                    session_id: "preview-session",
                    session_link: "https://disk.yandex.ru/d/photobooth-preview",
                });
            }
        } catch (error) {
            showError(error);
        }
    }

    window.photoboothPreview = Object.freeze({
        isActive: () => currentRoute() !== null,
        liveViewUrl: assetUrl("live-view.svg"),
        render,
    });
})();
