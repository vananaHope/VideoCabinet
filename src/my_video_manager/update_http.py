"""Bounded, unauthenticated HTTPS transport for release metadata only."""
from http.client import HTTPException
import socket
import time
from urllib import error, parse, request


class UpdateCheckError(Exception):
    """A stable code, never a remote body, URL, or exception message."""

    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(kind)


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibUpdateHttp:
    """At most 3 HTTPS redirects, 10s socket timeout, 30s elapsed budget per GET.

    The elapsed budget is checked between I/O operations; a pending operation
    can take up to the socket timeout. No retries, cookies, or auth tokens.
    opener is an optional urllib-compatible transport for offline tests.
    """

    HOSTS = frozenset({'api.github.com', 'github.com', 'objects.githubusercontent.com',
                       'release-assets.githubusercontent.com'})

    def __init__(self, *, opener=None):
        self._opener = opener if opener is not None else request.build_opener(_NoRedirect())

    def get(self, url: str, *, max_bytes: int) -> bytes:
        deadline = time.monotonic() + 30
        try:
            for redirects in range(4):
                parts = parse.urlsplit(url)
                if (parts.scheme != 'https' or parts.hostname not in self.HOSTS
                        or parts.username is not None or parts.password is not None
                        or parts.port not in (None, 443) or parts.fragment):
                    raise UpdateCheckError('unsafe_redirect')
                if time.monotonic() >= deadline:
                    raise UpdateCheckError('timeout')
                req = request.Request(url, headers={
                    'User-Agent': 'my-video-manager-update-check',
                    'Accept': 'application/vnd.github+json' if parts.hostname == 'api.github.com'
                              else 'application/octet-stream',
                    'Accept-Encoding': 'identity',
                })
                try:
                    response = self._opener.open(req, timeout=min(10, deadline - time.monotonic()))
                except error.HTTPError as exc:
                    with exc:
                        if exc.code in (301, 302, 303, 307, 308):
                            if redirects == 3:
                                raise UpdateCheckError('too_many_redirects') from None
                            location = exc.headers.get('Location')
                            if not location:
                                raise UpdateCheckError('invalid_response') from None
                            url = parse.urljoin(url, location)
                            continue
                        raise UpdateCheckError(f'http_{exc.code}') from None
                with response:
                    if response.status != 200:
                        raise UpdateCheckError(f'http_{response.status}')
                    length = response.headers.get('Content-Length')
                    if length is not None:
                        if not length.isascii() or not length.isdecimal():
                            raise UpdateCheckError('invalid_response')
                        length = int(length)
                        if length > max_bytes:
                            raise UpdateCheckError('response_too_large')
                    chunks = bytearray()
                    while True:
                        if time.monotonic() >= deadline:
                            raise UpdateCheckError('timeout')
                        # read1 does not wait for an entire buffer of drip-fed data.
                        chunk = response.read1(min(65536, max_bytes + 1 - len(chunks)))
                        if time.monotonic() >= deadline:
                            raise UpdateCheckError('timeout')
                        if not chunk:
                            break
                        chunks.extend(chunk)
                        if len(chunks) > max_bytes:
                            raise UpdateCheckError('response_too_large')
                    if length is not None and len(chunks) != length:
                        raise UpdateCheckError('invalid_response')
                    return bytes(chunks)
        except (TimeoutError, socket.timeout):
            raise UpdateCheckError('timeout') from None
        except error.URLError as exc:
            kind = 'timeout' if isinstance(exc.reason, TimeoutError) else 'network'
            raise UpdateCheckError(kind) from None
        except (OSError, HTTPException):
            raise UpdateCheckError('network') from None
        except ValueError:
            raise UpdateCheckError('invalid_response') from None
        raise UpdateCheckError('too_many_redirects')
