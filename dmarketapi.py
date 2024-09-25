import json
from datetime import datetime, timedelta
import time

from nacl.bindings import crypto_sign
import requests
import urllib3
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

import sqlite3
import numpy as np

# from pynput import keyboard
from pytz import utc

from furl import furl
from pydantic import BaseModel
import logging
from typing import List, Union


from credentials import PUBLIC_KEY, SECRET_KEY
from config import API_URL, API_URL_TRADING, db_path
from schemas import (
    Balance,
    Games,
    LastSales,
    LastSale,
    SalesHistory,
    MarketOffers,
    AggregatedTitle,
    UserTargets,
    ClosedTargets,
    Target,
    UserItems,
    CreateOffers,
    CreateOffersResponse,
    EditOffers,
    EditOffersResponse,
    DeleteOffers,
    CreateTargets,
    CumulativePrices,
    OfferDetails,
    OfferDetailsResponse,
    ClosedOffers,
)


# Globals
stop_thread = [False]



# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress only urllib3 warnings because my py has somewhat frequent DNS errors
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Set logging level to ERROR to suppress warnings
logging.getLogger("urllib3").setLevel(logging.ERROR)

def generate_headers(
    method: str, api_path: str, params: dict = None, body: dict = None
) -> dict:
    nonce = str(round(datetime.now().timestamp()))
    string_to_sign = method + api_path
    string_to_sign = str(furl(string_to_sign).add(params))
    if body:
        string_to_sign += json.dumps(body)
    string_to_sign += nonce
    signature_prefix = "dmar ed25519 "
    encoded = string_to_sign.encode("utf-8")
    signature_bytes = crypto_sign(encoded, bytes.fromhex(SECRET_KEY))
    signature = signature_bytes[:64].hex()
    headers = {
        "X-Api-Key": PUBLIC_KEY,
        "X-Request-Sign": signature_prefix + signature,
        "X-Sign-Date": nonce,
    }
    return headers


