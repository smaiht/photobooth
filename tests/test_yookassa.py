import asyncio
import copy
import io
import json
import tempfile
import time
import unittest
import urllib.request
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend import yookassa


class CredentialsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / yookassa.CACHE_FILENAME
        self.old = {"SHOPID": "old-shop", "SHOPTOKEN": "old-secret"}
        self.new = {"SHOPID": "new-shop", "SHOPTOKEN": "new-secret"}
        self.cache.write_text(json.dumps(self.old), encoding="utf-8")
        environment = patch.dict("os.environ", {"YADISK_TOKEN": "disk-token"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_refresh_replaces_cache_and_next_offline_start_uses_it(self):
        with patch.object(yookassa, "_download_credentials",
                          return_value=json.dumps(self.new).encode()):
            self.assertEqual(yookassa.load_credentials(self.root), self.new)

        with patch.object(yookassa, "_download_credentials",
                          side_effect=TimeoutError), \
                self.assertLogs(yookassa.log, level="WARNING"):
            self.assertEqual(yookassa.load_credentials(self.root), self.new)

    def test_credentials_are_read_from_the_shared_configs_folder(self):
        # The folder ZIP will later hold the app and camera configs too.
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as folder:
            folder.writestr("configs/config_app.json", '{"print_enabled": true}')
            folder.writestr(f"configs/{yookassa.REMOTE_FILENAME}",
                            json.dumps(self.new))
        with patch.object(yookassa.yadisk_updates, "_download_link",
                          return_value="https://storage.test/configs.zip"), \
                patch.object(urllib.request, "urlopen",
                             return_value=io.BytesIO(archive.getvalue())):
            self.assertEqual(yookassa.load_credentials(self.root), self.new)

    def test_invalid_remote_file_does_not_replace_valid_cache(self):
        original = self.cache.read_bytes()
        for payload in (b"not json", b'{"SHOPID": "new-shop"}'):
            with self.subTest(payload=payload), \
                    patch.object(yookassa, "_download_credentials",
                                 return_value=payload), \
                    self.assertLogs(yookassa.log, level="WARNING"):
                self.assertEqual(yookassa.load_credentials(self.root), self.old)
                self.assertEqual(self.cache.read_bytes(), original)

    def test_failed_cache_write_still_returns_fresh_credentials(self):
        with patch.object(yookassa, "_download_credentials",
                          return_value=json.dumps(self.new).encode()), \
                patch.object(yookassa, "_save_credentials",
                             side_effect=OSError), \
                self.assertLogs(yookassa.log, level="WARNING"):
            self.assertEqual(yookassa.load_credentials(self.root), self.new)
        self.assertEqual(json.loads(self.cache.read_text()), self.old)

    def test_no_cache_and_failed_download_leave_credentials_unavailable(self):
        self.cache.unlink()
        secret_url = "https://storage.example/private-signed-download"
        with patch.object(yookassa, "_download_credentials",
                          side_effect=RuntimeError(secret_url)), \
                self.assertLogs(yookassa.log, level="WARNING") as logs:
            self.assertIsNone(yookassa.load_credentials(self.root))
        self.assertNotIn(secret_url, "\n".join(logs.output))


def _attempt(**overrides) -> dict:
    attempt = {
        "request_id": "1e4f9a1c-0000-4000-8000-000000000001",
        "created_at": time.time(),
        "shop_id": "shop-1",
        "event": "Кафе",
        "status": "creating",
        "request": {
            "amount": {"value": "100.00", "currency": "RUB"},
            "payment_method_data": {"type": "sbp"},
            "confirmation": {"type": "qr"},
            "capture": True,
            "description": "Покупка одной фотосессии",
            "metadata": {"request_id": "1e4f9a1c-0000-4000-8000-000000000001"},
        },
    }
    attempt.update(overrides)
    return attempt


def _response(**overrides) -> dict:
    response = {
        "id": "2f0a1b2c-000f-5000-a000-000000000009",
        "status": "pending",
        "paid": False,
        "amount": {"value": "100.00", "currency": "RUB"},
        "recipient": {"account_id": "shop-1", "gateway_id": "2828288"},
        "payment_method": {"type": "sbp", "id": "2f0a1b2c-000f-5000-a000-000000000009"},
        "metadata": {"request_id": "1e4f9a1c-0000-4000-8000-000000000001"},
        "confirmation": {"type": "qr", "confirmation_data": "https://qr.nspk.ru/AS1A0000"},
    }
    response.update(overrides)
    return response


class PaymentResultTests(unittest.TestCase):
    def test_pending_payment_returns_the_sbp_qr(self):
        result = yookassa.payment_result(_response(), _attempt())
        self.assertEqual(result, {
            "id": "2f0a1b2c-000f-5000-a000-000000000009",
            "status": "pending",
            "qr": "https://qr.nspk.ru/AS1A0000",
        })

    def test_succeeded_payment_keeps_only_the_id_and_status(self):
        result = yookassa.payment_result(
            _response(status="succeeded", paid=True), _attempt())
        self.assertEqual(result, {
            "id": "2f0a1b2c-000f-5000-a000-000000000009",
            "status": "succeeded",
        })

    def test_response_that_is_not_this_request_is_rejected(self):
        cases = {
            "another shop": _response(recipient={"account_id": "shop-2"}),
            "another amount": _response(amount={"value": "10.00", "currency": "RUB"}),
            "another request": _response(metadata={"request_id": "other"}),
            "another payment id": _response(id="2f0a1b2c-000f-5000-a000-000000000010"),
            "unpaid success": _response(status="succeeded", paid=False),
            "test payment": _response(status="succeeded", paid=True, test=True),
            "no qr": _response(confirmation={"type": "qr"}),
            "foreign qr": _response(
                confirmation={"type": "qr", "confirmation_data": "https://evil.example/qr"}),
        }
        attempt = _attempt(id="2f0a1b2c-000f-5000-a000-000000000009", status="pending")
        for name, response in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                yookassa.payment_result(response, attempt)


class CafePaymentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payment = _attempt(
            id="2f0a1b2c-000f-5000-a000-000000000009",
            status="pending",
            qr="https://qr.nspk.ru/AS1A0000",
        )

    def _booth(self, remaining=0, payment=None):
        from backend import main
        return (
            patch.object(main, "ROOT_DIR", self.root),
            patch.object(main, "CONFIG", {
                "technical_event_name": "Кафе",
                "yadisk_folder": "Кафе",
                "technical_event_price_rubles": int(float(self.payment["request"]["amount"]["value"])),
            }),
            patch.dict(main.app.state._state, {"yookassa_credentials": {
                "SHOPID": "shop-1", "SHOPTOKEN": "secret"}}),
            patch.object(main, "STATE", "idle"),
            patch.object(main, "_session_running", False),
            patch.object(main, "_cafe_payment", payment or self.payment),
            patch.object(main, "_cafe_unlock_sessions_remaining", remaining),
            patch.object(main, "_payment_notice", ""),
            patch.object(main, "_payment_alert_until", 0.0),
            patch.object(main, "_service_tasks", set()),
            patch.object(yookassa, "PAYMENT_POLL_INTERVAL_SECONDS", 0),
            patch("backend.main.broadcast", new_callable=AsyncMock),
            patch("backend.main.yadisk_cloud.current_event_folder",
                  return_value="Кафе"),
        )

    async def _poll(self, response=None, remaining=0, payment=None):
        from backend import main
        main.app.state.yookassa_credentials = {
            "SHOPID": "shop-1", "SHOPTOKEN": "secret"}
        self.addCleanup(setattr, main.app.state, "yookassa_credentials", None)
        with ExitStack() as stack:
            for context in self._booth(remaining, payment):
                stack.enter_context(context)
            stack.enter_context(patch.object(
                yookassa, "request_payment", AsyncMock(return_value=response)))
            await main._poll_cafe_payment()
            return (main._cafe_unlock_sessions_remaining, main._cafe_payment,
                    main._payment_state())

    def _resumes_polling(self, remaining, payment):
        """Would a restart with this saved state keep watching the payment?"""
        from backend import main
        main.app.state.yookassa_credentials = {
            "SHOPID": "shop-1", "SHOPTOKEN": "secret"}
        self.addCleanup(setattr, main.app.state, "yookassa_credentials", None)
        with ExitStack() as stack:
            for context in self._booth(remaining, payment):
                stack.enter_context(context)
            stack.enter_context(patch.object(main, "_payment_task", None))
            stack.enter_context(patch.object(
                main, "_poll_cafe_payment", AsyncMock()))
            main._ensure_payment_task()
            task = main._payment_task
        return task is not None

    async def test_reboot_resumes_the_saved_payment_and_credits_it_once(self):
        from backend import main
        (self.root / "cafe_unlock_state.json").write_text(
            json.dumps({"remaining_sessions": 1, "payment": self.payment}),
            encoding="utf-8")
        with patch.object(main, "ROOT_DIR", self.root):
            restored_remaining, restored_payment = main._load_cafe_unlock_state()
        self.assertEqual(restored_remaining, 1)
        self.assertEqual(restored_payment, self.payment)
        self.assertTrue(self._resumes_polling(restored_remaining, restored_payment))

        remaining, payment, _ = await self._poll(
            _response(status="succeeded", paid=True), remaining=1)
        self.assertEqual(remaining, 2)
        self.assertTrue(payment["credited"])
        persisted = json.loads(
            (self.root / "cafe_unlock_state.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["remaining_sessions"], 2)
        self.assertEqual(persisted["payment"], payment)

        # The next reboot sees a paid receipt and must not pay out again.
        with patch.object(main, "ROOT_DIR", self.root):
            self.assertEqual(main._load_cafe_unlock_state(), (2, payment))
        self.assertFalse(self._resumes_polling(2, payment))

    async def test_unpaid_canceled_payment_is_forgotten(self):
        remaining, payment, state = await self._poll(_response(status="canceled"))

        self.assertEqual(remaining, 0)
        self.assertIsNone(payment)
        self.assertEqual(state["status"], "idle")
        persisted = json.loads(
            (self.root / "cafe_unlock_state.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted, {"remaining_sessions": 0})

    async def test_bad_creation_response_keeps_the_request_for_review(self):
        # Even without an ID, a bad response does not prove the POST was refused.
        remaining, payment, state = await self._poll(
            payment=_attempt(), response=_response(recipient={"account_id": "shop-2"}))

        self.assertEqual(remaining, 0)
        self.assertEqual(payment["status"], "review")
        self.assertEqual(payment["request_id"], _attempt()["request_id"])
        self.assertEqual(state["status"], "review")

    async def test_foreign_payment_never_credits_a_session(self):
        remaining, payment, state = await self._poll(
            _response(status="succeeded", paid=True,
                      recipient={"account_id": "shop-2"}))

        self.assertEqual(remaining, 0)
        self.assertEqual(payment["status"], "review")
        self.assertNotIn("credited", payment)
        self.assertEqual(state["status"], "review")

    async def test_double_tap_saves_one_request_with_the_configured_price(self):
        from backend import main
        with ExitStack() as stack:
            for context in self._booth():
                stack.enter_context(context)
            stack.enter_context(patch.object(main, "_cafe_payment", None))
            stack.enter_context(patch.object(main, "_ensure_payment_task"))
            configured_price = 237
            main.CONFIG["technical_event_price_rubles"] = configured_price
            await main._start_cafe_payment()
            saved = copy.deepcopy(main._cafe_payment)
            main.CONFIG["technical_event_price_rubles"] += 50
            await main._start_cafe_payment()

            self.assertEqual(main._cafe_payment, saved)
            self.assertEqual(saved["request"]["amount"], {
                "value": f"{configured_price}.00", "currency": "RUB"})
            self.assertEqual(main._load_cafe_unlock_state(), (0, saved))

    async def test_unblock_during_post_keeps_the_request_and_payment_adds_one(self):
        from backend import main
        request = _attempt()
        with ExitStack() as stack:
            for context in self._booth(payment=request):
                stack.enter_context(context)

            async def respond(session, attempt):
                result = await main.handle_disk_command({
                    "command_id": "a" * 32,
                    "command": "unblock", "data": {"sessions": 3}})
                self.assertEqual(result["status"], "ok")
                self.assertIs(main._cafe_payment, attempt)
                self.assertEqual(main._load_cafe_unlock_state(), (3, request))
                return _response(status="succeeded", paid=True)

            stack.enter_context(patch.object(yookassa, "request_payment", side_effect=respond))
            await main._poll_cafe_payment()
            self.assertEqual(main._cafe_unlock_sessions_remaining, 4)
            self.assertTrue(main._cafe_payment["credited"])

    async def test_lost_create_reply_reboots_and_repeats_the_saved_post(self):
        from backend import main
        with ExitStack() as stack:
            for context in self._booth(payment=_attempt()):
                stack.enter_context(context)
            main._save_cafe_payment(main._cafe_payment)
            original = copy.deepcopy(main._cafe_payment)
            with patch.object(yookassa, "request_payment", side_effect=TimeoutError), \
                    patch.object(main.asyncio, "sleep", side_effect=asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):
                    await main._poll_cafe_payment()

            main._cafe_unlock_sessions_remaining, main._cafe_payment = main._load_cafe_unlock_state()
            main.CONFIG["technical_event_price_rubles"] += 50
            with patch.object(yookassa, "request_payment", AsyncMock(
                    return_value=_response(status="succeeded", paid=True))) as request:
                await main._poll_cafe_payment()

            self.assertEqual(request.await_args.args[1], original)
            self.assertEqual(main._cafe_unlock_sessions_remaining, 1)

    async def test_unconfirmed_old_or_undated_post_is_not_recreated(self):
        from backend import main
        expired = time.time() - yookassa.IDEMPOTENCE_TTL_SECONDS - 1
        for created_at in (expired, None):
            with self.subTest(created_at=created_at), ExitStack() as stack:
                for context in self._booth(payment=_attempt(created_at=created_at)):
                    stack.enter_context(context)
                request = stack.enter_context(patch.object(yookassa, "request_payment", AsyncMock()))
                await main._poll_cafe_payment()
                request.assert_not_awaited()
                self.assertEqual(main._cafe_unlock_sessions_remaining, 0)
                self.assertEqual(main._cafe_payment["status"], "review")

    async def test_failed_credit_write_retries_without_unlocking_twice(self):
        from backend import main
        with ExitStack() as stack:
            for context in self._booth():
                stack.enter_context(context)
            main._save_cafe_payment(main._cafe_payment)
            write = main._write_cafe_unlock_sessions
            writes = 0

            def save(remaining, payment):
                nonlocal writes
                writes += 1
                if writes == 1:
                    raise OSError("disk full")
                self.assertTrue(main._start_locked())
                self.assertEqual(main._load_cafe_unlock_state()[0], 0)
                write(remaining, payment)

            stack.enter_context(patch.object(main, "_write_cafe_unlock_sessions", side_effect=save))
            stack.enter_context(patch.object(yookassa, "request_payment", AsyncMock(
                return_value=_response(status="succeeded", paid=True))))
            await main._poll_cafe_payment()
            self.assertEqual(writes, 2)
            self.assertEqual(main._load_cafe_unlock_state()[0], 1)
            self.assertEqual(main._payment_state()["status"], "succeeded")

    async def test_late_response_cannot_be_applied_to_a_replaced_request(self):
        from backend import main
        with ExitStack() as stack:
            for context in self._booth():
                stack.enter_context(context)

            async def respond(session, attempt):
                main._save_cafe_payment(None)
                return _response(status="succeeded", paid=True)

            stack.enter_context(patch.object(yookassa, "request_payment", side_effect=respond))
            await main._poll_cafe_payment()
            self.assertEqual(main._cafe_unlock_sessions_remaining, 0)
            self.assertIsNone(main._cafe_payment)

    async def test_crash_after_credit_file_replace_does_not_credit_again(self):
        from backend import main
        with ExitStack() as stack:
            for context in self._booth():
                stack.enter_context(context)
            write = main._write_cafe_unlock_sessions

            def write_then_crash(remaining, payment):
                write(remaining, payment)
                raise asyncio.CancelledError

            stack.enter_context(patch.object(
                main, "_write_cafe_unlock_sessions", side_effect=write_then_crash))
            request = stack.enter_context(patch.object(yookassa, "request_payment", AsyncMock(
                return_value=_response(status="succeeded", paid=True))))
            with self.assertRaises(asyncio.CancelledError):
                await main._poll_cafe_payment()
            self.assertEqual(main._cafe_unlock_sessions_remaining, 0)

            main._cafe_unlock_sessions_remaining, main._cafe_payment = main._load_cafe_unlock_state()
            await main._poll_cafe_payment()
            request.assert_awaited_once()
            self.assertEqual(main._cafe_unlock_sessions_remaining, 1)
            self.assertTrue(main._cafe_payment["credited"])


if __name__ == "__main__":
    unittest.main()
