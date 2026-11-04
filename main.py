
import os
import re
import json
import time
import uuid
import base64
import hashlib
import socket
import ipaddress
import sqlite3
import asyncio

from urllib.parse import urlparse
from contextlib import asynccontextmanager
from typing import Any

import httpx

from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field, HttpUrl

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError
)


# ==========================================
# CONFIGURATION
# ==========================================

APP_NAME = "AI Browser Automation Platform"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "")

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "/tmp/browser_tasks.db"
)

MAX_STEPS = int(os.getenv("MAX_STEPS", "12"))

TASK_TIMEOUT = int(os.getenv("TASK_TIMEOUT", "180"))

NAVIGATION_TIMEOUT = int(
    os.getenv("NAVIGATION_TIMEOUT", "30000")
)

ALLOWED_HOSTS = {
    x.strip().lower()
    for x in os.getenv("ALLOWED_HOSTS", "").split(",")
    if x.strip()
}


# ==========================================
# DATABASE
# ==========================================

def db():

    conn = sqlite3.connect(DATABASE_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key_hash TEXT PRIMARY KEY,
            label TEXT,
            active INTEGER DEFAULT 1,
            created_at INTEGER
        )
    """)

    conn.commit()

    return conn


def key_hash(key: str) -> str:

    return hashlib.sha256(
        key.encode()
    ).hexdigest()


# ==========================================
# ADMIN AUTHENTICATION
# ==========================================

def require_admin(
    x_admin_secret: str = Header(default="")
):

    if not ADMIN_SECRET:
        raise HTTPException(
            503,
            "ADMIN_SECRET is not configured"
        )

    if not hashlib.sha256(
        x_admin_secret.encode()
    ).digest() == hashlib.sha256(
        ADMIN_SECRET.encode()
    ).digest():

        raise HTTPException(
            403,
            "Invalid admin secret"
        )


# ==========================================
# CUSTOMER API KEY AUTHENTICATION
# ==========================================

def require_api_key(
    authorization: str = Header(default="")
):

    if not authorization.startswith("Bearer "):

        raise HTTPException(
            401,
            "Missing Bearer API key"
        )

    raw = authorization[7:].strip()

    if not raw:

        raise HTTPException(
            401,
            "Missing API key"
        )

    conn = db()

    row = conn.execute(
        "SELECT active FROM api_keys WHERE key_hash=?",
        (key_hash(raw),)
    ).fetchone()

    conn.close()

    if not row or row[0] != 1:

        raise HTTPException(
            401,
            "Invalid or inactive API key"
        )

    return raw


# ==========================================
# REQUEST MODELS
# ==========================================

class CreateKeyRequest(BaseModel):

    label: str = Field(
        default="customer",
        max_length=100
    )


class ExecuteRequest(BaseModel):

    url: HttpUrl

    instruction: str = Field(
        min_length=3,
        max_length=4000
    )

    credentials: dict[str, str] = Field(
        default_factory=dict
    )

    max_steps: int | None = Field(
        default=None,
        ge=1,
        le=20
    )


# ==========================================
# URL SECURITY
# ==========================================

def validate_target(url: str):

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):

        raise HTTPException(
            400,
            "Only HTTP and HTTPS URLs are allowed"
        )

    host = parsed.hostname

    if not host:

        raise HTTPException(
            400,
            "Invalid website URL"
        )

    host = host.lower()

    if ALLOWED_HOSTS:

        allowed = any(
            host == domain or
            host.endswith("." + domain)
            for domain in ALLOWED_HOSTS
        )

        if not allowed:

            raise HTTPException(
                403,
                "Website is not in ALLOWED_HOSTS"
            )

    if (
        host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".local")
    ):

        raise HTTPException(
            400,
            "Local network targets are blocked"
        )

    try:

        addresses = {
            ipaddress.ip_address(host)
        }

    except ValueError:

        try:

            infos = socket.getaddrinfo(
                host,
                None,
                type=socket.SOCK_STREAM
            )

            addresses = {
                ipaddress.ip_address(info[4][0])
                for info in infos
            }

        except socket.gaierror:

            raise HTTPException(
                400,
                "Target host could not be resolved"
            )

    if any(not ip.is_global for ip in addresses):

        raise HTTPException(
            400,
            "Private or reserved network targets are blocked"
        )


# ==========================================
# AI JSON RESPONSE
# ==========================================

def extract_json(content: str) -> dict[str, Any]:

    content = content.strip()

    content = re.sub(
        r"^```(?:json)?\s*",
        "",
        content
    )

    content = re.sub(
        r"\s*```$",
        "",
        content
    )

    try:

        data = json.loads(content)

        if isinstance(data, dict):
            return data

    except json.JSONDecodeError:
        pass

    match = re.search(
        r"\{.*\}",
        content,
        re.S
    )

    if match:

        data = json.loads(match.group(0))

        if isinstance(data, dict):
            return data

    raise ValueError(
        "AI returned invalid JSON"
    )


# ==========================================
# OPENROUTER AI CONNECTION
# ==========================================

async def ask_model(
    instruction,
    current_url,
    page_text,
    screenshot_b64,
    history,
    credentials
):

    if not OPENROUTER_API_KEY:

        raise RuntimeError(
            "OPENROUTER_API_KEY is missing"
        )

    if not OPENROUTER_MODEL:

        raise RuntimeError(
            "OPENROUTER_MODEL is missing"
        )

    system = """