def api_call(
    url: str,
    method: str,
    headers: dict,
    params: dict = None,
    body: dict = None,
    aio: bool = True,
) -> dict:

    session = requests.Session()
    retry = Retry(
        total=20,  # Number of retries
        backoff_factor=1,  # Time to wait between retries
        status_forcelist=[403, 500, 502, 503, 504],  # Retry on these status codes
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    backoff_time = 5  # Initial backoff time in seconds

    while True:
        try:
            if method == "GET":
                response = session.get(
                    url, params=params, headers=headers, timeout=30
                )  # Increase timeout if needed
            elif method == "POST":
                response = session.post(
                    url, json=body, headers=headers, timeout=10
                )  # Example for POST request
            elif method == "PATCH":
                response = session.patch(url, json=body, headers=headers, timeout=10)
            response.raise_for_status()  # Raise an exception for HTTP errors

            # Print rate limit headers
            rate_limit_remaining = int(response.headers.get("RateLimit-Remaining", 1))
            rate_limit_reset = int(response.headers.get("RateLimit-Reset", 1))
            rate_limit_limit = int(response.headers.get("RateLimit-Limit", 1))
            # print("request start")
            # logger.info(f"Updated item: {params.get('title', 'Unknown Title')}")
            # print("X-RateLimit-Limit-Second:", response.headers.get("X-RateLimit-Limit-Second"))
            # print("X-RateLimit-Remaining-Second:", response.headers.get("X-RateLimit-Remaining-Second"))
            # print("RateLimit-Remaining:", rate_limit_remaining)
            # print("RateLimit-Limit:", rate_limit_limit)
            # print("RateLimit-Reset:", rate_limit_reset)
            # print("request end")

            # Fallback mechanism for missing headers
            if rate_limit_remaining is None or rate_limit_reset is None:
                rate_limit_remaining = 1
                rate_limit_reset = 1

            # Wait if rate limit is reached
            if rate_limit_remaining == 0:
                #print(f"Rate limit reached. Waiting for {rate_limit_reset} seconds...") #bloats the output only for debugging
                time.sleep(rate_limit_reset)

            # Check if response is empty
            if not response.text:
                print("Empty response received")
                return None

            return response.json()
        except requests.exceptions.HTTPError as e:
            if 400 <= response.status_code < 500:
                print(f"Client error: {e}")
                break  # Exit the loop for client errors in the 400 range
            #logger.info(f"Making API call with params: {params}")  # Log the parameters
            print(f"HTTP error: {e}")
        except requests.exceptions.Timeout as e:
            #logger.info(f"Making API call with params: {params}")  # Log the parameters
            print(f"Timeout error: {e}")
        except requests.exceptions.RequestException as e:
            #logger.info(f"Making API call with params: {params}")  # Log the parameters
            print(f"An error occurred: {e}")
            #print(f"Retrying in {backoff_time} seconds...")
            time.sleep(backoff_time)  # Wait before retrying
            backoff_time = min(
                backoff_time * 2, 300
            )  # Exponential backoff with a maximum wait time of 5 minutes


##############
# Endpoints   #
##############


# get offers from the market
def get_offer_from_market(min_item_price: int, max_item_price: int) -> List[dict]:
    url_path = "/exchange/v1/market/items"
    url = API_URL + url_path
    params = {
        "gameId": "a8db",
        "limit": 5,  # 5 if price filter / 10 if no price filter
        "offset": 0,
        "orderBy": "updated",
        "orderDir": "desc",
        "treeFilters": "",
        "currency": "USD",
        "priceFrom": min_item_price,
        "priceTo": max_item_price,
        "cursor": "",
    }
    method = "GET"
    headers = generate_headers(method, url_path, params)

    while True:
        try:
            # print("get_offer_from_market")
            response = api_call(url, method, headers, params)
            offers = response.get("objects", [])
            return offers
        except requests.exceptions.RequestException as e:
            print(f"An error occurred in fetching new items: {e}")
            time.sleep(60)  # Wait for 1 minute before retrying


# Endpoint for receiving a response for recent sales.
# test last_sales
def last_sales(
    gameId: str,
    title: str,
    limit: str,
    offset: str = "0",
    start_date: datetime = None,
    end_date: datetime = None,
) -> LastSales:
    """Method for receiving and processing a response for recent sales."""

    method = "GET"
    params = {"gameId": gameId, "title": title, "limit": limit, "offset": offset}
    url_path = "/trade-aggregator/v1/last-sales"
    headers = generate_headers(method, url_path, params)
    url = API_URL_TRADING + url_path
    response = api_call(url, method, headers, params)
    if not response or "sales" not in response:
        print(f"Invalid response for title: {title}")
        return LastSales(sales=[])

    sales = LastSales(**response)

    if start_date is not None:
        start_date = start_date.replace(tzinfo=utc)
        sales.sales = [sale for sale in sales.sales if sale.date >= start_date]

    if end_date is not None:
        end_date = end_date.replace(tzinfo=utc)
        sales.sales = [sale for sale in sales.sales if sale.date <= end_date]

    return sales


# Endpoint to get offers for one title


def offers_by_title(title: str, limit: str) -> tuple:
    method = "GET"
    cursor = ""
    all_offers = []

    while True:
        params = {"title": title, "limit": limit, "Cursor": cursor}
        url_path = "/exchange/v1/offers-by-title"
        headers = generate_headers(method, url_path, params)
        url = API_URL_TRADING + url_path

        try:
            response = api_call(url, method, headers, params)
            if response is None:
                logging.error(f"Failed to get response for title: {title}")
                break

            market_offers = response.get("objects", [])
            all_offers.extend(market_offers)

            if "cursor" in response and response["cursor"] and len(all_offers) >= 100:
                #print(
                #    f"second api request for {title } was needed, because number of offers was {len(all_offers)}"
                #) #bloats the output only for debugging
                cursor = response["cursor"]
            else:
                break
        except Exception as e:
            logging.error(f"Error fetching offers for title {title}: {e}")
            break

    return all_offers, cursor


def buy_item(offer_id: str, price: float) -> dict:
    method = "PATCH"
    url_path = "/exchange/v1/offers-buy"
    body = build_buy_body_from_offer(offer_id, price)
    headers = generate_headers(method, url_path, body=body)
    url = API_URL_TRADING + url_path
    response = api_call(url, method, headers, body=body)
    print(response)
    # Extracting only the required fields
    result = {"orderId": response.get("orderId"), "status": response.get("status")}
    return result


# endpoint to get balance in usd/cents
def balance():
    method = "GET"
    url_path = "/account/v1/balance"
    headers = generate_headers(method, url_path)
    url = API_URL_TRADING + url_path
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        usd_balance = data.get("usd", 0)
        return usd_balance
    else:
        print(f"Failed to get balance: {response.status_code}")
        return None


def get_inventory(timestamp_to_set):
    print("get_inventory startet")  # delete
    set_timestamp = timestamp_to_set
    all_items = []
    offset = 0

    method = "GET"
    params = {
        "gameId": "a8db",
        "currency": "USD",
        "BasicFilters.InMarket": True,
        "offset": offset,
        "Limit": 50,
    }
    url_path = "/marketplace-api/v1/user-inventory"
    url = API_URL_TRADING + url_path

    while True:
        for attempt in range(6):  # Try up to 6 times
            headers = generate_headers(method, url_path, params)
            response = requests.get(url, params=params, headers=headers)

            if response.status_code == 200:
                break
            else:
                print(
                    f"Attempt {attempt + 1}: Received status code {response.status_code}"
                )
                if attempt < 5:
                    time.sleep(2)  # Wait for 2 seconds before retrying
                else:
                    print("Max retries reached. Exiting.")
                    return all_items

        try:
            data = response.json()
            print(f"data: {data}")# to delete
        except ValueError:
            print("Error: Unable to parse JSON response")
            print("Response text:", response.text)
            break
        # Check if 'objects' key exists in the response data
        if "Items" not in data:
            print("Key 'objects' not found in response data")
            break

        # Extract classId and title
        for item in data["Items"]:
            class_id = item.get("ClassID")
            timed_classId_listings = f"{set_timestamp}_{class_id}"
            title = item.get("Title")
            asset_id = item.get("AssetID")
            
            
            all_items.append(
                {
                    "timed_classId_listings": timed_classId_listings,
                    "title": title,
                    "assetId": asset_id,
                }
            )

            # Check if the item already exists in the listings table
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                SELECT COUNT(*) FROM listings WHERE timed_classId_listings = ?
                """,
                    (timed_classId_listings,),
                )
                count = cursor.fetchone()[0]
                print(f" count: {count}, title: {title}")  # delete
                print(f"listings Table trying to add: {title}")
                if count == 0:
                    # Insert into listings table if the item does not exist
                    cursor.execute(
                        """
                    INSERT INTO listings (timed_classId_listings, title, assetId)
                    VALUES (?, ?, ?)
                    """,
                        (timed_classId_listings, title, asset_id),
                    )
                    conn.commit()
                    print(f"Item inserted: {title}")  # delete

                # Transfer buy_price and prob_sell_price if classId matches
                cursor.execute(
                    """
                SELECT buy_price, prob_sell_price FROM bought_items WHERE timed_classId = ?
                """,
                    (timed_classId_listings,),
                )
                result = cursor.fetchone()

                if result:
                    buy_price, prob_sell_price = result
                    buy_price = round(buy_price / 100, 2)
                    prob_sell_price = round(prob_sell_price / 100, 2)
                    cursor.execute(
                        """
                    UPDATE listings
                    SET buy_price = ?, sell_price = ?
                    WHERE timed_classId_listings = ?
                    """,
                        (buy_price, prob_sell_price, timed_classId_listings),
                    )
                    conn.commit()
                    print(f"Item parameters transfered: {title}")  # delete

        # Check if the total number of items is less than or equal to 100
        if int(data["Total"]) <= 100:
            print("no loop needed")
            break

        # Increment the offset for the next request
        offset += 100
        print("loop needed")

        params["offset"] = offset


def get_fee():
    method = "GET"
    params = {"gameId": "a8db", "offerType": "dmarket", "limit": 15000}
    url_path = "/exchange/v1/customized-fees"
    headers = generate_headers(method, url_path, params)
    url = API_URL_TRADING + url_path
    response = requests.get(url, params=params, headers=headers)
    
    
    if response.status_code != 200:
        print(f"Error: Received status code {response.status_code}")
        return
    
    data = response.json()

    if "reducedFees" not in data:
        print("Key 'reducedFees' not found in the response")
        return

    reduced_fees = data["reducedFees"]

    # Create or connect to the database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()


    '''
    # Create the table if it doesn't exist
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reduced_fees (
            title TEXT PRIMARY KEY,
            fraction REAL,
            expiresAt INTEGER
        )
    """
    )
    '''
    # Collect all new titles
    new_titles = {fee["title"] for fee in reduced_fees}

    # Delete old data that is not in the new request
    cursor.execute(
        """
        DELETE FROM reduced_fees
        WHERE title NOT IN ({})
    """.format(
            ",".join("?" for _ in new_titles)
        ),
        tuple(new_titles),
    )

    # Insert or update data
    for fee in reduced_fees:
        cursor.execute(
            """
            INSERT OR REPLACE INTO reduced_fees (title, fraction, expiresAt)
            VALUES (?, ?, ?)
        """,
            (fee["title"], fee["fraction"], fee["expiresAt"]),
        )

    conn.commit()
    conn.close()


def create_target(body: CreateTargets):
    method = "POST"
    url_path = "/marketplace-api/v1/user-targets/create"
    headers = generate_headers(
        method, url_path, body=body.model_dump()
    )  # body.model_dump war vorher body.dict
    url = API_URL + url_path
    response = api_call(url, method, headers, body=body.model_dump())
    return response

def get_user_offers():
    url_path = "/marketplace-api/v1/user-offers"
    params = {"gameId": "a8db", "offerType": "dmarket", "limit": 100}
    method = "GET"
    headers = generate_headers(method, url_path, params)
    url = API_URL_TRADING + url_path
    response = requests.get(url, params=params, headers=headers)
    

    

def sell_item():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timed_classId_listings, assetId, sell_price FROM listings WHERE status = 'in_inventory'"
        )
        listings = cursor.fetchall()

    url_path = "/marketplace-api/v1/user-offers/create"
    method = "POST"
    for listing in listings:
        timed_classId, assetId, sell_price = listing
        # Skip if sell_price is NULL and update status to 'listing_error'
        if sell_price is None:
            cursor.execute(
                "UPDATE listings SET status = ? WHERE timed_classId_listings = ?",
                ("listing_error", timed_classId),
            )
            conn.commit()
            print("fehler kein preis")
            continue

        body = build_sell_body_from_offer(assetId, sell_price)
        headers = generate_headers(method, url_path, body=body)
        url = API_URL_TRADING + url_path
        response = api_call(url, method, headers, body=body)
        print(response)

        if response["Result"][0]["Successful"]:
            print("erfolgreich")
            cursor.execute(
                "UPDATE listings SET status = ? WHERE timed_classId_listings = ?",
                ("listed", timed_classId),
            )
            cursor.execute(
                "UPDATE bought_items SET status = ? WHERE timed_classId = ?",
                ("listed", timed_classId),
            )
            conn.commit()
        else:
            print("fehlgeschlagen")
            cursor.execute(
                "UPDATE listings SET status = ? WHERE timed_classId_listings = ?",
                ("listing_error", timed_classId),
            )
            cursor.execute(
                "UPDATE bought_items status = ? WHERE timed_classId = ?",
                ("listing_error", timed_classId),
            )
            conn.commit()


# def alter_listing()


##############
# output processes#
##############


def get_discount_fraction(offer_title):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT fraction FROM reduced_fees WHERE title = ?", (offer_title,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0.10  # Return 1.0 if no discount found


def markdown_items():
    one_week_ago = datetime.now() - timedelta(weeks=1)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Fetch items from bought_items table older than 1 week
        cursor.execute(
            """
            SELECT timed_classId, title, buy_price FROM bought_items WHERE timestamp < ?
        """,
            (one_week_ago.strftime("%Y-%m-%d %H:%M:%S"),),
        )
        old_items = cursor.fetchall()
        print(f"old items: {old_items}")  # delete

        for timed_classId, title, buy_price in old_items:
            # Fetch the current sell price from listings table
            cursor.execute(
                """
                SELECT sell_price FROM listings WHERE timed_classId_listings = ?
            """,
                (timed_classId,),
            )
            result = cursor.fetchone()
            if result is None:
                continue
            print(f"result {result}")
            sell_price = result[0]
            sell_price = sell_price * 100
            print(f" sell price {sell_price}")

            # Fetch and parse the offers_of_title field from the sales table
            cursor.execute(
                """
                SELECT offers_of_title FROM sales WHERE title = ?
            """,
                (title,),
            )
            sales_items = cursor.fetchone()
            if sales_items is None:
                continue
            offers_of_title = sales_items[0].split(", ")
            print(f"offers_of_title: {offers_of_title}")  # Debugging

            # Count the number of offers below the current item's sell price
            count_below = sum(
                1 for price in offers_of_title if float(price) < sell_price
            )
            print(f"count below: {count_below}")  # Debugging

            if count_below >= 4:
                # Calculate profit margin

                new_sell_price = max(sell_price * 0.95, buy_price * 1.15)
                new_sell_price_listings = round(new_sell_price / 100, 2)

                fee = get_discount_fraction(title)
                prob_profit = (
                    float(new_sell_price) - fee * float(new_sell_price)
                ) - float(buy_price)

                profit_margin = (prob_profit * 100) / buy_price
                print(f" profit margin: {profit_margin}")  # delete

                if profit_margin < 15:
                    profit_margin = 15
                    new_sell_price = buy_price * 1.15
                    new_sell_price_listings = round(new_sell_price / 100, 2)
                    prob_profit = (
                        float(new_sell_price) - fee * float(new_sell_price)
                    ) - float(buy_price)
                    print(
                        f"profit margin of {title} is now {profit_margin}%, the new sell price is: {new_sell_price}, the new prob profit is {prob_profit}"
                    )

                if profit_margin >= 15:
                    # Adjust price down by 5% profit but do not go below a profit margin of 15%

                    # Update the sell price in listings table
                    cursor.execute(
                        """
                        UPDATE listings SET sell_price = ? WHERE timed_classId_listings = ?
                    """,
                        (new_sell_price_listings, timed_classId),
                    )
                    conn.commit()

                    # Update prob_sell_price and prob_profit in bought_items table
                    cursor.execute(
                        """
                        UPDATE bought_items SET prob_sell_price = ?, prob_profit = ?, timestamp = ? WHERE timed_classId = ?
                        """,
                        (new_sell_price, prob_profit, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), timed_classId),
                    )

                    conn.commit()

                    print(
                        f"Updated sell price for {title} to {new_sell_price_listings}"
                    )
                    print(
                        f"Updated prob_sell_price to {new_sell_price} and prob_profit to {prob_profit}"
                    )
    


def build_buy_body_from_offer(offer_id: str, price: float):
    return {
        "offers": [
            {
                "offerId": offer_id,
                "price": {"amount": str(price), "currency": "USD"},
                "type": "dmarket",
            }
        ]
    }


def build_sell_body_from_offer(AssetID: str, price: float):
    return {
        "Offers": [{"AssetID": AssetID, "Price": {"Currency": "USD", "Amount": price}}]
    }


def build_target_body_from_offer(offer):
    return {
        "targets": [
            {
                "amount": 1,
                "gameId": offer["gameId"],
                "price": {"amount": "2", "currency": "USD"},
                "attributes": {
                    "gameId": offer["gameId"],
                    "categoryPath": offer["extra"]["categoryPath"],
                    "title": offer["title"],
                    "name": offer["title"],
                    "image": offer["image"],
                    "ownerGets": {"amount": "1", "currency": "USD"},
                },
            }
        ]
    }


def format_offer(
    offer: dict,
    avg_last_20_sales: float,
    avg_week: float,
    discount_rate: float,
    prob_profit: float,
    prob_sell_price: float,
    buy_response: str,
) -> dict:
    formatted_offer = {
        "createdAt": datetime.fromtimestamp(offer["createdAt"]).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "title": offer["title"].encode("ascii", "ignore").decode(),
        "price (USD)": offer["price"]["USD"],
        "avg_last_20_sales (USD)": round(float(avg_last_20_sales), 2),
        "avg_week (USD)": round(float(avg_week), 2),
        "discount_rate (%)": round(discount_rate, 2),
        "prob_profit (USD)": round(prob_profit, 2),
        "prob_sell_price (USD)": round(prob_sell_price, 2),
        "offerId": offer["extra"]["offerId"],
        "buy_response": buy_response,
    }
    return formatted_offer


# Method for processing a response for recent sales.
def get_combined_sales(
    title: str, limit: str, start_date: datetime = None
) -> LastSales:
    sales1 = last_sales("a8db", title, limit, "0", start_date)
    sales2 = last_sales("a8db", title, limit, "500", start_date)

    combined_sales = LastSales(sales=sales1.sales + sales2.sales)
    return combined_sales


# Method for processing a response for recent sales.
def filter_outliers(sales: List[LastSale]) -> List[LastSale]:
    if not sales:
        return []

    prices = [float(sale.price) for sale in sales]
    q1 = np.percentile(prices, 25)
    q3 = np.percentile(prices, 75)
    iqr = q3 - q1
    lower_bound = q1 - 0.3 * iqr
    upper_bound = q3 + 0.3 * iqr
    # print(f"lower Bound {lower_bound} + upper bound {upper_bound}")
    return [sale for sale in sales if lower_bound <= float(sale.price) <= upper_bound]


def calculate_prob_profit(offer, discount: float, min_avg_price: float, fee: float):
    # fee = get_discount_fraction(offer['title'])
    print(f" Fee: {fee}")
    print(f"avg min: {min_avg_price}")
    if discount < 12:
        prob_sell_price = (
            min_avg_price * 1.06
        )  # (discount_goal / 100) = Adds Discount goal ass markup / old = * 1.1 / Add 10% to min_avg_price
    else:
        prob_sell_price = min_avg_price * 1.10
    prob_profit = (prob_sell_price - fee * prob_sell_price) - float(
        offer["price"]["USD"]
    )
    return prob_sell_price, prob_profit


# to alter an sell_price in the listings table
def update_sell_price(class_id, new_sell_price):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
        UPDATE listings
        SET sell_price = ?
        WHERE timed_classId_listings = ?
        """,
            (new_sell_price, class_id),
        )
        conn.commit()


# Example usage #delete
# update_sell_price('188530170:5721079599', 'NULL') #delete


def delte_listing_errors():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM listings WHERE status = 'listing_error'")
        conn.commit()


#               #
#   Database    #
#               #


def create_sales_table():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS sales (
            title TEXT PRIMARY KEY,
            last_update TEXT NOT NULL,
            avg_min REAL NOT NULL,
            avg_week REAL NOT NULL,
            avg_month REAL NOT NULL,
            avg_all_time REAL NOT NULL,
            sales_month INTEGER NOT NULL,
            avg_last_20_sales TEXT NOT NULL,
            offers_of_title INTEGER DEFAULT 0
        )
        """
        )
        conn.commit()


def create_bought_items_table():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS bought_items (
            timed_classId TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            buy_price REAL NOT NULL,
            prob_sell_price REAL NOT NULL,
            prob_profit REAL NOT NULL,
            status TEXT NOT NULL               
        )
        """
        )
        conn.commit()


def create_listings_table():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS listings (
            timed_classId_listings TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'in_inventory',
            buy_price REAL DEFAULT NULL,
            sell_price REAL DEFAULT NULL, 
            assetId TEXT DEFAULT NULL
        )
        """
        )
        conn.commit()


def create_reduced_fees_table():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reduced_fees (
            title TEXT PRIMARY KEY,
            fraction REAL,
            expiresAt INTEGER
        )
    """
    )
    conn.commit()
    conn.close()
