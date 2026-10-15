"""실제 로컬 TLS로 인증서/호스트 검증과 HTTPS 생성자 호환성을 확인한다."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
from threading import Event, Thread

import pytest

from my_video_manager.opencode_go import OpenCodeGoError, UrllibTransport


@pytest.fixture
def tls_server():
    fixtures = Path(__file__).parent / "fixtures" / "tls"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(fixtures / "localhost-cert.pem", fixtures / "localhost-key.pem")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.requests = []
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, fixtures / "localhost-cert.pem"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("trusted,host,succeeds", [
    (True, "localhost", True),
    (False, "localhost", False),
    (True, "127.0.0.1", False),
])
def test_https_preserves_certificate_and_hostname_verification(tls_server, monkeypatch, trusted, host, succeeds):
    server, cert = tls_server
    context = ssl.create_default_context(cafile=str(cert) if trusted else None)
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    monkeypatch.setattr(ssl, "_create_default_https_context", lambda: context)
    # Python 3.10에서도 3.12+처럼 check_hostname 인자를 받지 않는 생성자를 적용한다.
    original_init = http.client.HTTPSConnection.__init__

    def init(connection, host, port=None, *, timeout=10, context=None):
        original_init(connection, host, port, timeout=timeout, context=context)

    monkeypatch.setattr(http.client.HTTPSConnection, "__init__", init)
    url = f"https://{host}:{server.server_port}/v1/models"
    if succeeds:
        response = UrllibTransport().request("GET", url, headers={}, body=None,
                                            timeout=3, cancellation=Event())
        assert response.status == 200 and response.body == b"{}"
        assert server.requests == ["/v1/models"]
    else:
        with pytest.raises(OpenCodeGoError) as raised:
            UrllibTransport().request("GET", url, headers={}, body=None,
                                      timeout=3, cancellation=Event())
        assert raised.value.kind == "connection"
        assert server.requests == []
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
