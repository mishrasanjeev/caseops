"""Execute only the extracted diagnostic scalar with an offline HTTP interceptor."""
import io
import json
import sys
import urllib.request

observed = []

def transport(request, *, timeout):
    if isinstance(request, str):
        url, headers = request, {}
    else:
        url, headers = request.full_url, dict(request.header_items())
    assert url == "http://127.0.0.1:8000/api/health"
    observed.append({"url": url, "headers": headers, "timeout": timeout})
    return io.BytesIO(b'{"status":"ok"}')

urllib.request.urlopen = transport
exec(compile(sys.argv[1], "cold-health-scalar", "exec"), {"__name__": "metadata_probe"})
print("REQUESTS " + json.dumps({"records": observed, "external_requests": 0}))
