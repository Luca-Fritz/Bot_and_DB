import json
from datetime import datetime
import time

from nacl.bindings import crypto_sign
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

import sqlite3
import numpy as np

#from pynput import keyboard 
from pytz import utc

from furl import furl
from pydantic import BaseModel
import logging
from typing import List, Union

from dmarketapi import create_bought_items_table, get_fee
from credentials import PUBLIC_KEY, SECRET_KEY
from config import API_URL, API_URL_TRADING, db_path
from schemas import Balance, Games, LastSales, LastSale, SalesHistory, MarketOffers, AggregatedTitle, \
    UserTargets, ClosedTargets, Target, UserItems, CreateOffers, CreateOffersResponse, EditOffers, EditOffersResponse, \
    DeleteOffers, CreateTargets, CumulativePrices, OfferDetails, OfferDetailsResponse, ClosedOffers


def add_new_columns():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('ALTER TABLE bought_items ADD COLUMN timed_classId TEXT')
        cursor.execute('ALTER TABLE listings ADD COLUMN timed_classId_listings TEXT')
        conn.commit()


def populate_new_columns():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Update bought_items table
        cursor.execute('SELECT classId, timestamp FROM bought_items')
        bought_items = cursor.fetchall()
        for classId, timestamp in bought_items:
            timed_classId = f"{timestamp}_{classId}"
            cursor.execute('UPDATE bought_items SET timed_classId = ? WHERE classId = ?', (timed_classId, classId))
        
        # Update listings table
        cursor.execute('SELECT classId_listings, title FROM listings')
        listings = cursor.fetchall()
        for classId_listings, title in listings:
            timed_classId_listings = f"{title}_{classId_listings}"
            cursor.execute('UPDATE listings SET timed_classId_listings = ? WHERE classId_listings = ?', (timed_classId_listings, classId_listings))
        
        conn.commit()

def update_primary_keys():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Create new bought_items table
        cursor.execute('''
        CREATE TABLE new_bought_items (
            timed_classId TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            buy_price REAL NOT NULL,
            prob_sell_price REAL NOT NULL,
            prob_profit REAL NOT NULL,
            status TEXT NOT NULL
        )
        ''')
        
        # Copy data to new bought_items table
        cursor.execute('''
        INSERT INTO new_bought_items (timed_classId, classId, title, timestamp, buy_price, prob_sell_price, prob_profit, status)
        SELECT timed_classId, classId, title, timestamp, buy_price, prob_sell_price, prob_profit, status FROM bought_items
        ''')
        
        # Drop old bought_items table and rename new table
        cursor.execute('DROP TABLE bought_items')
        cursor.execute('ALTER TABLE new_bought_items RENAME TO bought_items')
        
        # Create new listings table
        cursor.execute('''
        CREATE TABLE new_listings (
            timed_classId_listings TEXT PRIMARY KEY,
            assetId TEXT,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'in_inventory',
            buy_price REAL DEFAULT NULL,
            sell_price REAL DEFAULT NULL
        )
        ''')
        
        # Copy data to new listings table
        cursor.execute('''
        INSERT INTO new_listings (timed_classId_listings, assetId, title, status, buy_price, sell_price)
        SELECT timed_classId_listings, assetId, title, status, buy_price, sell_price FROM listings
        ''')
        
        # Drop old listings table and rename new table
        cursor.execute('DROP TABLE listings')
        cursor.execute('ALTER TABLE new_listings RENAME TO listings')
        
        conn.commit()
"""
if __name__ == "__main__":
    add_new_columns()
    populate_new_columns()
    update_primary_keys()
"""

def drop_listings_table():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('DROP TABLE IF EXISTS listings')
        conn.commit()

def drop_baught_table():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('DROP TABLE IF EXISTS bought_items')
        conn.commit()


#add offer_id collumn
def add_offer_id():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        ALTER TABLE listings ADD COLUMN offer_id TEXT;
        """
    )
    conn.commit()
    conn.close()


