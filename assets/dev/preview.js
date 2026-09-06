(function () {
    const core = window.PhotoboothCore;

    const scriptUrl = new URL(document.currentScript.src);
    const devAssetsUrl = new URL("./", scriptUrl);
    const projectUrl = new URL("../../", scriptUrl);

    function currentRoute() {
        return core.previewRoute(location.hash);
    }

    async function readJson(url) {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
        return response.json();
    }

    async function discoverPoseUrls() {
        const posesUrl = new URL("assets/poses/", projectUrl);
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
                    payment: { available: true, status: "idle" },
                });
            } else if (route.startsWith("payment_")) {
                const status = {
                    payment_loading: "creating",
                    payment_qr: "pending",
                    payment_success: "succeeded",
                    payment_review: "review",
                }[route];
                api.switchScreen("idle", {
                    start_locked: status !== "succeeded",
                    technical_event_active: true,
                    payment: {
                        available: true,
                        status,
                        amount: appConfig.technical_event_price_rubles,
                        qr: "https://example.com/photobooth-payment-preview",
                        message: status === "pending" ? "Макет QR-кода — без оплаты" : "",
                    },
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
            } else if (route === "template" || route === "photo_choice"
                    || route === "template_multi") {
                const maxSheets = Math.floor(
                    Number(appConfig.multi_print_max_sheets));
                api.switchScreen("template_select", {
                    templates: core.buildPreviewTemplateOptions(
                        appConfig,
                        templateConfig,
                        { assetUrl, photoUrl },
                    ),
                    timeout: appConfig.template_select_timeout,
                    // Preview always offers the mode so its layout can be
                    // checked; the booth only shows it in the technical event.
                    multi_print: true,
                    multi_print_max_sheets: Number.isFinite(maxSheets)
                        ? maxSheets
                        : 6,
                });
                if (route === "template_multi") {
                    document.getElementById("template-multi")?.click();
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
