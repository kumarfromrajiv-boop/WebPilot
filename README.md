
# AI Browser Automation Platform

AI Browser Automation Platform built with:

- Python
- FastAPI
- Playwright
- Chromium
- OpenRouter API
- Render

## 1. Project Features

- Browser automation through API
- AI-powered browser actions
- Website navigation
- Automatic clicking
- Form filling
- Text searching
- Scrolling
- Screenshot analysis
- Error handling
- Customer API keys
- Secure API authentication

## 2. Project Files

main.py
requirements.txt
render.yaml
.env.example
client-example.py
README.md

## 3. Install Python Libraries

Run:

pip install -r requirements.txt

## 4. Install Playwright Chromium

Run:

playwright install chromium

## 5. Configure Environment Variables

Set these variables:

OPENROUTER_API_KEY=your_api_key

OPENROUTER_MODEL=your_vision_model

ADMIN_SECRET=your_admin_secret

ALLOWED_HOSTS=example.com

MAX_STEPS=12

TASK_TIMEOUT=180

## 6. Run Locally

Run:

uvicorn main:app --reload

Open:

http://127.0.0.1:8000

API Documentation:

http://127.0.0.1:8000/docs

## 7. Create Customer API Key

Send POST request to:

/admin/api-keys

Header:

X-Admin-Secret: YOUR_ADMIN_SECRET

Request Body:

{
  "label": "customer-1"
}

The API will return a new customer API key.

Save this key securely.

## 8. Execute Browser Automation

Endpoint:

POST /api/browser/execute

Header:

Authorization: Bearer YOUR_CUSTOMER_API_KEY

Request Body:

{
  "url": "https://example.com",
  "instruction": "Open the website and find its main heading.",
  "max_steps": 8
}

## 9. Deploy on Render

1. Upload the project to GitHub.
2. Create a Render Web Service.
3. Connect the GitHub repository.
4. Configure Environment Variables.
5. Deploy the application.
6. Open the Render URL.
7. Test the API using /docs.

## 10. Security

- Use separate API keys for customers.
- Keep API secrets private.
- Restrict allowed website domains.
- Use isolated browser sessions.
- Set task timeouts and action limits.
- Require human help for OTP and CAPTCHA.
- Never automate websites without authorization.

## 11. Important Production Notes

This is a starter implementation.

Before launching publicly, add:

- Persistent database
- Background task queue
- Rate limiting
- Customer usage limits
- API key revocation
- Human approval and resume workflow
- Strong network-level SSRF protection
- Encrypted credential storage

Only automate websites and accounts you are authorized to use.
