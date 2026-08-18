(function (root) {
    "use strict";

    const SCREEN_BY_STATE = Object.freeze({
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
    });

    const PREVIEW_ROUTES = Object.freeze({
        "no-camera": "no_camera",
        "camera-searching": "camera_searching",
        idle: "idle",
        "idle-locked": "idle_locked",
        shooting: "shooting",
        processing: "processing",
        template: "template",
        "photo-choice": "photo_choice",
        "template-multi": "template_multi",
        done: "done",
    });

    function screenForState(state) {
        return SCREEN_BY_STATE[state] ?? null;
    }

    function previewRoute(hash) {
        if (typeof hash !== "string") return null;
        const route = hash
            .replace(/^#/, "")
            .trim()
            .toLowerCase()
            .replace(/^\/+|\/+$/g, "")
            .replace(/[\s_]+/g, "-");
        return PREVIEW_ROUTES[route] ?? null;
    }

    function shuffledCopy(items, random = Math.random) {
        const shuffled = [...items];
        for (let index = shuffled.length - 1; index > 0; index--) {
            const swapIndex = Math.floor(random() * (index + 1));
            [shuffled[index], shuffled[swapIndex]] = [
                shuffled[swapIndex],
                shuffled[index],
            ];
        }
        return shuffled;
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

    function sheetWord(count) {
        const mod100 = count % 100;
        const mod10 = count % 10;
        if (mod100 >= 11 && mod100 <= 14) return "листов";
        if (mod10 === 1) return "лист";
        if (mod10 >= 2 && mod10 <= 4) return "листа";
        return "листов";
    }

    function printItemKey(item) {
        return `${item.template}|${item.photo_index ?? ""}|${item.with_frame}`;
    }

    function nextBasketCopies(current, delta, basketTotal, maxSheets) {
        const otherSheets = basketTotal - current;
        return Math.max(
            0,
            Math.min(current + delta, maxSheets - otherSheets),
        );
    }

    function defaultWithFrame(config) {
        return config?.photo_choice_default_with_frame === true;
    }

    function buildViewerFrames(options) {
        const source = Array.isArray(options)
            ? options.find((option) => option?.photo_choice === true
                && Array.isArray(option.photo_previews)
                && option.photo_previews.length > 0)
            : null;
        return source
            ? source.photo_previews.map((preview) => ({
                previewUrl: preview.without_frame_url ?? preview.with_frame_url,
                originalUrl: preview.original_url,
            }))
            : [];
    }

    function wrappedIndex(index, length) {
        if (!Number.isInteger(length) || length <= 0) return -1;
        return ((index % length) + length) % length;
    }

    function clampAxisOffset(offset, contentSize, frameSize) {
        const limit = Math.max(0, (contentSize - frameSize) / 2);
        return Math.min(limit, Math.max(-limit, offset));
    }

    function pointCentroid(points) {
        if (!points.length) return { x: 0, y: 0 };
        const total = points.reduce(
            (sum, point) => ({ x: sum.x + point.x, y: sum.y + point.y }),
            { x: 0, y: 0 },
        );
        return { x: total.x / points.length, y: total.y / points.length };
    }

    function pointSpread(points) {
        const [first, second] = points;
        if (!second) return 0;
        return Math.hypot(second.x - first.x, second.y - first.y);
    }

    function viewerReleaseAction({
        travel,
        drift,
        viewportWidth,
        swipeRatio,
        tapDistance = 10,
    }) {
        const horizontal = Math.abs(travel);
        const vertical = Math.abs(drift);
        if (horizontal > viewportWidth * swipeRatio && horizontal > vertical) {
            return travel < 0 ? "next" : "previous";
        }
        if (horizontal < tapDistance && vertical < tapDistance) return "close";
        return null;
    }

    function qrPresentation(state, { available, dismissed }) {
        if (!available) return { modal: false, result: false };
        const result = state === "composing"
            || state === "printing"
            || state === "done";
        const modal = (result || state === "idle") && !dismissed;
        return { modal, result };
    }

    function buildPreviewTemplateOptions(
        appConfig,
        templateConfig,
        { assetUrl, photoUrl },
    ) {
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
                        original_url: photoUrl(photoIndex, false),
                    }),
                );
            }
            return option;
        });
    }

    const api = Object.freeze({
        buildPreviewTemplateOptions,
        buildViewerFrames,
        clampAxisOffset,
        defaultWithFrame,
        frameWord,
        nextBasketCopies,
        pointCentroid,
        pointSpread,
        previewRoute,
        printItemKey,
        qrPresentation,
        screenForState,
        secondWord,
        sheetWord,
        shuffledCopy,
        viewerReleaseAction,
        wrappedIndex,
    });

    root.PhotoboothCore = api;
    if (typeof module === "object" && module.exports) module.exports = api;
})(typeof globalThis === "undefined" ? this : globalThis);
