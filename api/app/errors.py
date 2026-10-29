"""Turn unexpected failures into plain-English messages the web app can show.

Without this, an unhandled error returns a bare 500 without CORS headers, and the browser only says
"Failed to fetch". This middleware sits inside the CORS middleware, so the real reason reaches the screen."""
import logging

import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = logging.getLogger("errors")


def explain(exc: Exception) -> tuple[int, str]:
    name = type(exc).__name__
    module = type(exc).__module__ or ""
    text = str(exc)
    if module.startswith("anthropic"):
        if name == "AuthenticationError":
            return 502, "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env, then run docker compose up -d."
        if "credit balance" in text.lower():
            return 502, "Your Anthropic account is out of credit. Add credit at console.anthropic.com → Billing."
        if name == "NotFoundError":
            return 502, "The AI model name wasn't recognised. Check the model name in Settings."
        if name in ("RateLimitError", "InternalServerError", "APIConnectionError", "APITimeoutError"):
            return 503, "The AI service is busy or unreachable right now. Try again in a minute."
        return 502, f"The AI service returned an error: {text[:200]}"
    if module.startswith("openai"):
        return 502, f"The local AI model couldn't be reached or returned an error: {text[:200]}"
    if isinstance(exc, httpx.HTTPStatusError) and "/storage/" in str(exc.request.url):
        code = exc.response.status_code
        if code in (400, 404) and "bucket" in exc.response.text.lower():
            return 502, "Supabase Storage has no bucket named “documents”. Create it (private) under Storage."
        if code in (401, 403):
            return 502, "Supabase Storage refused the upload. Check SUPABASE_SERVICE_ROLE_KEY (the sb_secret key) in .env."
        return 502, f"Couldn't save the file to Supabase Storage ({code}): {exc.response.text[:150]}"
    if isinstance(exc, httpx.ConnectError):
        return 502, "Couldn't reach Supabase Storage. Check SUPABASE_URL in .env."
    if isinstance(exc, ValueError) and "JSON" in text:
        return 502, "The AI's answer couldn't be read. Try again; if it keeps happening, try a different model in Settings."
    return 500, f"Something went wrong: {name}: {text[:200]}"


class FriendlyErrors(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001
            log.exception("unhandled error on %s %s", request.method, request.url.path)
            status, message = explain(exc)
            return JSONResponse(status_code=status, content={"detail": message})
