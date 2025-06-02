import streamlit as st
import requests
import os
import pandas as pd
from datetime import date

st.set_page_config(page_title="FedEx Rate Checker", layout="centered")

# --- Secrets via environment variables ---
CLIENT_ID = os.getenv("FEDEX_CLIENT_ID", "YOUR_FEDEX_CLIENT_ID")
CLIENT_SECRET = os.getenv("FEDEX_CLIENT_SECRET", "YOUR_FEDEX_CLIENT_SECRET")
ACCOUNT_NUMBER = os.getenv("FEDEX_ACCOUNT_NUMBER", "YOUR_FEDEX_ACCOUNT_NUMBER")

# --- Helper Functions ---

def get_transit_times(origin_zip, dest_zip):
    token = get_access_token()
    if not token:
        return {}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = {
        "accountNumber": {"value": ACCOUNT_NUMBER},
        "requestedShipment": {
            "shipper": {"address": {"postalCode": origin_zip, "countryCode": "US"}},
            "recipient": {"address": {"postalCode": dest_zip, "countryCode": "US"}},
            "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
            "shipDate": date.today().isoformat()
        }
    }

    try:
        response = requests.post("https://apis.fedex.com/transit/v1/transittimes", headers=headers, json=body)
        response.raise_for_status()
        data = response.json()
        commits = {}
        for option in data.get("output", {}).get("transitTimeDetails", []):
            service = option.get("serviceType")
            delivery = option.get("commitDate")
            if service and delivery:
                commits[service] = delivery
        return commits
    except requests.exceptions.RequestException as e:
        return {}

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

from datetime import date

def get_list_rates(origin_zip, dest_zip, weight_lb, length, width, height):
    token = get_access_token()
    if not token:
        return {"error": "Unable to get access token."}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = {
        "accountNumber": {"value": ACCOUNT_NUMBER},
        "shipDate": date.today().isoformat(),
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
                    },
                    "dimensions": {
                        "length": int(length),
                        "width": int(width),
                        "height": int(height),
                        "units": "IN"
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

def extract_selected_rates(response, transit_estimates):
    results = []
    rate_details = response.get("output", {}).get("rateReplyDetails", [])
    for item in rate_details:
        service_name = item.get("serviceName") or item.get("serviceType") or "Unknown Service"
        for detail in item.get("ratedShipmentDetails", []):
            charge = detail.get("totalNetFedExCharge")
            if not charge:
                shipment_detail = detail.get("shipmentRateDetail") or {}
                charge = shipment_detail.get("totalNetFedExCharge")

            if isinstance(charge, dict):
                amount = charge.get("amount")
                currency = charge.get("currency")
            elif isinstance(charge, (int, float)):
                amount = charge
                currency = "USD"
            else:
                amount = None
                currency = None

            if amount and currency:
                estimated = item.get("commit", {}).get("dateDetail", {}).get("estimatedDeliveryDateTime") or item.get("operationalDetail", {}).get("deliveryDate") or "N/A"
                delivery = transit_estimates.get(item.get("serviceType"), "Estimate unavailable")
                results.append({"Service": service_name, "Price": f"{amount} {currency}", "Estimated Delivery": delivery}).get("deliveryDate", "Estimate unavailable")})
    return results

# --- Streamlit UI ---
st.title("📦 FedEx Rate Checker")
st.markdown("Check retail (list) rates for FedEx Ground, 2Day, and Overnight services.")

with st.form("rate_form"):
    origin = st.text_input("From ZIP Code", value="53202")
    destination = st.text_input("To ZIP Code", value="90210")
    weight = st.number_input("Package Weight (lb)", min_value=0.1, value=10.0)
    length = st.number_input("Length (in)", min_value=1.0, value=10.0)
    width = st.number_input("Width (in)", min_value=1.0, value=10.0)
    height = st.number_input("Height (in)", min_value=1.0, value=10.0)
    submitted = st.form_submit_button("Get Rates")

if submitted:
    response = get_list_rates(origin, destination, weight, length, width, height)
    if "error" in response:
        st.error(response["error"])
    else:
        transit_estimates = get_transit_times(origin, destination)
        rates = extract_selected_rates(response, transit_estimates)
        if rates:
            st.success("Here are the available list rates:")
            df = pd.DataFrame(rates)
            df["Numeric"] = df["Price"].str.extract(r'(\d+\.\d+)').astype(float)
            df = df.sort_values(by="Numeric").drop(columns="Numeric")
            st.table(df.set_index("Service"))
        else:
            st.warning("No matching list rates returned for the specified inputs.")

        alerts = response.get("output", {}).get("alerts", [])
        if alerts:
            st.info("FedEx API Alerts:")
            for alert in alerts:
                code = alert.get("code")
                message = alert.get("message")
                st.write(f"- ({code}) {message}")

        with st.expander("See full FedEx API response"):
            try:
                st.json(response)
            except Exception:
                st.write("Raw response:")
                st.write(response)
