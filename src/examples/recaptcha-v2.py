import os
import httpx
from solvium import Solvium

# Step 0. Change Parameters
PROXY = os.environ.get("PROXY")
assert PROXY is not None, "Please set the PROXY environment variable."
WEBSITE_WITH_RECAPTCHA_V2 = "https://clusters.xyz/community/campnetwork/register"
RECAPTCHA_SITE_KEY = "6Lc4jRkrAAAAAAr295LcTFPkvbxbMxcBS3gfBRXu"
RECAPTCHA_ACTION = "SIGNUP"
CLUSTERS_AUTHORIZATION_TOKEN = os.environ.get("CLUSTERS_AUTHORIZATION_TOKEN")
assert CLUSTERS_AUTHORIZATION_TOKEN is not None, (
    "Please set the CLUSTERS_AUTHORIZATION_TOKEN environment variable."
)
API_KEY = os.environ.get("API_KEY")  # Can be found at https://t.me/solvium_crypto_bot
assert API_KEY is not None, "Please set the API_KEY environment variable."

solvium = Solvium(API_KEY, verbose=True)
session = httpx.Client(proxy=PROXY, verify=False)

# Step 1. Solve Captcha Using Solvium API
solution = solvium.recaptcha_v2_sync(
    RECAPTCHA_SITE_KEY,
    WEBSITE_WITH_RECAPTCHA_V2,
    RECAPTCHA_ACTION,
    enterprise=True,
    proxy=PROXY,
)
assert solution is not None

# Step 2. Make Requests With Token
response = session.post(
    url="https://api.clusters.xyz/v1/trpc/names.community.register",
    headers={
        "authorization": f"Bearer {CLUSTERS_AUTHORIZATION_TOKEN}",
        "content-type": "application/json",
    },
    json={
        "clusterName": "campnetwork",
        "walletName": "walletName",
        "recaptchaToken": {
            "type": "manual",
            "token": solution,
        },
    },
)

print(response.json())
