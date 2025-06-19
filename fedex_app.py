import streamlit as st
import requests
import os
import pandas as pd
from datetime import date, timedelta
import numpy as np
import math

st.set_page_config(page_title="FedEx Rate Checker", layout="centered")

# --- Secrets via environment variables ---
CLIENT_ID = os.getenv("FEDEX_CLIENT_ID", "YOUR_FEDEX_CLIENT_ID")
CLIENT_SECRET = os.getenv("FEDEX_CLIENT_SECRET", "YOUR_FEDEX_CLIENT_SECRET")
ACCOUNT_NUMBER = os.getenv("FEDEX_ACCOUNT_NUMBER", "YOUR_FEDEX_ACCOUNT_NUMBER")

# --- Load ZIP code coordinates, supplier ZIPs, and product data ---
@st.cache_data
def load_zip_coords():
    zip_df = pd.read_csv("US Zip Codes.csv")
    zip_df["zip"] = zip_df["zip"].astype(str).str.zfill(5)
    return zip_df.set_index("zip")

def load_supplier_zips():
    df = pd.read_csv("TEST Supplier Code and Origin Zip.csv")
    df["supplier_code"] = df["supplier_code"].astype(str)
    df["zip"] = df["zip"].astype(str).str.zfill(5)
    return df.set_index("supplier_code")

@st.cache_data
def load_product_data():
    df = pd.read_csv("TEST SAMPLE All Products Shipping Info.csv", encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    df["Product Number"] = df["Product Number"].astype(str).str.strip()
    df["zip"] = df["zip"].astype(str).str.zfill(5)
    return df.set_index("Product Number")

zip_coords = load_zip_coords()
supplier_zips = load_supplier_zips()
product_data = load_product_data()
MARKUP_PERCENT = 0.10

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

def haversine(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def estimate_ground_transit_days(origin_zip, dest_zip):
    try:
        o = zip_coords.loc[str(origin_zip)]
        d = zip_coords.loc[str(dest_zip)]
        dist = haversine(o.lat, o.lng, d.lat, d.lng)
        if dist <= 150:
            return 1
        elif dist <= 450:
            return 2
        elif dist <= 1000:
            return 3
        elif dist <= 2000:
            return 4
        else:
            return 5
    except KeyError:
        return 5

def get_list_rates(origin_zip, dest_zip, origin_state, dest_state, weight_lb, length, width, height, token):
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
                    "stateOrProvinceCode": origin_state,
                    "countryCode": "US"
                }
            },
            "recipient": {
                "address": {
                    "postalCode": dest_zip,
                    "stateOrProvinceCode": dest_state,
                    "countryCode": "US",
                    "residential": False
                }
            },
            "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
            "packagingType": "YOUR_PACKAGING",
            "rateRequestType": ["LIST"],
            "requestedPackageLineItems": [
                {
                    "weight": {"units": "LB", "value": weight_lb},
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

def add_business_days(start_date, business_days):
    date_range = pd.bdate_range(start=start_date, periods=business_days + 1).tolist()
    return date_range[-1].date().isoformat()

def extract_selected_rates(response, origin_zip, dest_zip):
    results = []
    fixed_days_by_service = {
        "FIRST_OVERNIGHT": 1,
        "PRIORITY_OVERNIGHT": 1,
        "STANDARD_OVERNIGHT": 1,
        "FEDEX_2_DAY_AM": 2,
        "FEDEX_2_DAY": 2,
        "FEDEX_EXPRESS_SAVER": 3
    }

    rate_details = response.get("output", {}).get("rateReplyDetails", [])
    for item in rate_details:
        service_type = item.get("serviceType", "UNKNOWN")
        service_name = item.get("serviceName") or service_type

        if service_type == "FEDEX_GROUND":
            days = estimate_ground_transit_days(origin_zip, dest_zip)
        else:
            days = fixed_days_by_service.get(service_type, None)

        delivery_date = add_business_days(date.today(), days) if days else "Estimate unavailable"

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
                marked_up = round(amount * (1 + MARKUP_PERCENT), 2)
                results.append({
                    "Service": service_name,
                    "List Rate": f"{amount} {currency}",
                    "DS Rate": f"{marked_up} {currency}",
                    "Estimated Delivery": delivery_date
                })
    return results

# --- Streamlit UI ---
st.title("\U0001F4E6 FedEx Rate Checker")
st.markdown("Check retail (list) rates for FedEx Ground, 2Day, and Overnight services.")

with st.form("rate_form"):
    st.markdown("### Product Lookup")
    product_number = st.text_input("Product Number", value="0-00004")

    st.markdown("### Destination")
    col1, col2 = st.columns([2, 1])
    with col1:
        destination = st.text_input("To ZIP Code", value="90210")
    with col2:
        dest_state = st.text_input("To State Code", value="CA")

    submitted = st.form_submit_button("Get Rates")

if submitted:
    try:
        product = product_data.loc[product_number.strip()]
        supplier_code = product["SupplierCode"]
        origin = product["zip"]
        weight = float(product["Weight"])
        length = int(product["Length"])
        width = int(product["Width"])
        height = int(product["Height"])
        origin_state = zip_coords.loc[origin, "state_id"]

        token = get_access_token()
        if token:
            response = get_list_rates(origin, destination, origin_state, dest_state, weight, length, width, height, token)
            if "error" in response:
                st.error(response["error"])
            else:
                rates = extract_selected_rates(response, origin, destination)
                if rates:
                    st.success("Here are the available list rates:")
                    df = pd.DataFrame(rates)
                    df["Numeric"] = df["Marked Up Rate"].str.extract(r'(\d+\.\d+)').astype(float)
                    df = df.sort_values(by="Numeric").drop(columns="Numeric")
                    st.table(df[["Service", "List Rate", "DS Rate", "Estimated Delivery"]].set_index("Service"))
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
        else:
            st.error("Failed to get FedEx access token.")

    except KeyError:
        st.error(f"Product number '{product_number}' not found in product catalog.")
