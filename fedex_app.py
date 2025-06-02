import streamlit as st
import requests
import os

st.set_page_config(page_title="FedEx Rate Checker", layout="centered")

# --- Secrets via environment variables ---
CLIENT_ID = os.getenv("FEDEX_CLIENT_ID", "YOUR_FEDEX_CLIENT_ID")
CLIENT_SECRET = os.getenv("FEDEX_CLIENT_SECRET", "YOUR_FEDEX_CLIENT_SECRET")
ACCOUNT_NUMBER = os.getenv("FEDEX_ACCOUNT_NUMBER", "YOUR_FEDEX_ACCOUNT_NUMBER")

# --- Helper Functions ---
def get_access_token():
    url = "https://apis.fedex.com/oauth/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        return response.json().get("access_token")
    except requests.exceptions.RequestException as e:
        st.error(f"OAuth error: {e}")
        return None

def get_list_rates(origin_zip, dest_zip, weight_lb):
    token = get_access_token()
    if not token:
        return {"error": "Unable to get access token."}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = {
        "accountNumber": {"value": ACCOUNT_NUMBER},
        "requestedShipment": {
            "shipper": {
                "address": {
                    "postalCode": origin_zip,
                    "countryCode": "US"
                }
            },
            "recipient": {
                "address": {
                    "postalCode": dest_zip,
                    "countryCode": "US",
                    "residential": False
                }
            },
            "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
            "packagingType": "YOUR_PACKAGING",
            "rateRequestType": ["LIST"],
            "requestedPackageLineItems": [
                {
                    "weight": {
                        "units": "LB",
                        "value": weight_lb
                    }
                }
            ]
        }
    }

    try:
        response = requests.post("https://apis.fedex.com/rate/v1/rates/quotes", headers=headers, json=body)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"API request failed: {e}"}

def extract_selected_rates(response):
    results = {}
    rate_details = response.get("output", {}).get("rateReplyDetails", [])
    for item in rate_details:
        service_name = item.get("serviceName") or item.get("serviceType") or "Unknown Service"
        for detail in item.get("ratedShipmentDetails", []):
            rate_detail = detail.get("shipmentRateDetail") or {}
            charge = rate_detail.get("totalNetFedExCharge") or {}
            amount = charge.get("amount")
            currency = charge.get("currency")
            if amount and currency:
                results[service_name] = f"{amount} {currency}"
    return results

# --- Streamlit UI ---
st.title("📦 FedEx Rate Checker")
st.markdown("Check retail (list) rates for FedEx Ground, 2Day, and Overnight services.")

with st.form("rate_form"):
    origin = st.text_input("From ZIP Code", value="53202")
    destination = st.text_input("To ZIP Code", value="90210")
    weight = st.number_input("Package Weight (lb)", min_value=0.1, value=10.0)
    submitted = st.form_submit_button("Get Rates")

if submitted:
    response = get_list_rates(origin, destination, weight)
    if "error" in response:
        st.error(response["error"])
    else:
        rates = extract_selected_rates(response)
        if rates:
            st.success("Here are the available list rates:")
            for service, price in rates.items():
                st.write(f"**{service}**: {price}")
        else:
            st.warning("No matching list rates returned for the specified inputs.")

        # Show FedEx alerts if available
        alerts = response.get("output", {}).get("alerts", [])
        if alerts:
            st.info("FedEx API Alerts:")
            for alert in alerts:
                code = alert.get("code")
                message = alert.get("message")
                st.write(f"- ({code}) {message}")

        # Always show the raw FedEx response for debugging
        with st.expander("See full FedEx API response"):
            try:
                st.json(response)
            except Exception:
                st.write("Raw response:")
                st.write(response)
