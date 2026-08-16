import ctypes
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend import main
from backend.camera import constants, edsdk
from backend.config import (
    ROOT_DIR,
    apply_camera_preset,
    preset_names,
    update_camera_config_field,
)


class ConfigOptionsMatchEdsdkMapsTests(unittest.TestCase):
    """config_camera.json must advertise exactly what the EDSDK maps accept."""

    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(
            (ROOT_DIR / "config_camera.json").read_text(encoding="utf-8"))

    def test_av_tv_iso_options_list_every_supported_value(self):
        for field, mapping in (
            ("av", constants.AV_MAP),
            ("tv", constants.TV_MAP),
            ("iso", constants.ISO_MAP),
        ):
            with self.subTest(field=field):
                self.assertEqual(
                    self.config[f"_{field}_options"], list(mapping))

    def test_current_values_resolve_to_edsdk_codes(self):
        for field, resolver in constants.CAMERA_VALUE_RESOLVERS.items():
            with self.subTest(field=field):
                resolved = resolver(self.config[field])
                self.assertIsNotNone(resolved)
                # The stored value must already be canonical, so a restart
                # never rewrites the file just to normalise it.
                self.assertEqual(resolved[0], self.config[field])

    def test_other_option_lists_only_hold_known_values(self):
        for field, mapping in (
            ("image_quality", constants.IMAGE_QUALITY_MAP),
            ("ae_mode", constants.AE_MODE_MAP),
            ("shutter_type", constants.SHUTTER_TYPE_MAP),
            ("white_balance", constants.WHITE_BALANCE_MAP),
            ("picture_style", constants.PICTURE_STYLE_MAP),
            ("evf_af_mode", constants.EVF_AF_MODE_MAP),
            ("af_mode", constants.AF_MODE_MAP),
            ("subject_tracking", constants.AF_TRACKING_OBJECT_MAP),
            ("evf_view_type", constants.EVF_VIEW_TYPE_MAP),
            ("color_space", constants.COLOR_SPACE_MAP),
        ):
            with self.subTest(field=field):
                options = self.config[f"_{field}_options"]
                self.assertTrue(options)
                for option in options:
                    self.assertIn(option, mapping)
                self.assertIn(self.config[field], options)

    def test_numeric_ranges_are_mirrored_in_the_config(self):
        for field, (minimum, maximum, step) in \
                constants.CAMERA_NUMERIC_RANGES.items():
            with self.subTest(field=field):
                published = self.config[f"_{field}_range"]
                expected = [minimum, maximum] if step is None \
                    else [minimum, maximum, step]
                self.assertEqual(published, expected)
                self.assertIsNone(
                    constants.numeric_range_error(field, self.config[field]))

    def test_every_public_field_has_a_real_value_check(self):
        """No public field may fall back to a bare type check."""
        unchecked = []
        for field, value in self.config.items():
            if field.startswith("_"):
                continue
            if isinstance(value, bool):
                continue  # booleans are fully constrained by their type
            if field in constants.CAMERA_VALUE_RESOLVERS:
                continue
            if field in constants.CAMERA_NUMERIC_RANGES:
                continue
            if isinstance(self.config.get(f"_{field}_options"), list):
                continue
            unchecked.append(field)
        self.assertEqual(unchecked, [])

    def test_every_configured_lighting_preset_can_be_applied(self):
        presets = self.config["_presets"]
        self.assertTrue(presets)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config_camera.json"
            for name in presets:
                with self.subTest(preset=name):
                    path.write_text(
                        json.dumps(self.config, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    label, _changes, hint = apply_camera_preset(name, path)
                    self.assertTrue(label)
                    self.assertIsInstance(hint, str)


class ResolveCameraValueTests(unittest.TestCase):
    def test_resolve_av_accepts_equivalent_spellings(self):
        for value in ("5.6", " 5.6 ", 5.6, "f/5.6", "F5.6"):
            with self.subTest(value=value):
                self.assertEqual(constants.resolve_av(value), ("5.6", 0x30))
        # "4" and "4.0" are the same stop; the canonical key wins.
        self.assertEqual(constants.resolve_av("4"), ("4.0", 0x28))
        self.assertEqual(constants.resolve_av("16"), ("16", 0x48))

    def test_resolve_av_rejects_values_outside_the_map(self):
        for value in ("1.9", "23", "", "auto", None, True, "abc"):
            with self.subTest(value=value):
                self.assertIsNone(constants.resolve_av(value))

    def test_resolve_tv_accepts_fractions_and_seconds(self):
        self.assertEqual(constants.resolve_tv("1/200"), ("1/200", 0x75))
        self.assertEqual(constants.resolve_tv(0.005), ("1/200", 0x75))
        self.assertEqual(constants.resolve_tv("1"), ("1", 0x38))
        self.assertEqual(constants.resolve_tv("0.5"), ("0.5", 0x40))
        self.assertEqual(constants.resolve_tv("1/2"), ("0.5", 0x40))

    def test_resolve_tv_rejects_unsupported_and_malformed(self):
        for value in ("1/90", "1/0", "1/", "/200", "", None, True, "fast"):
            with self.subTest(value=value):
                self.assertIsNone(constants.resolve_tv(value))

    def test_resolve_iso_normalises_telegram_strings_to_int(self):
        self.assertEqual(constants.resolve_iso("100"), (100, 0x48))
        self.assertEqual(constants.resolve_iso(" 100 "), (100, 0x48))
        self.assertEqual(constants.resolve_iso(100), (100, 0x48))
        self.assertEqual(constants.resolve_iso(100.0), (100, 0x48))
        self.assertIs(type(constants.resolve_iso("100")[0]), int)

    def test_resolve_iso_falls_back_to_auto_only_for_the_auto_keyword(self):
        for value in ("auto", "AUTO", " Auto "):
            with self.subTest(value=value):
                self.assertEqual(constants.resolve_iso(value), ("auto", 0x00))
        for value in ("150", "0", "", "high", None, True, 100.5):
            with self.subTest(value=value):
                self.assertIsNone(constants.resolve_iso(value))

    def test_resolved_code_returns_none_for_unsupported_values(self):
        self.assertEqual(
            constants.resolved_code(constants.resolve_iso, "200"), 0x50)
        self.assertIsNone(
            constants.resolved_code(constants.resolve_iso, "150"))


class NumericRangeTests(unittest.TestCase):
    def test_color_temperature_honours_bounds_and_step(self):
        self.assertIsNone(
            constants.numeric_range_error("color_temperature", 5200))
        self.assertIsNone(
            constants.numeric_range_error("color_temperature", 2500))
        self.assertIsNone(
            constants.numeric_range_error("color_temperature", 10000))
        self.assertIn(
            "диапазон",
            constants.numeric_range_error("color_temperature", 2400))
        self.assertIn(
            "диапазон",
            constants.numeric_range_error("color_temperature", 99999))
        self.assertIn(
            "шаг", constants.numeric_range_error("color_temperature", 5250))

    def test_focus_delay_and_disk_guard_reject_negative_values(self):
        self.assertIsNone(constants.numeric_range_error("focus_delay", 0.0))
        self.assertIsNone(constants.numeric_range_error("focus_delay", 5.0))
        self.assertIn(
            "диапазон", constants.numeric_range_error("focus_delay", -0.1))
        self.assertIn(
            "диапазон", constants.numeric_range_error("focus_delay", 999999))
        self.assertIn(
            "диапазон",
            constants.numeric_range_error("min_free_disk_gib", 0.1))

    def test_unbounded_field_has_no_range_error(self):
        self.assertIsNone(constants.numeric_range_error("focus_before_capture", 1))
        self.assertIsNone(constants.numeric_range_error("unknown_field", 42))


class TelegramNumericAndBooleanFieldTests(unittest.TestCase):
    """Every non-map field must survive an unexpected Telegram spelling."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temporary.name) / "config_camera.json"
        self.base = {
            "color_temperature": 5200,
            "focus_delay": 0.4,
            "min_free_disk_gib": 2.0,
            "continuous_af": True,
            "lock_camera_ui": True,
        }
        self._write()

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self):
        self.config_path.write_text(json.dumps(self.base), encoding="utf-8")

    def _read(self):
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def test_accepted_numeric_spellings_keep_the_field_type(self):
        for field, value, expected in (
            ("color_temperature", "6000", 6000),
            ("color_temperature", " 6000 ", 6000),
            ("color_temperature", "+6000", 6000),
            ("focus_delay", "1", 1.0),
            ("focus_delay", "0.75", 0.75),
            ("focus_delay", "1e0", 1.0),
            ("min_free_disk_gib", "5", 5.0),
        ):
            with self.subTest(field=field, value=value):
                self._write()
                _, _, new_value, _ = update_camera_config_field(
                    field, value, self.config_path)
                self.assertEqual(new_value, expected)
                self.assertIs(type(new_value), type(self.base[field]))

    def test_out_of_range_and_malformed_numbers_are_rejected(self):
        for field, value in (
            ("color_temperature", "99999"),
            ("color_temperature", "-100"),
            ("color_temperature", "0"),
            ("color_temperature", "5250"),
            ("color_temperature", "5200.5"),
            ("focus_delay", "-5"),
            ("focus_delay", "999999"),
            ("focus_delay", "0,4"),
            ("focus_delay", "nan"),
            ("focus_delay", "1e400"),
            ("min_free_disk_gib", "0"),
            ("min_free_disk_gib", "-3"),
            ("min_free_disk_gib", "много"),
        ):
            with self.subTest(field=field, value=value):
                before = self.config_path.read_bytes()
                with self.assertRaises(ValueError):
                    update_camera_config_field(field, value, self.config_path)
                self.assertEqual(self.config_path.read_bytes(), before)

    def test_boolean_accepts_common_spellings_in_both_languages(self):
        for value, expected in (
            ("true", True), ("false", False), ("TRUE", True),
            ("yes", True), ("no", False), ("on", True), ("off", False),
            ("1", True), ("0", False), ("да", True), ("нет", False),
            ("вкл", True), ("выкл", False), (" true ", True),
        ):
            with self.subTest(value=value):
                self._write()
                _, _, new_value, _ = update_camera_config_field(
                    "continuous_af", value, self.config_path)
                self.assertIs(new_value, expected)

    def test_boolean_rejects_anything_ambiguous(self):
        for value in ("2", "-1", "maybe", "", "0.0", "нету"):
            with self.subTest(value=value):
                before = self.config_path.read_bytes()
                with self.assertRaisesRegex(ValueError, "boolean"):
                    update_camera_config_field(
                        "continuous_af", value, self.config_path)
                self.assertEqual(self.config_path.read_bytes(), before)


class CameraConfigReportTests(unittest.TestCase):
    """The readback report must cover every mappable camera-side field."""

    def _camera(self, overrides: dict | None = None,
                actual_overrides: dict | None = None):
        config = json.loads(
            (ROOT_DIR / "config_camera.json").read_text(encoding="utf-8"))
        config.update(overrides or {})
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._cfg = config
        codes = {
            prop_id: camera._requested_code(field, default, mapping)
            for _, prop_id, field, default, mapping in camera._CONFIG_READBACK
        }
        codes.update(actual_overrides or {})
        return camera, codes

    def _report(self, overrides=None, actual_overrides=None):
        camera, codes = self._camera(overrides, actual_overrides)
        with patch.object(camera, "_get_prop_u32",
                          side_effect=lambda prop_id: codes.get(prop_id)):
            return camera.build_config_report()

    def test_every_mappable_field_is_read_back(self):
        config = json.loads(
            (ROOT_DIR / "config_camera.json").read_text(encoding="utf-8"))
        reported = {entry["field"] for entry in self._report()["camera"]}
        reported |= {entry["field"] for entry in self._report()["host"]}
        # color_temperature only applies when white_balance is color_temp.
        reported.add("color_temperature")
        public = {field for field in config if not field.startswith("_")}
        self.assertEqual(public - reported, set())

    def test_matching_camera_values_report_no_problems(self):
        report = self._report()
        self.assertEqual(report["mismatched"], [])
        self.assertEqual(report["unavailable"], [])
        self.assertTrue(all(entry["matches"] for entry in report["camera"]))

    def test_mismatch_and_unavailable_are_reported_separately(self):
        camera, codes = self._camera()
        codes[edsdk.kEdsPropID_Av] = next(
            code for code in edsdk.AV_MAP.values()
            if code != codes[edsdk.kEdsPropID_Av]
        )
        codes[edsdk.kEdsPropID_ImageQuality] = None
        with patch.object(
            camera,
            "_get_prop_u32",
            side_effect=lambda prop_id: codes.get(prop_id),
        ):
            report = camera.build_config_report()

        self.assertEqual(report["mismatched"], ["Av"])
        self.assertEqual(report["unavailable"], ["ImageQuality"])
        entry = next(e for e in report["camera"] if e["label"] == "Av")
        self.assertTrue(entry["available"])
        self.assertFalse(entry["matches"])

    def test_color_temperature_only_appears_for_color_temp_white_balance(self):
        other_white_balance = next(
            value for value in constants.WHITE_BALANCE_MAP
            if value != "color_temp"
        )
        labels = [
            entry["label"]
            for entry in self._report(overrides={
                "white_balance": other_white_balance,
            })["camera"]
        ]
        self.assertNotIn("ColorTemperature", labels)

        report = self._report(overrides={"white_balance": "color_temp"})
        entry = next(e for e in report["camera"]
                     if e["label"] == "ColorTemperature")
        self.assertTrue(entry["available"])
        self.assertTrue(entry["matches"])

    def test_report_is_stored_in_the_health_snapshot(self):
        camera, codes = self._camera()
        with patch.object(camera, "_get_prop_u32",
                          side_effect=lambda prop_id: codes.get(prop_id)), \
                self.assertLogs(edsdk.log, level="INFO") as logs:
            camera._log_applied_config()

        snapshot = camera.status_snapshot()
        self.assertIn("config_report", snapshot)
        self.assertTrue(snapshot["config_report_at"])
        joined = "\n".join(logs.output)
        self.assertIn("Camera applied config:", joined)
        self.assertIn("Camera host config:", joined)
        for entry in snapshot["config_report"]["camera"]:
            self.assertIn(f"{entry['label']}={entry['actual']}", joined)
        for entry in snapshot["config_report"]["host"]:
            self.assertIn(f"{entry['label']}={entry['value']!r}", joined)

    def test_mismatch_is_logged_as_a_warning(self):
        camera, codes = self._camera()
        codes[edsdk.kEdsPropID_Av] = next(
            code for code in edsdk.AV_MAP.values()
            if code != codes[edsdk.kEdsPropID_Av]
        )
        with patch.object(camera, "_get_prop_u32",
                          side_effect=lambda prop_id: codes.get(prop_id)), \
                self.assertLogs(edsdk.log, level="WARNING") as logs:
            camera._log_applied_config()
        self.assertTrue(
            any("Camera config mismatch Av" in line for line in logs.output),
            msg=logs.output)


class CameraConfigReportDeliveryTests(unittest.IsolatedAsyncioTestCase):
    """The applied config must reach the administrator on every launch."""

    def setUp(self):
        self.report = {
            "camera": [
                {"label": "ISO", "field": "iso", "requested": 100,
                 "actual": "100", "available": True, "verifiable": True,
                 "matches": True},
                {"label": "Av", "field": "av", "requested": "16",
                 "actual": "5.6", "available": True, "verifiable": True,
                 "matches": False},
                {"label": "ImageQuality", "field": "image_quality",
                 "requested": "jpeg_large_fine", "actual": "unavailable",
                 "available": False, "verifiable": True, "matches": False},
            ],
            "host": [{"label": "FocusDelay", "field": "focus_delay",
                      "value": 0.4}],
            "mismatched": ["Av"],
            "unavailable": ["ImageQuality"],
        }
        self.snapshot = {
            "config_report": self.report,
            "config_report_at": "2026-08-09T11:00:00+00:00",
            "product_name": "Canon EOS R8",
            "lens": "RF24-50mm",
        }

    def test_report_text_lists_matches_mismatches_and_gaps(self):
        fake_camera = MagicMock()
        fake_camera.status_snapshot.return_value = self.snapshot
        with patch.object(main, "camera", fake_camera):
            text = main._camera_config_report_text()

        self.assertIn("Canon EOS R8", text)
        self.assertIn("RF24-50mm", text)
        self.assertIn("✓ ISO=100", text)
        self.assertIn("✗ Av=5.6 (в конфиге '16')", text)
        self.assertIn("? ImageQuality=unavailable", text)
        self.assertIn("НЕ ПРИМЕНИЛОСЬ: Av", text)
        self.assertIn("Камера не сообщила: ImageQuality", text)
        self.assertIn("FocusDelay=0.4", text)

    def test_clean_report_states_that_everything_applied(self):
        clean = {
            "camera": [{"label": "ISO", "field": "iso", "requested": 100,
                        "actual": "100", "available": True,
                        "verifiable": True, "matches": True}],
            "host": [],
            "mismatched": [],
            "unavailable": [],
        }
        fake_camera = MagicMock()
        fake_camera.status_snapshot.return_value = {"config_report": clean}
        with patch.object(main, "camera", fake_camera):
            text = main._camera_config_report_text()
        self.assertIn("без расхождений", text)

    async def test_notice_is_published_on_every_camera_setup(self):
        fake_camera = MagicMock()
        fake_camera.status_snapshot.return_value = self.snapshot
        with patch.object(main, "camera", fake_camera), \
             patch("backend.main.yadisk_control.publish_booth_notice",
                   new_callable=AsyncMock) as publish:
            await main._report_camera_config_to_admin()
            # A USB reconnect reconfigures the camera and reports again.
            await main._report_camera_config_to_admin()

        self.assertEqual(publish.await_count, 2)
        kind, title, text = publish.await_args.args
        self.assertEqual(kind, "camera_config")
        self.assertIn("Камера настроена и готова", text)

    async def test_delivery_failure_does_not_break_the_booth(self):
        fake_camera = MagicMock()
        fake_camera.status_snapshot.return_value = self.snapshot
        with patch.object(main, "camera", fake_camera), \
             patch("backend.main.yadisk_control.publish_booth_notice",
                   new_callable=AsyncMock,
                   side_effect=RuntimeError("disk down")) as publish:
            await main._report_camera_config_to_admin()
            await main._report_camera_config_to_admin()

        self.assertEqual(publish.await_count, 2)

    async def test_missing_camera_does_not_publish_anything(self):
        with patch.object(main, "camera", None), \
             patch("backend.main.yadisk_control.publish_booth_notice",
                   new_callable=AsyncMock) as publish:
            await main._report_camera_config_to_admin()
        publish.assert_not_awaited()

    async def test_status_command_includes_the_applied_config(self):
        fake_camera = MagicMock()
        fake_camera.is_connected = True
        fake_camera.status_snapshot.return_value = self.snapshot
        with patch.object(main, "camera", fake_camera), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "CONFIG", {"yadisk_folder": "event"}), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="event"), \
             patch("backend.main.yadisk_cloud.pending_count", return_value=0):
            result = await main.handle_disk_command({
                "command_id": "a" * 32,
                "command": "status",
                "data": None,
            })

        self.assertEqual(result["status"], "ok")
        self.assertIn("Applied config", result["message"])
        self.assertIn("✓ ISO=100", result["message"])
        self.assertIn("НЕ ПРИМЕНИЛОСЬ: Av", result["message"])


class TelegramCameraFieldUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temporary.name) / "config_camera.json"
        self.config_path.write_text(json.dumps({
            "av": "16",
            "tv": "1/200",
            "iso": 100,
            "_iso_options": [100, 200, "auto"],
        }), encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def _read(self):
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def test_iso_is_stored_as_int_and_auto_as_string(self):
        # Telegram always delivers "/iso 800" as the string "800".
        self.assertEqual(
            update_camera_config_field("iso", "800", self.config_path),
            ("iso", 100, 800, True))
        self.assertIs(type(self._read()["iso"]), int)

        self.assertEqual(
            update_camera_config_field("iso", "AUTO", self.config_path),
            ("iso", 800, "auto", True))
        self.assertEqual(self._read()["iso"], "auto")

    def test_iso_ignores_the_shorter_legacy_options_list(self):
        # 160 is a valid EDSDK ISO but is absent from _iso_options.
        update_camera_config_field("iso", "160", self.config_path)
        self.assertEqual(self._read()["iso"], 160)

    def test_av_and_tv_are_stored_in_canonical_map_spelling(self):
        update_camera_config_field("av", "4", self.config_path)
        update_camera_config_field("tv", "1/160", self.config_path)
        config = self._read()
        self.assertEqual(config["av"], "4.0")
        self.assertEqual(config["tv"], "1/160")

    def test_unsupported_av_tv_iso_is_rejected_without_writing(self):
        before = self.config_path.read_bytes()
        for field, value in (
            ("av", "1.9"),
            ("av", "wide"),
            ("tv", "1/90"),
            ("tv", "fast"),
            ("iso", "150"),
            ("iso", "on"),
        ):
            with self.subTest(field=field, value=value), \
                    self.assertRaisesRegex(ValueError, "доступно"):
                update_camera_config_field(field, value, self.config_path)
            self.assertEqual(self.config_path.read_bytes(), before)

    def test_equivalent_value_does_not_rewrite_the_file(self):
        before = self.config_path.read_bytes()
        result = update_camera_config_field("av", "16", self.config_path)
        self.assertEqual(result, ("av", "16", "16", False))
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_json_number_from_vps_is_accepted_like_a_string(self):
        self.assertEqual(
            update_camera_config_field("iso", 400, self.config_path),
            ("iso", 100, 400, True))
        self.assertIs(type(self._read()["iso"]), int)


class CameraPresetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temporary.name) / "config_camera.json"
        self.config = {
            "_presets": {
                "bright": {
                    "_label": "Ярко",
                    "_hint": "1/16",
                    "av": "8",
                    "tv": "1/160",
                    "iso": 200,
                },
                "already": {
                    "_label": "Без изменений",
                    "av": "16",
                    "tv": "1/200",
                    "iso": 100,
                },
            },
            "av": "16",
            "tv": "1/200",
            "iso": 100,
        }
        self._write()

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self):
        self.config_path.write_text(
            json.dumps(self.config, ensure_ascii=False),
            encoding="utf-8",
        )

    def _read(self):
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def test_lists_and_applies_a_preset_in_one_write(self):
        self.assertEqual(
            preset_names(self.config_path),
            ["bright", "already"],
        )

        label, changes, hint = apply_camera_preset(
            " BRIGHT ", self.config_path)

        self.assertEqual(label, "Ярко")
        self.assertEqual(hint, "1/16")
        self.assertEqual(changes, {
            "av": ("16", "8.0"),
            "tv": ("1/200", "1/160"),
            "iso": (100, 200),
        })
        saved = self._read()
        self.assertEqual(
            {field: saved[field] for field in ("av", "tv", "iso")},
            {"av": "8.0", "tv": "1/160", "iso": 200},
        )
        self.assertEqual(saved["_presets"], self.config["_presets"])

    def test_invalid_field_keeps_the_whole_file_unchanged(self):
        self.config["_presets"]["broken"] = {
            "av": "8.0",
            "iso": 150,
        }
        self._write()
        before = self.config_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "доступно"):
            apply_camera_preset("broken", self.config_path)

        self.assertEqual(self.config_path.read_bytes(), before)

    def test_unknown_preset_lists_available_names_without_writing(self):
        before = self.config_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "already, bright"):
            apply_camera_preset("missing", self.config_path)
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_already_applied_preset_does_not_rewrite_the_file(self):
        before = self.config_path.read_bytes()
        result = apply_camera_preset("already", self.config_path)
        self.assertEqual(result, ("Без изменений", {}, ""))
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_malformed_preset_container_and_name_are_rejected(self):
        self.config["_presets"] = []
        self._write()
        with self.assertRaisesRegex(ValueError, "JSON-объект"):
            preset_names(self.config_path)

        self.config["_presets"] = {"bad-name": {"iso": 200}}
        self._write()
        with self.assertRaisesRegex(ValueError, "имя пресета"):
            preset_names(self.config_path)


class CameraAppliesConfigValuesTests(unittest.TestCase):
    """The EDSDK layer must apply every stored value or log a hard error."""

    def _configure(self, config: dict):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._camera = ctypes.c_void_p(123)
        camera._sdk = MagicMock()
        camera._sdk.EdsSendCommand.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetCapacity.return_value = edsdk.EDS_ERR_OK

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "config_camera.json").write_text(
                json.dumps(config), encoding="utf-8")
            with patch("backend.config.ROOT_DIR", Path(tmpdir)), \
                 patch.object(camera, "storage_ready", return_value=(True, "")), \
                 patch.object(camera, "_configure_ae_mode"), \
                 patch.object(camera, "_set_prop_u32",
                              return_value=edsdk.EDS_ERR_OK) as set_prop, \
                 patch.object(camera, "_read_camera_identity"), \
                 patch.object(camera, "_log_applied_config"), \
                 patch.object(camera, "_log_camera_health"), \
                 patch.object(edsdk.shutil, "disk_usage",
                              return_value=SimpleNamespace(free=10 * 1024 ** 3)), \
                 self.assertLogs(edsdk.log, level="INFO") as logs:
                camera._configure_for_photobooth()

        applied = {
            call.args[0]: call.args[1] for call in set_prop.call_args_list
            if len(call.args) >= 2
        }
        return applied, logs.output

    def test_string_iso_from_an_older_config_still_reaches_the_camera(self):
        applied, _ = self._configure({
            "av": "16",
            "tv": "1/200",
            "iso": "100",
            "disable_auto_power_off": False,
            "lock_camera_ui": False,
            "lock_mode_dial": False,
        })
        self.assertEqual(applied[edsdk.kEdsPropID_Av], 0x48)
        self.assertEqual(applied[edsdk.kEdsPropID_Tv], 0x75)
        self.assertEqual(applied[edsdk.kEdsPropID_ISOSpeed], 0x48)

    def test_iso_auto_is_applied_as_zero(self):
        applied, _ = self._configure({
            "iso": "auto",
            "disable_auto_power_off": False,
            "lock_camera_ui": False,
            "lock_mode_dial": False,
        })
        self.assertEqual(applied[edsdk.kEdsPropID_ISOSpeed], 0x00)

    def test_unsupported_value_is_logged_and_not_silently_skipped(self):
        applied, output = self._configure({
            "av": "1.9",
            "tv": "1/90",
            "iso": 150,
            "disable_auto_power_off": False,
            "lock_camera_ui": False,
            "lock_mode_dial": False,
        })
        self.assertNotIn(edsdk.kEdsPropID_Av, applied)
        self.assertNotIn(edsdk.kEdsPropID_Tv, applied)
        self.assertNotIn(edsdk.kEdsPropID_ISOSpeed, applied)
        errors = [line for line in output if line.startswith("ERROR")]
        self.assertEqual(len(errors), 3)
        for label in ("av", "tv", "iso"):
            self.assertTrue(
                any(f"Unsupported {label}=" in line for line in errors),
                msg=f"missing error for {label}: {errors}")

    def test_unknown_named_value_is_not_replaced_by_the_default(self):
        applied, output = self._configure({
            "white_balance": "sunset",
            "picture_style": "vivid",
            "disable_auto_power_off": False,
            "lock_camera_ui": False,
            "lock_mode_dial": False,
        })
        self.assertNotIn(edsdk.kEdsPropID_WhiteBalance, applied)
        self.assertNotIn(edsdk.kEdsPropID_PictureStyle, applied)
        errors = [line for line in output if line.startswith("ERROR")]
        self.assertEqual(len(errors), 2)
        self.assertTrue(
            any("Unsupported white_balance='sunset'" in line for line in errors),
            msg=errors)

    def test_missing_fields_fall_back_to_the_documented_defaults(self):
        applied, output = self._configure({
            "disable_auto_power_off": False,
            "lock_camera_ui": False,
            "lock_mode_dial": False,
        })
        self.assertEqual(
            applied[edsdk.kEdsPropID_WhiteBalance],
            edsdk.WHITE_BALANCE_MAP["auto"])
        self.assertEqual(applied[edsdk.kEdsPropID_Av], 0x30)      # f/5.6
        self.assertEqual(applied[edsdk.kEdsPropID_Tv], 0x70)      # 1/125
        self.assertEqual(applied[edsdk.kEdsPropID_ISOSpeed], 0x58)  # ISO 400
        self.assertEqual(
            [line for line in output if line.startswith("ERROR")], [])

    def test_hand_edited_color_temperature_is_clamped_and_logged(self):
        applied, output = self._configure({
            "white_balance": "color_temp",
            "color_temperature": 99999,
            "disable_auto_power_off": False,
            "lock_camera_ui": False,
            "lock_mode_dial": False,
        })
        self.assertEqual(applied[edsdk.kEdsPropID_ColorTemperature], 10000)
        self.assertTrue(
            any("Out-of-range color_temperature" in line for line in output),
            msg=output)


class NumericRuntimeGuardTests(unittest.TestCase):
    """A hand-edited config must not be able to stall the camera worker."""

    def _camera(self, cfg: dict):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._cfg = cfg
        return camera

    def test_focus_delay_is_clamped_before_the_worker_waits(self):
        camera = self._camera({"focus_delay": 999999})
        with self.assertLogs(edsdk.log, level="ERROR"):
            self.assertEqual(
                camera._numeric_config_value(camera._cfg, "focus_delay", 0.4),
                5.0)

        camera = self._camera({"focus_delay": -5})
        with self.assertLogs(edsdk.log, level="ERROR"):
            self.assertEqual(
                camera._numeric_config_value(camera._cfg, "focus_delay", 0.4),
                0.0)

    def test_unparsable_number_uses_the_default(self):
        camera = self._camera({"focus_delay": "почти сразу"})
        with self.assertLogs(edsdk.log, level="ERROR"):
            self.assertEqual(
                camera._numeric_config_value(camera._cfg, "focus_delay", 0.4),
                0.4)

    def test_disk_guard_never_drops_below_the_documented_minimum(self):
        camera = self._camera({"min_free_disk_gib": -3})
        with self.assertLogs(edsdk.log, level="ERROR"):
            self.assertEqual(
                camera._minimum_free_disk_bytes(), int(0.25 * 1024 ** 3))

        camera = self._camera({"min_free_disk_gib": 2.0})
        self.assertEqual(camera._minimum_free_disk_bytes(), 2 * 1024 ** 3)

    def test_valid_value_is_used_verbatim_without_logging(self):
        camera = self._camera({"focus_delay": 0.75})
        self.assertEqual(
            camera._numeric_config_value(camera._cfg, "focus_delay", 0.4), 0.75)


if __name__ == "__main__":
    unittest.main()
