#!/usr/bin/env python
import os
import requests

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------
# Put your user token in an env var before running:
#   set EBAY_USER_TOKEN=eyJhbGciOi...
# v^1.1#i^1#f^0#r^1#p^3#I^3#t^Ul4xMF8zOkE0RDA1QTc4MTVBQ0Q1OEU0QTBFMjkzOEY2NDdFRjVGXzFfMSNFXjI2MA==
EBAY_TOKEN = os.environ.get("EBAY_USER_TOKEN")
if not EBAY_TOKEN:
    raise SystemExit("ERROR: set EBAY_USER_TOKEN env var to your eBay user access token")

# eBay production endpoint
BASE_URL = "https://api.ebay.com/sell/fulfillment/v1/order"

# we want orders that are not fully shipped
FILTER = "orderfulfillmentstatus:{NOT_STARTED|IN_PROGRESS}"

def fetch_orders():
    orders = []
    limit = 50  # max 200, 50 is fine
    offset = 0

    headers = {
        "Authorization": f"Bearer {EBAY_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    while True:
        params = {
            "filter": FILTER,
            "limit": str(limit),
            "offset": str(offset)
        }
        resp = requests.get(BASE_URL, headers=headers, params=params)
        if resp.status_code != 200:
            print("Request failed:", resp.status_code, resp.text)
            break

        data = resp.json()
        batch = data.get("orders", [])
        orders.extend(batch)

        total = data.get("total", 0)
        offset += limit
        if offset >= total:
            break

    return orders


def main():
    orders = fetch_orders()
    print(f"Found {len(orders)} unshipped / partially shipped orders")
    print("-" * 60)

    for o in orders:
        order_id = o.get("orderId")
        status = o.get("orderFulfillmentStatus")
        buyer = o.get("buyer", {})
        buyer_username = buyer.get("username")

        # shipping address is under fulfillmentStartInstructions
        ship_to = None
        inst = o.get("fulfillmentStartInstructions", [])
        if inst:
            ship_to = inst[0].get("shippingStep", {}).get("shipTo")

        print(f"Order ID: {order_id}")
        print(f"Fulfillment status: {status}")
        print(f"Buyer: {buyer_username}")

        if ship_to:
            name = ship_to.get("fullName")
            addr1 = ship_to.get("addressLine1")
            city = ship_to.get("city")
            state = ship_to.get("stateOrProvince")
            postal = ship_to.get("postalCode")
            country = ship_to.get("countryCode")
            print("Ship to:")
            print(f"  {name}")
            print(f"  {addr1}")
            print(f"  {city}, {state} {postal}")
            print(f"  {country}")
        else:
            print("Ship to: (not provided)")

        print("-" * 60)


if __name__ == "__main__":
    main()

