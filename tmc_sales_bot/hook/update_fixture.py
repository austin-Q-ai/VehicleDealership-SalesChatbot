import requests
import json
from config import (VEHICLE_WITH_VIDEO_JSON, BACKEND_URL, GET_STOCK_URL)
from tmc_sales_bot.sql_utils import create_database, read_vehicle_data


def update_video_json():
    payload = {}
    headers = {}
    response = requests.request("GET", GET_STOCK_URL, headers=headers, data=payload)
    result = response.json()
    with open(VEHICLE_WITH_VIDEO_JSON, 'w') as f:
        json.dump(result, f, indent=4)


def update_sql_db():
    data = read_vehicle_data()
    create_database(data)