You are an AI browser automation planner.

Return ONLY valid JSON.

Allowed actions:

click
fill
press
scroll
wait
done
needs_attention

Response example:

{
  "action": "click",
  "selector": "role:button:name=Login",
  "reason": "Login button found"
}

Selectors:

role:button:name=Continue
role:link:name=Dashboard
label:Email
placeholder:Search
text:OpenAI
css:button.submit

For OTP, CAPTCHA, payments and destructive
actions return needs_attention.

Never bypass CAPTCHA or access controls.

Never expose passwords or credentials.

Return done only when the task is completed.
"""

    user_data = {

        "instruction": instruction,

        "current_url": current_url,

        "visible_page_text": page_text[:14000],

        "recent_actions": history[-8:],

        "available_credential_fields": list(
            credentials.keys()
        )

    }

    content = [

        {
            "type": "text",
            "text": json.dumps(
                user_data,
                ensure_ascii=False
            )
        }

    ]

    if screenshot_b64:

        content.append({

            "type": "image_url",

            "image_url": {

                "url": (
                    "data:image/jpeg;base64,"
                    + screenshot_b64
                )

            }

        })

    headers = {

        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),

        "Content-Type": "application/json",

        "HTTP-Referer": os.getenv(
            "PUBLIC_APP_URL",
            "https://your-service.onrender.com"
        ),

        "X-Title": APP_NAME

    }

    payload = {

        "model": OPENROUTER_MODEL,

        "messages": [

            {
                "role": "system",
                "content": system
            },

            {
                "role": "user",
                "content": content
            }

        ],

        "temperature": 0.1,

        "max_tokens": 700

    }

    async with httpx.AsyncClient(
        timeout=60
    ) as client:

        response = await client.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload
        )

        response.raise_for_status()

        result = response.json()

    raw = result["choices"][0]["message"]["content"]

    if isinstance(raw, list):

        raw = "\n".join(
            item.get("text", "")
            for item in raw
            if item.get("type") == "text"
        )

    return extract_json(raw)


# ==========================================
# PLAYWRIGHT SELECTORS
# ==========================================

def make_locator(page, selector):

    if not selector:
        raise ValueError("Selector is required")

    if selector.startswith("role:"):

        match = re.match(
            r"role:([^:]+):name=(.*)",
            selector
        )

        if not match:
            raise ValueError("Invalid role selector")

        return page.get_by_role(
            match.group(1),
            name=match.group(2),
            exact=False
        ).first

    if selector.startswith("label:"):

        return page.get_by_label(
            selector[6:],
            exact=False
        ).first

    if selector.startswith("placeholder:"):

        return page.get_by_placeholder(
            selector[12:],
            exact=False
        ).first

    if selector.startswith("text:"):

        return page.get_by_text(
            selector[5:],
            exact=False
        ).first

    if selector.startswith("css:"):

        return page.locator(
            selector[4:]
        ).first

    return page.locator(selector).first


# ==========================================
# WEBSITE PAGE INFORMATION
# ==========================================

async def page_context(page):

    try:

        text = await page.locator(
            "body"
        ).inner_text(timeout=5000)

    except Exception:

        text = ""

    return text[:14000]


# ==========================================
# EXECUTE BROWSER ACTION
# ==========================================

async def run_action(
    page,
    data,
    credentials
):

    action = str(
        data.get("action", "")
    ).lower()

    selector = data.get("selector")

    value = data.get("value")

    if isinstance(value, str):

        match = re.fullmatch(
            r"\{\{credential:([A-Za-z0-9_.-]+)\}\}",
            value
        )

        if match:

            field = match.group(1)

            if field not in credentials:

                raise ValueError(
                    "Credential field not provided"
                )

            value = credentials[field]

    if action == "click":

        await make_locator(
            page,
            selector
        ).click(timeout=10000)

    elif action == "fill":

        if value is None:

            raise ValueError(
                "Fill action requires a value"
            )

        await make_locator(
            page,
            selector
        ).fill(
            str(value),
            timeout=10000
        )

    elif action == "press":

        key = data.get("key") or "Enter"

        if selector:

            await make_locator(
                page,
                selector
            ).press(
                key,
                timeout=10000
            )

        else:

            await page.keyboard.press(key)

    elif action == "scroll":

        direction = data.get(
            "direction",
            "down"
        )

        amount = max(
            100,
            min(
                int(data.get("amount") or 600),
                1500
            )
        )

        await page.evaluate(
            "(arg) => window.scrollBy(0, arg)",
            amount if direction == "down" else -amount
        )

    elif action == "wait":

        amount = int(
            data.get("amount") or 1000
        )

        await page.wait_for_timeout(
            min(max(amount, 200), 5000)
        )

    elif action in ("done", "needs_attention"):

        return action

    else:

        raise ValueError(
            f"Unsupported action: {action}"
        )

    return "executed"


# ==========================================
# MAIN BROWSER AUTOMATION ENGINE
# ==========================================

async def execute_task(req: ExecuteRequest):

    validate_target(str(req.url))

    started = time.monotonic()

    task_id = (
        "task_"
        + uuid.uuid4().hex[:12]
    )

    history = []

    errors = []

    step_limit = req.max_steps or MAX_STEPS

    async with async_playwright() as p:

        browser = await p.chromium.launch(

            headless=True,

            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]

        )

        context = await browser.new_context(

            viewport={
                "width": 1365,
                "height": 900
            }

        )

        page = await context.new_page()

        page.set_default_timeout(10000)

        page.set_default_navigation_timeout(
            NAVIGATION_TIMEOUT
        )

        try:

            await page.goto(
                str(req.url),
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT
            )

            final_result = ""

            status = "needs_attention"

            for step in range(1, step_limit + 1):

                if (
                    time.monotonic() - started
                    > TASK_TIMEOUT
                ):

                    errors.append(
                        "Task time limit exceeded"
                    )

                    break

                page_text = await page_context(page)

                screenshot = await page.screenshot(

                    type="jpeg",

                    quality=55,

                    full_page=False

                )

                screenshot_b64 = base64.b64encode(
                    screenshot
                ).decode("ascii")

                try:

                    decision = await ask_model(

                        req.instruction,

                        page.url,

                        page_text,

                        screenshot_b64,

                        history,

                        req.credentials

                    )

                    action = decision.get(
                        "action",
                        ""
                    )

                    if action == "needs_attention":

                        status = "needs_attention"

                        final_result = decision.get(
                            "reason",
                            "Human assistance required"
                        )

                        break

                    if action == "done":

                        status = "completed"

                        final_result = decision.get(
                            "result",
                            "Task completed"
                        )

                        break

                    outcome = await run_action(

                        page,

                        decision,

                        req.credentials

                    )

                    history.append({

                        "step": step,

                        "action": action,

                        "selector": decision.get(
                            "selector"
                        ),

                        "outcome": outcome

                    })

                    await page.wait_for_timeout(700)

                except PlaywrightTimeoutError:

                    errors.append(
                        f"Step {step}: Browser action timed out"
                    )

                    history.append({

                        "step": step,

                        "error": "timeout"

                    })

                except Exception as exc:

                    errors.append(

                        f"Step {step}: "
                        f"{type(exc).__name__}: "
                        f"{str(exc)[:300]}"

                    )

                    history.append({

                        "step": step,

                        "error": str(exc)[:300]

                    })

            else:

                final_result = (
                    "Maximum action count reached"
                )

            if not final_result:

                final_result = (
                    errors[-1]
                    if errors
                    else "Task stopped before completion"
                )

            return {

                "status": status,

                "task_id": task_id,

                "result": final_result,

                "final_url": page.url,

                "steps_completed": len([

                    x for x in history
                    if "outcome" in x

                ]),

                "steps": history,

                "errors": errors,

                "duration_seconds": round(
                    time.monotonic() - started,
                    2
                )

            }

        finally:

            await context.close()

            await browser.close()


# ==========================================
# FASTAPI STARTUP
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    db().close()

    yield


app = FastAPI(

    title=APP_NAME,

    version="1.0.0",

    lifespan=lifespan

)


# ==========================================
# HOME ROUTE
# ==========================================

@app.get("/")
async def root():

    return {

        "service": APP_NAME,

        "status": "online",

        "docs": "/docs"

    }


# ==========================================
# HEALTH CHECK
# ==========================================

@app.get("/health")
async def health():

    return {
        "status": "ok"
    }


# ==========================================
# CREATE CUSTOMER API KEY
# ==========================================

@app.post(
    "/admin/api-keys",
    dependencies=[Depends(require_admin)]
)

async def create_api_key(
    body: CreateKeyRequest
):

    import secrets

    raw = (
        "abp_"
        + secrets.token_urlsafe(32)
    )

    conn = db()

    conn.execute(

        """
        INSERT INTO api_keys
        (key_hash, label, active, created_at)
        VALUES (?, ?, 1, ?)
        """,

        (
            key_hash(raw),
            body.label,
            int(time.time())
        )

    )

    conn.commit()

    conn.close()

    return {

        "api_key": raw,

        "label": body.label,

        "warning": (
            "Copy this key now. "
            "It is stored as a hash."
        )

    }


# ==========================================
# EXECUTE BROWSER TASK API
# ==========================================

@app.post("/api/browser/execute")

async def browser_execute(

    body: ExecuteRequest,

    _: str = Depends(require_api_key)

):

    try:

        return await asyncio.wait_for(

            execute_task(body),

            timeout=TASK_TIMEOUT + 30

        )

    except asyncio.TimeoutError:

        raise HTTPException(
            408,
            "Task timed out"
        )

    except httpx.HTTPStatusError as exc:

        raise HTTPException(

            502,

            f"OpenRouter API error: {exc.response.status_code}"

        )

    except RuntimeError as exc:

        raise HTTPException(
            503,
            str(exc)
        )

    except HTTPException:

        raise

    except Exception as exc:

        raise HTTPException(

            500,

            f"Task failed: {type(exc).__name__}: {str(exc)[:300]}"

        )

