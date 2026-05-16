from fastapi.testclient import TestClient
from wirestudio.api.app import create_app

def test_cors_preflight_headers_restricted():
    app = create_app()
    client = TestClient(app)

    # Simulate a preflight request from an allowed origin
    # asking for a header that is NOT in our new whitelist.
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-Custom-Header",
    }

    response = client.options("/health", headers=headers)

    assert response.status_code == 200
    allow_headers = response.headers.get("access-control-allow-headers", "")

    # After the fix, X-Custom-Header should NOT be allowed.
    # CORSMiddleware typically only returns the intersection of requested and allowed headers,
    # or the full allowed list. In either case, X-Custom-Header should not be there.
    assert "X-Custom-Header" not in allow_headers
    assert allow_headers != "*"

    # Verify that our whitelisted headers ARE allowed if requested
    headers_ok = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type, Authorization",
    }
    response_ok = client.options("/health", headers=headers_ok)
    assert response_ok.status_code == 200
    allow_headers_ok = response_ok.headers.get("access-control-allow-headers", "").split(", ")
    assert "Content-Type" in allow_headers_ok or "content-type" in [h.lower() for h in allow_headers_ok]
    assert "Authorization" in allow_headers_ok or "authorization" in [h.lower() for h in allow_headers_ok]
