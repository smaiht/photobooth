"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const core = require("../../frontend/core.js");

test("backend states select the intended screen", () => {
    const expected = {
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
    for (const [state, screen] of Object.entries(expected)) {
        assert.equal(core.screenForState(state), screen);
    }
    assert.equal(core.screenForState("unknown"), null);
});

test("preview hashes are normalized and unknown hashes stay inactive", () => {
    const expected = {
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
    };
    for (const [hash, route] of Object.entries(expected)) {
        assert.equal(core.previewRoute(`#${hash}`), route);
    }
    assert.equal(core.previewRoute("# IDLE-LOCKED "), "idle_locked");
    assert.equal(core.previewRoute("#idle_locked"), "idle_locked");
    assert.equal(core.previewRoute("#/idle-locked/"), "idle_locked");
    assert.equal(core.previewRoute("#not-a-screen"), null);
    assert.equal(core.previewRoute(null), null);
});

test("Russian sheet counter uses the correct word forms", () => {
    const cases = [
        [1, "лист"],
        [2, "листа"],
        [5, "листов"],
        [11, "листов"],
        [21, "лист"],
        [24, "листа"],
    ];
    for (const [count, sheets] of cases) {
        assert.equal(core.sheetWord(count), sheets);
    }
});

test("shuffle returns the same members without mutating its input", () => {
    const source = ["a", "b", "c", "d"];
    const shuffled = core.shuffledCopy(source, () => 0);

    assert.deepEqual(source, ["a", "b", "c", "d"]);
    assert.notDeepEqual(shuffled, source);
    assert.deepEqual([...shuffled].sort(), [...source].sort());
});

test("print basket keys separate photo and frame variants", () => {
    const plain = { template: "grid" };
    const framed = { template: "single", photo_index: 1, with_frame: true };
    const unframed = { ...framed, with_frame: false };

    assert.notEqual(core.printItemKey(plain), core.printItemKey(framed));
    assert.notEqual(core.printItemKey(framed), core.printItemKey(unframed));
});

test("basket changes are clamped by zero and the total sheet limit", () => {
    assert.equal(core.nextBasketCopies(1, -5, 3, 6), 0);
    assert.equal(core.nextBasketCopies(1, 1, 3, 6), 2);
    assert.equal(core.nextBasketCopies(2, 5, 5, 6), 3);
    assert.equal(core.nextBasketCopies(3, 1, 6, 6), 3);
});

test("photo choice honors the configured frame default", () => {
    assert.equal(core.defaultWithFrame({ photo_choice_default_with_frame: true }), true);
    assert.equal(core.defaultWithFrame({ photo_choice_default_with_frame: false }), false);
    assert.equal(core.defaultWithFrame({}), false);
});

test("viewer frames come from the first usable photo-choice template", () => {
    const frames = core.buildViewerFrames([
        { name: "grid" },
        {
            name: "single",
            photo_choice: true,
            photo_previews: [
                {
                    with_frame_url: "frame-1.jpg",
                    without_frame_url: "plain-1.jpg",
                    original_url: "original-1.jpg",
                },
                {
                    with_frame_url: "frame-2.jpg",
                    original_url: "original-2.jpg",
                },
            ],
        },
    ]);

    assert.deepEqual(frames, [
        { previewUrl: "plain-1.jpg", originalUrl: "original-1.jpg" },
        { previewUrl: "frame-2.jpg", originalUrl: "original-2.jpg" },
    ]);
    assert.deepEqual(core.buildViewerFrames(null), []);
    assert.equal(core.wrappedIndex(-1, frames.length), 1);
    assert.equal(core.wrappedIndex(2, frames.length), 0);
});

test("viewer geometry clamps pan and measures pointer gestures", () => {
    assert.equal(core.clampAxisOffset(90, 300, 200), 50);
    assert.equal(core.clampAxisOffset(-90, 300, 200), -50);
    assert.equal(core.clampAxisOffset(25, 100, 200), 0);
    assert.deepEqual(core.pointCentroid([{ x: 0, y: 2 }, { x: 4, y: 6 }]),
        { x: 2, y: 4 });
    assert.equal(core.pointSpread([{ x: 0, y: 0 }, { x: 3, y: 4 }]), 5);
    assert.equal(core.pointSpread([{ x: 0, y: 0 }]), 0);
});

test("viewer release distinguishes swipes, taps, and diagonal movement", () => {
    const gesture = { viewportWidth: 1000, swipeRatio: 0.1 };
    assert.equal(core.viewerReleaseAction({ ...gesture, travel: -150, drift: 20 }),
        "next");
    assert.equal(core.viewerReleaseAction({ ...gesture, travel: 150, drift: 20 }),
        "previous");
    assert.equal(core.viewerReleaseAction({ ...gesture, travel: 3, drift: 4 }),
        "close");
    assert.equal(core.viewerReleaseAction({ ...gesture, travel: 150, drift: 180 }),
        null);
});

test("QR presentation follows session state and dismissal", () => {
    assert.deepEqual(core.qrPresentation("done", {
        available: true,
        dismissed: false,
    }), { modal: true, result: true });
    assert.deepEqual(core.qrPresentation("idle", {
        available: true,
        dismissed: true,
    }), { modal: false, result: false });
    assert.deepEqual(core.qrPresentation("done", {
        available: true,
        dismissed: true,
    }), { modal: false, result: true });
    assert.deepEqual(core.qrPresentation("shooting", {
        available: true,
        dismissed: false,
    }), { modal: false, result: false });
    assert.deepEqual(core.qrPresentation("done", {
        available: false,
        dismissed: false,
    }), { modal: false, result: false });
});

test("preview options are derived from template config", () => {
    const options = core.buildPreviewTemplateOptions(
        { num_photos: 3 },
        {
            templates: {
                strips: { label: "Полоски", preview_split: "horizontal" },
                grid: {},
                single: { label: "Одно фото", photo_choice: true },
            },
        },
        {
            assetUrl: (name) => `asset:${name}`,
            photoUrl: (index, withFrame) => (
                `photo:${index}:${withFrame ? "frame" : "plain"}`
            ),
        },
    );

    assert.deepEqual(options.map((option) => option.name),
        ["strips", "grid", "single"]);
    assert.equal(options[0].preview_url, "asset:template-strips.svg");
    assert.equal(options[1].label, "grid");
    assert.equal(options[1].preview_url, "asset:template-grid.svg");
    assert.equal(options[2].preview_url, "photo:0:frame");
    assert.equal(options[2].photo_previews.length, 3);
    assert.deepEqual(options[2].photo_previews[2], {
        photo_index: 2,
        with_frame_url: "photo:2:frame",
        without_frame_url: "photo:2:plain",
        original_url: "photo:2:plain",
    });
});

test("preview options reject a malformed template config", () => {
    assert.throws(() => core.buildPreviewTemplateOptions(
        {},
        {},
        { assetUrl: String, photoUrl: String },
    ), /template config has no templates/);
});
