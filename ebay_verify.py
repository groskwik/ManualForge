from flask import Flask, request, jsonify
import hashlib

app = Flask(__name__)

# IMPORTANT: this must be EXACTLY the same token you typed in the eBay form
VERIFICATION_TOKEN = "ebay_token_for_benoit_2025_123456789_123456"

# IMPORTANT: this must be EXACTLY the URL you told eBay
# for example: https://ventilable-tandra-subconnectedly.ngrok-free.dev
ENDPOINT_URL = "https://ventilable-tandra-subconnectedly.ngrok-free.dev"

@app.route("/", methods=["GET", "POST"])
def root():
    # eBay sends: GET /?challenge_code=...
    challenge_code = request.args.get("challenge_code")
    print("Incoming request, args:", request.args)

    if challenge_code:
        # eBay spec: SHA256( challengeCode + verificationToken + endpointUrl )
        to_hash = challenge_code + VERIFICATION_TOKEN + ENDPOINT_URL
        digest = hashlib.sha256(to_hash.encode("utf-8")).hexdigest()
        print("Responding with challengeResponse:", digest)
        return jsonify({"challengeResponse": digest})

    # if eBay later sends real delete notifications (POST), just return ok
    return "ok", 200

if __name__ == "__main__":
    # run on port 5000 so ngrok http 5000 works
    app.run(host="0.0.0.0", port=5000)


# ngrok account recovery
# JMRARECRD9
# Q693Q2UXGP
# 9SFYJDVYR9
# WJSQNXMTKD
# FFVAHKX2YS
# VP6WPHTKTT
# BHKJ72P96U
# VD7A2W27JH
# 2JYGZH8AXH
# EDWXPWW4BC
# Token
# 35DvUMOrzEGeNZ3SMH5823rHCI6_3Jc2LywakeXW5eGp7YPYD
# public endpoint
# https://ventilable-tandra-subconnectedly.ngrok-free.dev 
