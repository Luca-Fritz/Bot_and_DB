from datetime import datetime # For the timestamp
import os # for the path to the safed list


#URL Paths
API_URL = "https://api.dmarket.com"
API_URL_TRADING = API_URL


#directory for the offer list
offer_list_directory = os.path.join(os.path.expanduser("~"), "OneDrive", "Dokumente", "_projects", "api", "dmarket_api", "Bot_and_DB", "lists", "offer_lists") 
db_append_directory = os.path.join(os.path.expanduser("~"), "OneDrive", "Dokumente", "_projects", "api", "dmarket_api", "Bot_and_DB", "lists", "db_append_lists")
no_data_titles_path = os.path.join(os.path.expanduser("~"), "OneDrive", "Dokumente", "_projects", "api", "dmarket_api", "Bot_and_DB", "lists", "db_append_lists", "no_data_titles.txt")
db_path = os.path.join(os.path.expanduser("~"), "OneDrive", "Dokumente", "_projects", "api", "dmarket_api", "Bot_and_DB", "sales_data.db")

#for Test
#db_path = os.path.join(os.path.expanduser("~"), "OneDrive", "Dokumente", "_projects", "api", "dmarket_api", "test", "test_for_Main", "sales_data.db") #for test_for_main
#no_data_titles_path = os.path.join(os.path.expanduser("~"), "OneDrive", "Dokumente", "_projects", "api", "dmarket_api", "test", "test_for_Main", "lists", "db_append_lists", "no_data_titles.txt") #for test_for_main

#for pi
#offer_list_directory = os.path.join(os.path.expanduser("~"),"Bot_and_DB", "lists", "offer_lists") #for pi
#db_append_directory = os.path.join(os.path.expanduser("~"),"Bot_and_DB", "lists", "db_append_lists") #for pi
#no_data_titles_path = os.path.join(os.path.expanduser("~"), "Bot_and_DB", "lists", "db_append_lists", "no_data_titles.txt")  # for pi
#db_path = os.path.join(os.path.expanduser("~"), "Bot_and_DB", "sales_data.db")  # for pi

#"C:\\Users\\fritz\\OneDrive\\Dokumente\\_projects\\dmarket_api\\py\\Dmarket\\offer_lists"

# Get the current timestamp in a more readable format
timestamp =  datetime.now().strftime("%S-%M-%H-%d_%m-%Y") 
#timestamp =  datetime.now().strftime("%Y-%m-%d_%H-%M-%S") #Timetamp with other arrangement 




url_get_items = "/exchange/v1/market/items"

