#!/usr/bin/env python3

import base64
import hashlib
import time
import urllib.request
import xml.etree.ElementTree as ET


MODEM = "http://192.168.8.1"
USER = "admin"
PASSWORD = ""  # Впиши пароль админки или оставь пустым.
INTERVAL = 5

session_id = ""


def api(path, xml=None, token=None, referer="/html/home.html"):
    """GET без xml, POST с xml. Возвращает разобранный XML."""
    global session_id

    headers = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
    if session_id:
        headers["Cookie"] = f"SessionID={session_id}"
    if token:
        # Для BROVI важны подчёркивания в именах этих заголовков.
        headers.update({
            "__RequestVerificationToken": token,
            "_ResponseSource": "Broswer",  # Так, с опечаткой, делает WebUI.
            "Origin": MODEM,
            "Referer": MODEM + referer,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        })

    data = xml.encode("utf-8") if xml is not None else None
    request = urllib.request.Request(MODEM + path, data=data, headers=headers)

    with urllib.request.urlopen(request, timeout=8) as response:
        cookie = response.headers.get("Set-Cookie", "")
        if "SessionID=" in cookie:
            session_id = cookie.split("SessionID=", 1)[1].split(";", 1)[0]
        root = ET.fromstring(response.read())

    if root.tag == "error":
        raise RuntimeError(f'ошибка API {root.findtext("code", "unknown")}')
    return root


def b64_sha256(text):
    digest = hashlib.sha256(text.encode()).hexdigest().encode()
    return base64.urlsafe_b64encode(digest).decode()


def open_session():
    """Получить SessionID и при необходимости войти в админку."""
    global session_id

    session_id = ""
    root = api("/api/webserver/SesTokInfo")
    session = root.findtext("SesInfo")
    login_token = root.findtext("TokInfo")
    if not session or not login_token:
        raise RuntimeError("модем не вернул SessionID/TokInfo")
    session_id = session.removeprefix("SessionID=")

    if PASSWORD:
        password_hash = b64_sha256(USER + b64_sha256(PASSWORD) + login_token)
        xml = (
            f"<request><Username>{USER}</Username>"
            f"<Password>{password_hash}</Password>"
            "<password_type>4</password_type></request>"
        )
        result = api("/api/user/login", xml, login_token)
        if (result.text or "").strip() != "OK":
            raise RuntimeError("модем не принял логин/пароль")


def fresh_post_token():
    """CSRF-токен этой модели безопаснее получать перед каждым POST."""
    root = api("/api/webserver/token")
    token = root.findtext("token") or root.findtext("TokInfo")
    if not token:
        raise RuntimeError("модем не вернул POST-токен")
    return token[32:] if len(token) > 32 else token


def get_sms():
    xml = (
        "<request><PageIndex>1</PageIndex><ReadCount>50</ReadCount>"
        "<BoxType>1</BoxType><SortType>0</SortType><Ascending>0</Ascending>"
        "<UnreadPreferred>1</UnreadPreferred></request>"
    )
    root = api(
        "/api/sms/sms-list",
        xml,
        fresh_post_token(),
        "/html/smsinbox.html",
    )

    result = []
    for item in root.findall("./Messages/Message"):
        result.append({name: item.findtext(tag, "") for name, tag in {
            "index": "Index",
            "status": "Smstat",
            "phone": "Phone",
            "date": "Date",
            "text": "Content",
        }.items()})
    return result


def mark_as_read(index):
    xml = f"<request><Index>{index}</Index></request>"
    result = api(
        "/api/sms/set-read",
        xml,
        fresh_post_token(),
        "/html/smsinbox.html",
    )
    if (result.text or "").strip() != "OK":
        raise RuntimeError(f"не удалось пометить SMS {index} прочитанной")


def send_to_telegram(sms):
    """Пока мок: потом здесь будет HTTPS-запрос к Telegram."""
    print(f'\nSMS от {sms["phone"]} ({sms["date"]})')
    print(sms["text"], flush=True)
    return True


def main():
    global session_id
    seen = set()
    print("Слежу за SMS; остановка: Ctrl+C")

    while True:
        try:
            if not session_id:
                open_session()
                print("Сессия открыта", flush=True)

            for sms in get_sms():
                if sms["status"] not in ("", "0"):  # 0 = непрочитанная
                    continue
                key = tuple(sms.values())
                if key not in seen and send_to_telegram(sms):
                    mark_as_read(sms["index"])
                    seen.add(key)

        except KeyboardInterrupt:
            print("\nОстановлено")
            return
        except Exception as error:
            print(f"Ошибка: {error}; пересоздаю сессию", flush=True)
            session_id = ""

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
