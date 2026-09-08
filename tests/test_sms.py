import json
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from backend import sms, yadisk_control


class SmsForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.read = False
        self.reject_mark = False
        self.sms_text = "Проверка: <код> & кириллица 📩"
        self.posts = []
        app = web.Application()
        app.router.add_route("*", "/api/{path:.*}", self.modem_api)
        self.server = TestServer(app)
        await self.server.start_server()
        self.session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
        self.modem = sms.Modem(self.session, str(self.server.make_url("")))

    async def asyncTearDown(self):
        await self.session.close()
        await self.server.close()

    async def modem_api(self, request):
        if request.path == "/api/webserver/SesTokInfo":
            return web.Response(text="<response><SesInfo>SessionID=session-one</SesInfo>"
                                     "<TokInfo>login-token</TokInfo></response>")
        self.assertEqual(request.headers.get("Cookie"), "SessionID=session-one")
        if request.path == "/api/webserver/token":
            return web.Response(text=f'<response><token>{"0" * 32}{"t" * 32}</token></response>')
        headers = dict(request.raw_headers)
        self.assertEqual(headers[b"__RequestVerificationToken"], b"t" * 32)
        self.assertEqual(headers[b"_ResponseSource"], b"Broswer")
        self.posts.append(request.path)
        if request.path == "/api/sms/set-read":
            body = sms.ET.fromstring(await request.text())
            self.assertEqual(body.findtext("Index"), "7")
            if self.reject_mark:
                return web.Response(text="<error><code>125003</code></error>")
            self.read = True
            return web.Response(text="<response>OK</response>")
        self.assertEqual(request.path, "/api/sms/sms-list")
        root = sms.ET.Element("response")
        messages = sms.ET.SubElement(root, "Messages")
        message = sms.ET.SubElement(messages, "Message")
        for key, value in {
            "Index": "7", "Smstat": "1" if self.read else "0", "Phone": "Test sender",
            "Date": "2026-09-08 15:00:00", "Content": self.sms_text,
        }.items():
            sms.ET.SubElement(message, key).text = value
        return web.Response(body=sms.ET.tostring(root, encoding="utf-8"))

    async def test_upload_failure_keeps_sms_unread_then_retries(self):
        with patch.object(yadisk_control, "publish_booth_notice", AsyncMock(
            side_effect=RuntimeError("Disk unavailable"),
        )) as publish:
            with self.assertRaisesRegex(RuntimeError, "Disk unavailable"):
                await self.modem.forward_unread()
            first_id = publish.await_args.kwargs["notice_id"]
        self.assertFalse(self.read)
        self.assertNotIn("/api/sms/set-read", self.posts)

        with patch.object(yadisk_control, "publish_booth_notice", AsyncMock()) as publish:
            await self.modem.forward_unread()
            self.assertTrue(self.read)
            self.assertEqual(publish.await_args.kwargs["notice_id"], first_id)
            self.assertTrue(publish.await_args.args[2].endswith(self.sms_text))
            await self.modem.forward_unread()
            publish.assert_awaited_once()

    async def test_failed_mark_read_and_restart_reuse_the_same_disk_file(self):
        self.reject_mark = True
        uploads = []

        async def upload(body, path):
            self.assertFalse(self.read)
            uploads.append((json.loads(body), path))

        with patch.object(yadisk_control, "_root", "/control"), \
             patch.object(yadisk_control, "_connect", AsyncMock(return_value=True)), \
             patch.object(yadisk_control, "_upload_bytes", AsyncMock(side_effect=upload)), \
             patch.object(yadisk_control, "_prune_booth_notices", AsyncMock()) as prune:
            with self.assertRaisesRegex(RuntimeError, "125003"):
                await self.modem.forward_unread()
            self.modem = sms.Modem(self.session, self.modem.url)
            self.reject_mark = False
            await self.modem.forward_unread()
            prune.assert_not_awaited()
        self.assertTrue(self.read)
        self.assertEqual(uploads[0][1], uploads[1][1])
        self.assertEqual(uploads[0][0]["notice_id"], uploads[1][0]["notice_id"])
        self.assertTrue(uploads[0][1].endswith(f'/notice_{uploads[0][0]["notice_id"]}.json'))

    async def test_long_sms_is_delivered_in_parts_without_losing_text(self):
        self.sms_text *= yadisk_control.MAX_BOOTH_NOTICE_TEXT // len(self.sms_text) + 1
        with patch.object(yadisk_control, "publish_booth_notice", AsyncMock()) as publish:
            await self.modem.forward_unread()
        calls = publish.await_args_list
        self.assertGreater(len(calls), 1)
        self.assertEqual("".join(call.args[2].split("\n\n", 1)[1] for call in calls), self.sms_text)
        self.assertTrue(all(len(call.args[2]) <= yadisk_control.MAX_BOOTH_NOTICE_TEXT for call in calls))
        self.assertEqual(len({call.kwargs["notice_id"] for call in calls}), len(calls))
        self.assertTrue(self.read)
