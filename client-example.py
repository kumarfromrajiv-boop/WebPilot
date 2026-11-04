
import requests

# =================================
# YOUR RENDER SERVER URL
# =================================

API_URL = "https://YOUR-RENDER-SERVICE.onrender.com"


# =================================
# CUSTOMER API KEY
# =================================

API_KEY = "YOUR_CUSTOMER_API_KEY"


# =================================
# SEND BROWSER AUTOMATION REQUEST
# =================================

def run_browser_task(url, instruction):

    endpoint = f"{API_URL}/api/browser/execute"

    headers = {

        "Authorization": f"Bearer {API_KEY}",

        "Content-Type": "application/json"

    }

    payload = {

        "url": url,

        "instruction": instruction,

        "max_steps": 8

    }

    try:

        response = requests.post(

            endpoint,

            headers=headers,

            json=payload,

            timeout=240

        )

        response.raise_for_status()

        result = response.json()

        return result

    except requests.exceptions.Timeout:

        return {
            "status": "error",
            "message": "Request timed out"
        }

    except requests.exceptions.RequestException as error:

        return {
            "status": "error",
            "message": str(error)
        }


# =================================
# EXAMPLE USAGE
# =================================

if __name__ == "__main__":

    result = run_browser_task(

        url="https://example.com",

        instruction="Open the website and tell me its main heading."

    )

    print("BROWSER AUTOMATION RESULT:")

    print(result)
