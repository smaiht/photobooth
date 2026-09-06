"""One TLS trust source for every HTTPS request the booth makes."""

import functools
import ssl

import certifi


@functools.lru_cache(maxsize=1)
def ca_context() -> ssl.SSLContext:
    """Verify HTTPS against the bundled Mozilla CA list.

    Embedded Windows Python has no OpenSSL CA file and sees only the roots
    already cached in the Windows store, which the kiosk profile never
    refreshes: api.yookassa.ru failed with CERTIFICATE_VERIFY_FAILED because
    its HARICA root was missing. One explicit bundle behaves the same on the
    booth and in development, and this module stays free of side effects so
    the updater can import it before the backend exists.
    """
    return ssl.create_default_context(cafile=certifi.where())
