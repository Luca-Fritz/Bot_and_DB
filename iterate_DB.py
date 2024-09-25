import sqlite3
import concurrent.futures
import signal
import threading
from datetime import datetime, timedelta, timezone
from dmarketapi import last_sales, filter_outliers, offers_by_title, create_sales_table
from config import no_data_titles_path, db_path
import time
import logging

# Configuration
refresh_time_in_h = 0.5
bad_words = ['key', 'pin', 'sticker', 'case', 'operation', 'pass', 'capsule', 'package', 'challengers', 'patch', 'music', 'kit', 'graffiti', 'contenders']

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

stop_event = threading.Event()

def signal_handler(sig, frame):
    logger.info('You pressed Ctrl+C!')
    stop_event.set()

signal.signal(signal.SIGINT, signal_handler)

# Shared counter and lock
total_updated_items = 0
counter_lock = threading.Lock()

create_sales_table()

def update_item(title_tuple):
    global total_updated_items
    if stop_event.is_set():
        return 0  # Exit if stop_event is set
    title, last_update, avg_min, avg_week, avg_month, avg_all_time, sales_month, avg_last_20_sales, offers_of_title = title_tuple

    if not title.strip():  
        logger.info(f"Skipping blank title")
        return 0
    
    if any(bad_word in title.lower() for bad_word in bad_words):
        logger.info(f"Skipping title with bad word: {title}")
        return 0  # Skip titles with bad words

    try:
        # Fetch all sales data in a single request
        combined_sales_all_time = last_sales("a8db", title, 500, "0", datetime.min.replace(tzinfo=timezone.utc))
        

        # Filter sales data locally
        one_week_ago = datetime.now(timezone.utc) - timedelta(weeks=1)
        one_month_ago = datetime.now(timezone.utc) - timedelta(weeks=4)

        filtered_sales_week = [sale for sale in combined_sales_all_time.sales if sale.date >= one_week_ago]
        filtered_sales_month = [sale for sale in combined_sales_all_time.sales if sale.date >= one_month_ago]
        filtered_sales_all_time = combined_sales_all_time.sales

        new_sales_month = len(filtered_sales_month)

        # Convert prices from last_sales to cents

        # Apply the filter_outliers function
        filtered_sales_week = filter_outliers(filtered_sales_week)
        filtered_sales_month = filter_outliers(filtered_sales_month)
        filtered_sales_all_time = filter_outliers(filtered_sales_all_time)

        new_avg_week = round(sum(float(sale.price) * 100 for sale in filtered_sales_week) / len(filtered_sales_week), 2) if filtered_sales_week else 0
        new_avg_month = round(sum(float(sale.price) * 100 for sale in filtered_sales_month) / len(filtered_sales_month), 2) if filtered_sales_month else 0
        new_avg_all_time = round(sum(float(sale.price) * 100 for sale in filtered_sales_all_time) / len(filtered_sales_all_time), 2) if filtered_sales_all_time else 0

        avg_values = [avg for avg in [new_avg_week, new_avg_month] if avg > 0]
        new_avg_min = round(min(avg_values), 2) if avg_values else 0

        

        sorted_sales = sorted(filtered_sales_all_time, key=lambda sale: sale.date, reverse=True)
        most_recent_20_sales = sorted_sales[:20]

        if most_recent_20_sales:
            new_avg_recent_20_sales = round(sum(float(sale.price) * 100 for sale in most_recent_20_sales) / len(most_recent_20_sales), 2)
        else:
            new_avg_recent_20_sales = 0

        new_avg_recent_20_sales_str = str(new_avg_recent_20_sales)

        # Process offers data without caching
        offers_by_title_list, cursor = offers_by_title(title, "100")
        new_offers_prices = sorted([str(float(o['price']['USD'])) for o in offers_by_title_list]) #new_offers_prices = sorted([str(float(o['price']['USD']) / 100) for o in offers_by_title_list])
        new_offers_of_title = ', '.join(new_offers_prices)
        
        # Convert the prices to float for sorting
        sorted_offers = sorted([float(price) for price in new_offers_prices])
        
        # Convert back to string for saving to the database
        sorted_offers_str = ', '.join([str(price) for price in sorted_offers])

        with sqlite3.connect(db_path) as conn: 
        #with sqlite3.connect('sales_data.db') as conn:
        #with sqlite3.connect('/home/gira/Bot_and_DB/sales_data.db') as conn:  # Use the full path to your database file on pi
            db_cursor = conn.cursor()
            db_cursor.execute('''
                UPDATE sales SET
                    last_update = ?,
                    avg_min = ?,
                    avg_week = ?,
                    avg_month = ?,
                    avg_all_time = ?,
                    sales_month = ?,
                    avg_last_20_sales = ?,
                    offers_of_title = ?
                WHERE title = ?
            ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), new_avg_min, new_avg_week, new_avg_month, new_avg_all_time, new_sales_month, new_avg_recent_20_sales_str, sorted_offers_str, title))
            conn.commit()
            #logger.info(f"Database updated for item: {title}") #bloats the output only for debugging
        #logger.info(f"Updated item: {title}") #bloats the output only for debugging

        # Increment the shared counter
        with counter_lock:
            total_updated_items += 1

        return 1
    except Exception as e:
        logger.error(f"Error updating item {title}: {e}")
    return 0  # Return 0 if there was an error to not count the item as processed


def update_sales_data():
    global total_updated_items
    with sqlite3.connect(db_path) as conn: 
    #with sqlite3.connect('sales_data.db') as conn:
    #with sqlite3.connect('/home/gira/Bot_and_DB/sales_data.db') as conn:  # Use the full path to your database file on pi
        db_cursor = conn.cursor()
        
        refresh_time = datetime.now() - timedelta(hours=refresh_time_in_h)
        db_cursor.execute('SELECT title, last_update, avg_min, avg_week, avg_month, avg_all_time, sales_month, avg_last_20_sales, offers_of_title FROM sales WHERE last_update < ?', (refresh_time.strftime('%Y-%m-%d %H:%M:%S'),))
        titles = db_cursor.fetchall()
    
    if not titles:
        logger.info("All Items up to date!")
        return

    total_updated_items = 0
    start_time = time.time()  # Start the timer

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_title = {executor.submit(update_item, title_tuple): title_tuple for title_tuple in titles}
        for future in concurrent.futures.as_completed(future_to_title):
            if stop_event.is_set():
                break
            try:
                future.result()
            except Exception as exc:
                logger.error(f'Generated an exception: {exc}')

        # Wait for all threads to complete
        executor.shutdown(wait=True)

    end_time = time.time()  # End the timer
    total_time = end_time - start_time
    average_time_per_item = total_time / total_updated_items if total_updated_items > 0 else 0

    logger.info(f"Total updated items: {total_updated_items}")
    logger.info(f"Total time taken: {total_time:.2f} seconds")
    logger.info(f"Average time per item: {average_time_per_item:.2f} seconds")

    


def add_titles_from_file():
    with open(no_data_titles_path, 'r', encoding='utf-8') as file:
        titles = file.read().split(', ')
        
    with sqlite3.connect(db_path) as conn: 
    #with sqlite3.connect('sales_data.db') as conn:
    #with sqlite3.connect('/home/gira/Bot_and_DB/sales_data.db') as conn:  # Use the full path to your database file on pi
        db_cursor = conn.cursor()
        
        for title in titles:
            if not title.strip():  
                continue
            
            db_cursor.execute('SELECT title FROM sales WHERE title = ?', (title,))
            result = db_cursor.fetchone()
            
            if not result:
                db_cursor.execute('''
                    INSERT INTO sales (title, last_update, avg_min, avg_week, avg_month, avg_all_time, sales_month, avg_last_20_sales, offers_of_title)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (title, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 0, 0, 0, 0, 0, '0', ''))
                logger.info(f"Added {title} to the database")

        conn.commit()

