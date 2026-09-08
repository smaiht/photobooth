"""Poll BROVI SMS in the background and hand them directly to the VPS bus."""

import asyncio
import base64
import hashlib
import json
import logging
import xml.etree.ElementTree as ET

import aiohttp

from . import yadisk_control

MODEM_URL = "http://192.168.8.1"
USER = "admin"
PASSWORD = ""  # Пароль админки модема; пусто, если вход не нужен.
POLL_INTERVAL = 5

log = logging.getLogger(__name__)
status = "выключено"


def _xml(**fields):
    root = ET.Element("request")
    for name, value in fields.items():
        ET.SubElement(root, name).text = str(value)
    return ET.tostring(root, encoding="unicode")


def _b64_sha256(text):
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest().encode("ascii")
    return base64.b64encode(digest).decode("ascii")


class Modem:
    def __init__(self, session, url, password=""):
        self.session = session
        self.url = url.rstrip("/")
        self.password = password
        self.session_id = ""

    async def api(self, path, xml=None, token=None, referer="/html/home.html"):
        headers = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
        if self.session_id:
            headers["Cookie"] = f"SessionID={self.session_id}"
        if token:
            # BROVI WebUI uses these underscores and the spelling "Broswer".
            headers.update({
                "__RequestVerificationToken": token,
                "_ResponseSource": "Broswer",
                "Origin": self.url,
                "Referer": self.url + referer,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            })
        async with self.session.request(
            "GET" if xml is None else "POST", self.url + path,
            data=xml.encode("utf-8") if xml is not None else None,
            headers=headers, timeout=aiohttp.ClientTimeout(total=8),
        ) as response:
            response.raise_for_status()
            if "SessionID" in response.cookies:
                self.session_id = response.cookies["SessionID"].value
            root = ET.fromstring(await response.read())
        if root.tag == "error":
            raise RuntimeError(f'{path}: ошибка API {root.findtext("code", "unknown")}')
        if root.tag != "response":
            raise RuntimeError(f"{path}: неожиданный ответ модема")
        return root

    async def open_session(self):
        self.session_id = ""
        root = await self.api("/api/webserver/SesTokInfo")
        session = root.findtext("SesInfo")
        token = root.findtext("TokInfo")
        if not session or not token:
            raise RuntimeError("модем не вернул SessionID/TokInfo")
        self.session_id = session.removeprefix("SessionID=").split(";", 1)[0]
        if self.password:
            password_hash = _b64_sha256(USER + _b64_sha256(self.password) + token)
            result = await self.api(
                "/api/user/login",
                _xml(Username=USER, Password=password_hash, password_type=4),
                token,
            )
            if (result.text or "").strip() != "OK":
                raise RuntimeError("модем не принял логин/пароль")

    async def post_sms(self, path, xml):
        root = await self.api("/api/webserver/token")
        token = root.findtext("token") or root.findtext("TokInfo")
        if not token:
            raise RuntimeError("модем не вернул POST-токен")
        return await self.api(
            path, xml, token[32:] if len(token) > 32 else token,
            "/html/smsinbox.html",
        )

    async def get_sms(self):
        if not self.session_id:
            await self.open_session()
        root = await self.post_sms("/api/sms/sms-list", _xml(
            PageIndex=1, ReadCount=50, BoxType=1,
            SortType=0, Ascending=0, UnreadPreferred=1,
        ))
        if root.find("Messages") is None:
            raise RuntimeError("sms-list: модем не вернул Messages")
        return [{name: item.findtext(tag, "") for name, tag in {
            "index": "Index", "status": "Smstat", "phone": "Phone",
            "date": "Date", "text": "Content",
        }.items()} for item in root.findall("./Messages/Message")]

    async def mark_as_read(self, index):
        result = await self.post_sms("/api/sms/set-read", _xml(Index=index))
        if (result.text or "").strip() != "OK":
            raise RuntimeError(f"не удалось пометить СМС {index} прочитанной")

    async def forward_unread(self):
        for sms in await self.get_sms():
            if sms["status"] not in ("", "0"):
                continue
            if not sms["index"].isdigit():
                raise RuntimeError("sms-list: модем не вернул индекс СМС")
            identity = json.dumps([
                self.url, *(sms[field] for field in ("index", "phone", "date", "text")),
            ], ensure_ascii=False)
            header = f'От: {sms["phone"]}\nДата в модеме: {sms["date"]}\n\n'
            # Even an all-emoji part must fit when a messenger counts UTF-16 units.
            size = yadisk_control.MAX_BOOTH_NOTICE_TEXT // 2 - len(header)
            if size <= 0:
                raise ValueError("слишком длинный отправитель или дата СМС")
            text = sms["text"]
            parts = [text[i:i + size] for i in range(0, len(text), size)] or [""]
            for number, part in enumerate(parts, 1):
                # Stable IDs let the VPS recognize retries, including after a restart.
                notice_id = hashlib.sha256(
                    f"{identity}:{number}".encode("utf-8")).hexdigest()[:32]
                title = "СМС на модем фотобудки"
                if len(parts) > 1:
                    title += f" ({number}/{len(parts)})"
                await yadisk_control.publish_booth_notice(
                    "sms_received", title, header + part, notice_id=notice_id,
                )
            # The unread modem inbox is the retry buffer until Disk accepts the text.
            await self.mark_as_read(sms["index"])
            log.info(
                "SMS: index %s uploaded for VPS delivery and marked read", sms["index"])


async def watch(config):
    global status
    if not config.get("sms_enabled", False):
        status = "выключено"
        log.info("SMS: disabled")
        return
    status = "ожидание опроса"
    delay = POLL_INTERVAL
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        modem = Modem(session, MODEM_URL, PASSWORD)
        log.info("SMS: background polling started")
        while True:
            try:
                await modem.forward_unread()
                if status != "модем доступен":
                    log.info("SMS: modem ready")
                status = "модем доступен"
                delay = POLL_INTERVAL
            except Exception as exc:
                status = str(exc) or type(exc).__name__
                modem.session_id = ""
                delay = min(max(30, delay * 2), 300)
                log.warning("SMS: %s; retry in %ss", status, delay)
            await asyncio.sleep(delay)
