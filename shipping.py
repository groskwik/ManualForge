#!/usr/bin/env python
import requests
import os

def load_token():
    # try env var first
    token = os.environ.get("EBAY_USER_TOKEN")
    if token:
        return token.strip()
    # fallback to file
    with open("ebay_token.txt", "r") as f:
        return f.read().strip()

EBAY_TOKEN = load_token()

BASE_URL = "https://api.ebay.com/sell/fulfillment/v1/order"
FILTER = "orderfulfillmentstatus:{NOT_STARTED|IN_PROGRESS}"

headers = {
    "Authorization": f"Bearer {EBAY_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

params = {
    "filter": FILTER,
    "limit": "50",
    "offset": "0"
}

resp = requests.get(BASE_URL, headers=headers, params=params)
print(resp.status_code)
print(resp.text)