create_sales_table()  # Ensure the table exists
add_titles_from_file()  # Add titles from the file
update_sales_data()  # Update sales data

#remove blank titles from DB
"""
def delete_blank_titles():
    with sqlite3.connect('sales_data.db') as conn:
    #with sqlite3.connect('/home/gira/Bot_and_DB/sales_data.db') as conn:  # Use the full path to your database file on pi
        db_cursor = conn.cursor()
        db_cursor.execute("DELETE FROM sales WHERE TRIM(title) = ''")
        conn.commit()
        logger.info("Deleted entries with blank titles from the database")

delete_blank_titles()
"""
#removes titles given in a file
"""
def remove_titles_from_file():
    with open('no_data_titles_path', 'r') as file: #or when you only want to remove correctly fromated titles: with open('no_data_titles.txt', 'r', encoding='utf-8') as file: 
        titles = file.read().split(', ')
    
    conn = sqlite3.connect('sales_data.db')
    #conn = sqlite3.connect('/home/gira/Bot_and_DB/sales_data.db')  # Use the full path to your database file on pi
    db_cursor = conn.cursor()
    
    for title in titles:
        db_cursor.execute('SELECT title FROM sales WHERE title = ?', (title,))
        result = db_cursor.fetchone()
        
        if result:
            db_cursor.execute('DELETE FROM sales WHERE title = ?', (title,))
            print(f"Removed {title} from the database")
    
    conn.commit()
    conn.close()
"""


