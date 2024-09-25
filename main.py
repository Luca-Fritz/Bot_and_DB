import json
import time
import os
from datetime import datetime, timedelta
import sqlite3  # Using SQLite for the database

from credentials import PUBLIC_KEY, SECRET_KEY
from config import API_URL, url_get_items, timestamp, offer_list_directory, no_data_titles_path, db_path
from dmarketapi import offers_by_title, filter_outliers, get_offer_from_market, format_offer, balance, buy_item, create_bought_items_table, create_listings_table, create_reduced_fees_table, get_inventory, get_discount_fraction, calculate_prob_profit, get_fee 

# How much should a skin be discounted? Fee is 10%
discount_goal = 14

min_item_price = 100
max_item_price = 5000

max_offers_below_buy_price = 2 #2

min_sales_per_month = 20 #20
offers = get_offer_from_market(min_item_price, max_item_price)

time_to_run_script = 5 #1 = 1H, 0.1 = 10 Min, 0.01 = 1 Min 

#Ensure the table exists
create_bought_items_table()
create_listings_table()
create_reduced_fees_table()

#Create / Update the Fee Table
get_fee()

class MarketOffers:
    def __init__(self):
        self.all_offers = []
        self.processed_offers = set()  # Set to keep track of processed offers
        self.stop_thread = False
        self.bad_words = ['key', 'pin', 'sticker', 'case', 'operation', 'pass', 'capsule', 'package', 'challengers', 'patch', 'music', 'kit', 'graffiti', 'contenders']
        self.conn = sqlite3.connect(db_path)  # Connect to the database
        self.cursor = self.conn.cursor()
        self.no_data_titles = set()  # Set to keep track of titles with no data


    def sort_by_date(self, offers):
        return sorted(offers, key=lambda x: x["createdAt"], reverse=True)

    def get_item_data_from_db(self, title):
        self.cursor.execute("SELECT avg_min, avg_week, avg_month, avg_all_time, sales_month, avg_last_20_sales, offers_of_title FROM sales WHERE title = ?", (title,))
        return self.cursor.fetchone()

    def save_no_data_titles(self):
            with open(no_data_titles_path, "w", encoding='utf-8') as file:  # Use the new path
                file.write(", ".join(self.no_data_titles))
            print(f"missing entrys saved to: {no_data_titles_path}")

    def get_balance_with_retry(self, max_retries=10):
        retries = 0
        while retries < max_retries:
            current_balance = balance()
            if current_balance is not None:
                return current_balance
            retries += 1
            print(f"Balance request failed. Retrying {retries}/{max_retries}...")
            time.sleep(1)  # Wait for 1 second before retrying
        print("Failed to retrieve balance after multiple attempts.")
        return None    

    def insert_bought_item(self, classId, title, timestamp, buy_price, prob_sell_price, prob_profit, status):
        timestamp = timestamp
        timed_classId = f"{timestamp}_{classId}"
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO bought_items (timed_classId, title, timestamp, buy_price, prob_sell_price, prob_profit, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (timed_classId, title, timestamp, buy_price, prob_sell_price, prob_profit, status))
            conn.commit()
        get_inventory(timestamp)

    

    def process_offers_with_pagination(self):
        start_time = time.time()  # Start the timer
        dup_offer_count = 0
        offer_count = 0
        while not self.stop_thread:
            current_time = time.time()
            elapsed_time = current_time - start_time
            if elapsed_time > time_to_run_script * 60 * 60:  # Stop after the specified time
                break


            offers = get_offer_from_market(min_item_price, max_item_price)  # Call the function directly

            for offer in offers:
                #offer_count += 1
                offer_key = offer['extra']['offerId']
                if offer_key in self.processed_offers:
                    #dup_offer_count += 1
                    #print(f"duplicate percentage: {(dup_offer_count / offer_count) * 100}%")
                    continue  # Skip already processed offers
                self.processed_offers.add(offer_key)  # Add the offer to the set of processed offers

                if any(bad_word in offer['title'].lower() for bad_word in self.bad_words):
                    continue  # Skip offers with bad words in the title

                # Get item data from the database
                item_data = self.get_item_data_from_db(offer['title'])
                if not item_data:
                    self.no_data_titles.add(offer['title'])  # Add title to the set
                    #print(f"Title: {offer['title']}, Price: {float(offer['price']['USD'])} Nicht in DB")
                    continue  # Skip if no data found in the database

                avg_min, avg_week, avg_month, avg_all_time, sales_month, avg_last_20_sales, offers_of_title_str = item_data

                min_avg_price = min(float(avg_last_20_sales), float(avg_week)) 

                fee = float(get_discount_fraction(offer['title']))

                if min_avg_price != 0:
                    discount_rate = ((min_avg_price - float(offer["price"]["USD"])) / min_avg_price) * 100
                    discount_rate = round(discount_rate, 2)
                    if fee < 0.1:
                        discount_to_add = 10 - (fee * 100)
                        discount_to_add = round(discount_to_add, 2)
                        discount_rate = discount_rate + discount_to_add
                    if discount_rate < discount_goal:
                        continue  # Skip offers with a discount rate less than the goal
                

                # Get all offers for a given offer from the database
                if isinstance(offers_of_title_str, str):
                    offers_of_title_list = [float(price) for price in offers_of_title_str.split(', ') if price.strip()]
                    #hier muss ein offers_below_sell_price rein
                    offers_below_buy_price = [price for price in offers_of_title_list if price < float(offer["price"]["USD"])]
                else:
                    offers_below_buy_price = []

                if sales_month >= min_sales_per_month and len(offers_below_buy_price) <= max_offers_below_buy_price and min_avg_price != 0: #offers_below_sell_price hier integrieren

                    prob_sell_price, prob_profit = calculate_prob_profit(offer, discount_rate, min_avg_price, fee)

                    print(f"Title: {offer['title']}, Price: {float(offer['price']['USD'])}")
                    print(f"Discount rate: {discount_rate:.2f}%")
                    print(f"Probable sell price: {prob_sell_price}, probable profit in cents with fee: {prob_profit}")
                    print(f"Average price for last 20 sales: {avg_last_20_sales}")
                    print(f"Average sales last week: {avg_week}")
                    print("Amount below offers: " + str(len(offers_below_buy_price)))
                    
            
                    print("Start Buy Check")
                    
                     # Check balance before buying
                    current_balance = self.get_balance_with_retry()
                    if current_balance is not None and float(current_balance) >= float(offer['price']['USD']):
                        # Call the buy_item function
                        buy_response = buy_item(offer['extra']['offerId'], float(offer['price']['USD']))
                        print(f"Buy response: {buy_response}")

                        if buy_response['status'] == 'TxSuccess':
                        
                        
                        # Insert bought item data into the new table
                            status = "bought"
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            print(f"insert params classId: {offer['classId']}, Title: {offer['title']}, Timestamp: {timestamp}, offer Price: {float(offer['price']['USD'])}, Prob sell price: {prob_sell_price}, prob prof: {prob_profit}, status: {status}")
                            self.insert_bought_item(offer['classId'], offer['title'], timestamp, float(offer['price']['USD']), prob_sell_price, prob_profit, status) 
                            response = buy_response['status']
                        else:
                            print(f"Transfer not successfull: {buy_response['status']}")
                            response = buy_response['status']
                        
                    else:
                        print("Insufficient balance to buy the item or failed to retrieve balance.")
                        response = "not successfull"
                    print("--Offer End--")
                    
                    formatted_offer = format_offer(offer, float(avg_last_20_sales), float(avg_week), discount_rate, prob_profit, prob_sell_price,  response)
                    self.all_offers.append(formatted_offer)
                    #print(f"dup offer count: {dup_offer_count}")
                    
            time.sleep(0.5)


    def save_offers(self):
        if not self.all_offers:
            print("No offers to save.")
            self.save_no_data_titles()  # Save titles with no data
            return

        sorted_all_offers = self.sort_by_date(self.all_offers)
        with open(os.path.join(offer_list_directory, f"sorted_offers_{timestamp}.txt"), "w", encoding='utf-8') as file:
            for offer in sorted_all_offers:
                file.write(json.dumps(offer) + "\n")
        print(f"Offers saved to {os.path.join(offer_list_directory, f'sorted_offers_{timestamp}.txt')}")
        self.save_no_data_titles()  # Save titles with no data

if __name__ == "__main__":
    market_offers = MarketOffers()
    market_offers.process_offers_with_pagination()
    market_offers.save_offers()
