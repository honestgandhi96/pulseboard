import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    base_url = os.getenv("BASE_URL", "").strip().rstrip("/")
    if not base_url:
        print("BASE_URL is not configured", file=sys.stderr)
        return 1

    url = f"{base_url}/v1/ingest/run?trigger_type=scheduled"
    request = urllib.request.Request(url, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
            print(body)
            return 0
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(
            json.dumps(
                {
                    "url": url,
                    "status_code": exc.code,
                    "error": error_body,
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    except urllib.error.URLError as exc:
        print(f"Failed to reach {url}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
