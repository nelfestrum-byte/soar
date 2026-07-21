from fastapi import Request


def resolve_client_ip(request: Request) -> str:
    """Client IP, trusting X-Real-IP/X-Forwarded-For only from configured trusted_proxies."""
    client_ip = request.client.host if request.client else "unknown"

    config = getattr(request.app.state, "config", None)
    trusted_proxies = config.server.trusted_proxies if config else []
    if client_ip in trusted_proxies:
        forwarded_ip = (
            request.headers.get("X-Real-IP")
            or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        )
        if forwarded_ip:
            client_ip = forwarded_ip

    return client_ip
