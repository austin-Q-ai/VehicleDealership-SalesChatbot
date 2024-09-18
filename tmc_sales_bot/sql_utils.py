import json
import sqlite3
from os import environ
from openai import OpenAI
import re
from config import FRONTEND_URL, VEHICLE_WITH_VIDEO_JSON, SQL_DB, load_env
from tmc_sales_bot.utils import get_completion, retrieve_vehicle


client = OpenAI(api_key=environ['OPENAI_API_KEY'])
completion = get_completion()

create_table_template = r"CREATE TABLE {} ({})"
property_template_without_check = r"{} {}, "
property_template_primary_key = r"{} {} PRIMARY KEY, "
property_template_with_check = r"{} {} CHECK({} IN ({})), "
check_property = "'{}', "
insert_property = "{}, "

frontend_prefix = FRONTEND_URL + r"/vehicles-for-sale/viewdetail/{}"

def read_vehicle_data():
    with open(VEHICLE_WITH_VIDEO_JSON, "r") as f:
        vehicle_data = json.load(f)
    data = vehicle_data["data"]["results"]
    return data


def remove_none(lst):
    return [i for i in lst if i is not None]


def process_type(lst):
    if len(lst) == 0:
        raise Exception("The array can not be empty")
    _lst = remove_none(lst)
    if len(_lst) == 0:
        return None, None
    else:
        primary_type = type(_lst[0])
        if primary_type == float:
            for i in range(len(_lst)):
                _lst[i] = float(_lst[i])
        for j, element in enumerate(_lst):
            if not isinstance(element, primary_type):
                if primary_type == float and type(element) == int:
                    _lst[j] = float(_lst[j])
        if primary_type == str:
            if len(_lst) < 40:
                if len(_lst) != len(lst):
                    _lst.append(None)
                return str, _lst
            else:
                return str, None
        else:
            return primary_type, None


def drop_all_tables(connect):
    cursor = connect.cursor()

    # get the list of all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()

    # iterate through each table and drop it
    for table in tables:
        cursor.execute(f"DROP TABLE IF EXISTS {table[0]};")


def property_template(prop, prop_type, check_list):
    if prop == "yearOfManufacture":
        prop_type = int
        check_list = None
    if check_list is None:
        if prop_type == int:
            return property_template_without_check.format(str(prop), "INTEGER"), "INTEGER"
        elif prop_type == float:
            return property_template_without_check.format(str(prop), "FLOAT"), "FLOAT"
        elif prop_type == str:
            return property_template_without_check.format(str(prop), "TEXT"), "TEXT"
        elif prop_type == None or prop_type == dict:
            return "", None
        elif prop_type == bool:
            return property_template_with_check.format(str(prop), "TEXT", str(prop), "null, 'True', 'False'"), "TEXT"
        else:
            raise Exception(f"Type {str(prop_type)} occurred!")
    else:
        if prop_type != str:
            raise Exception(f"Type {str(prop_type)} occurred with check list.")
        else:
            check_str = ""
            for value in check_list:
                if value is not None:
                    check_str += check_property.format(value)
                else:
                    check_str += "null, "
            check_str = check_str[:-2]
            # print("============")
            # print(property_template_with_check.format(str(prop), "TEXT", str(prop), check_str), "TEXT")
            return property_template_with_check.format(str(prop), "TEXT", str(prop), check_str), "TEXT"


def property_template_with_null(prop, prop_type, check_list):
    if prop == "yearOfManufacture":
        prop_type = int
        check_list = None
    if prop == "vin":
        return property_template_primary_key.format(str(prop), "TEXT"), "TEXT"
    if check_list is None:
        if prop_type == int:
            return property_template_without_check.format(str(prop), "INTEGER"), "INTEGER"
        elif prop_type == float:
            return property_template_without_check.format(str(prop), "FLOAT"), "FLOAT"
        elif prop_type == str:
            return property_template_without_check.format(str(prop), "TEXT"), "TEXT"
        elif prop_type == dict:
            return "", None
        elif prop_type == None:
            return property_template_without_check.format(str(prop), "TEXT"), "TEXT"
        elif prop_type == bool:
            return property_template_with_check.format(str(prop), "TEXT", str(prop), "null, 'True', 'False'"), "TEXT"
        else:
            # print("-----------------")
            # print(prop_type, check_list, prop)
            raise Exception(f"Type {str(prop_type)} occurred!")
    else:
        if prop_type != str:
            raise Exception(f"Type {str(prop_type)} occurred with check list.")
        else:
            check_str = ""
            for value in check_list:
                if value is not None:
                    check_str += check_property.format(value)
                else:
                    check_str += "null, "
            check_str = check_str[:-2]
            return property_template_with_check.format(str(prop), "TEXT", str(prop), check_str), "TEXT"


def get_table_schema(connect, table_name="vehicle"):
    cursor = connect.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    # Fetch all the rows
    rows = cursor.fetchall()
    return rows


def execute_query(connect, query):
    cursor = connect.cursor()
    cursor.execute(query)


def generate_create_table_query(vehicle_data, table_name="vehicle", with_null=False):
    create_table_query = ""
    properties = list(vehicle_data[1]["vehicle"].keys())
    # print(properties, "=-=-=-=-=-=-=-=-=")
    prop_with_types = {}
    extra_props = ["ULEZ", "forecourtPrice", "forecourtPriceVatStatus", "attentionGrabber", "priceIndicatorRating"]
    for prop in properties:
        temp = []
        for vehicle in vehicle_data:
            try:
                if vehicle["vehicle"][prop] in temp:
                    pass
                else:
                    temp.append(vehicle["vehicle"][prop])
            except:
                # print(prop)
                pass

        data_type, data_list = process_type(temp)
        if with_null:
            prop_query, prop_type = property_template_with_null(prop, data_type, data_list)
            create_table_query += prop_query
            if prop_query != "":
                prop_with_types[prop] = prop_type
        else:
            prop_query, prop_type = property_template(prop, data_type, data_list)
            create_table_query += prop_query
            if prop_query != "":
                prop_with_types[prop] = prop_type

    for prop in extra_props:
        temp = []
        for vehicle in vehicle_data:
            try:
                value = None
                if prop == "ULEZ":

                    if vehicle["vehicle"]["emissionClass"] == "Euro 6":
                        value = "ULEZ compliant"
                    elif vehicle["vehicle"]["emissionClass"] is None:
                        value = "Not ULEZ compliant"
                    else:
                        value = "Not sure, Please contact TMC team for the details."
                elif prop == "forecourtPrice":
                    value = vehicle["adverts"][prop]["amountGBP"]
                elif prop == "forecourtPriceVatStatus":
                    value = vehicle["adverts"][prop]
                elif prop == "attentionGrabber":
                    value = vehicle["adverts"]["retailAdverts"][prop]
                elif prop == "priceIndicatorRating":
                    value = vehicle["adverts"]["retailAdverts"][prop]
                else:
                    print("Extra Prop Error !!", prop)
                    raise Exception("Extra Prop")
                if value in temp:
                    pass
                else:
                    temp.append(value)
            except:
                # print(prop)
                pass
                
        if len(temp) == 0:
            temp.append(None)
        data_type, data_list = process_type(temp)
        if with_null:
            prop_query, prop_type = property_template_with_null(prop, data_type, data_list)

            create_table_query += prop_query
            if prop_query != "":
                prop_with_types[prop] = prop_type
        else:
            prop_query, prop_type = property_template(prop, data_type, data_list)
            create_table_query += prop_query
            if prop_query != "":
                prop_with_types[prop] = prop_type

    create_table_query = create_table_query[:-2]
    final_query = create_table_template.format(table_name, create_table_query)
    return final_query, prop_with_types


def generate_insert_query(vehicle, properties_with_type, table_name="vehicle"):
    # vehicle_data = vehicle["vehicle"]
    properties = list(properties_with_type.keys())
    sql_command = r"""INSERT INTO {} {} VALUES {}"""
    data_tup = ()
    insert_prop_str = ""
    value_str = ""
    for prop in properties:
        if prop != "standard":
            insert_prop_str += insert_property.format(prop)
            value_str += "?, "
            value = None
            try:
                if prop == "ULEZ":
                    # print(vehicle["vehicle"]["emissionClass"] == None, vehicle["vehicle"]["emissionClass"] == "", vehicle["vehicle"]["emissionClass"])
                    if vehicle["vehicle"]["emissionClass"] == "Euro 6":
                        value = "ULEZ compliant"
                    elif vehicle["vehicle"]["emissionClass"] is None:
                        value = "Not ULEZ compliant"
                    else:
                        value = "Not sure, Please contact TMC team for the details."
                elif prop == "forecourtPrice":
                    value = vehicle["adverts"][prop]["amountGBP"]
                elif prop == "forecourtPriceVatStatus":
                    value = vehicle["adverts"][prop]
                elif prop == "attentionGrabber":
                    value = vehicle["adverts"]["retailAdverts"][prop]
                elif prop == "priceIndicatorRating":
                    value = vehicle["adverts"]["retailAdverts"][prop]
                elif prop not in vehicle["vehicle"].keys():
                    value = None
                else:
                    value = vehicle["vehicle"][prop]
            except:
                pass
            if value is None:
                data_tup += (None,)
            else:
                if properties_with_type[prop] == "TEXT":
                    data_tup += (str(value),)
                elif properties_with_type[prop] == "INTEGER":
                    data_tup += (int(value),)
                elif properties_with_type[prop] == "FLOAT":
                    data_tup += (float(value),)
                else:
                    raise Exception(f"Data Property {properties_with_type[prop]} Occurred!")
    insert_prop_str = insert_prop_str[:-2]
    insert_prop_str = r"({})".format(insert_prop_str)
    value_str = value_str[:-2]
    value_str = r"({})".format(value_str)
    sql_command = sql_command.format(table_name, insert_prop_str, value_str)
    return sql_command, data_tup


def create_database(vehicle_data):
    conn = sqlite3.connect(SQL_DB)
    cursor = conn.cursor()
    drop_all_tables(conn)
    create_table_query, prop_types = generate_create_table_query(vehicle_data, with_null=True)
    execute_query(conn, create_table_query)
    for vehicle in vehicle_data:
        sql_command, data_tup = generate_insert_query(vehicle, prop_types)
        cursor.execute(sql_command, data_tup)
    conn.commit()
    return conn


def generate_select_query(create_table_query, previous_conversation, features):
    system_message = r"""Given the following SQL table, and customer conversation, your job is to write queries given user's request.
Plz generate query for most recent user's request. i.e. If user asks different questions several times, you should generate query for last question.

Create table sql query is as follows.
###
{}
###

Here are customer conversation.
###
{}
###

Please always generate 'SELECT *' query to gather all properties EXCEPT {}.
Must use correct column name in create table sql query.
If user is searching for vehicle around the mileage, just set the range 2000 miles up and back.
For example, if user is asking about the vehicles around the 10000 miles, you can find vehicles around 8000 - 12000 miles.
But when user is searching for vehicle below or above miles, you set the range just bigger or smaller than the base mileage.
For example, if user is asking about the vehicles below 10000 miles, you can find vehicles around 0 - 10000 miles.
Do not including any guide or system message in the response. 
Only generate query.
""".format(create_table_query, previous_conversation, ",".join(features))
    messages = []
    messages.append({"role": "user", "content": system_message})
    response = completion(
        messages=messages
    )
    response_str = response.json()['choices'][0]['message']['content']
    return extract_select_query(response_str)


def extract_select_query(query_str: str):
    # Define your SQL query
    # Use re.search() to find 'SELECT' in the string
    query_temp_str = query_str.lower()
    match = re.search('select', query_temp_str)

    # Check if a match was found
    if match:
        final_res = query_str[match.start():]
        final_res = final_res.split(";")[0]
        return final_res
    else:
        return None


def get_vehicle_data(vehicle_data, customer_conversation, features):
    create_table_query, prop_types = generate_create_table_query(vehicle_data, with_null=False)
    sql_query = generate_select_query(create_table_query, customer_conversation, features)
    rfeatures = []
    for feature in features :
        if feature.lower() not in sql_query.lower() :
            rfeatures.append(feature.lower().replace(" ", ""))
    print("-------sql_query--------")
    print(sql_query)
    
    print ("^Features", rfeatures)
    
    sql_query = sql_query.split("\n")[0]
    conn = sqlite3.connect(SQL_DB)
    cursor = conn.cursor()
    vehicles = []
    try:
        cursor.execute(sql_query)
        vehicles = cursor.fetchall()
    except:
        pass

    conn.commit()
    conn.close()

    result = []
    
    all_vehicles = read_vehicle_data()
    for vehicle in vehicles:
        for prop in vehicle:
            if isinstance(prop, str):
                if len(prop) == 17 and " " not in prop:
                    result.append(vehicle)
                    break
    if len(result) != len(vehicles):
        raise Exception(f"Length of vehicles mismatched.")

    # print("===================", len(result), len(vehicles), result)
    final = []
    for vehicle in result:
        for prop in vehicle:
            if isinstance(prop, str):
                if len(prop) == 17 and " " not in prop:
                    cfeatures = list(filter(lambda vehicle: vehicle["vehicle"]["vin"] == prop, all_vehicles))[0]["features"]
                    cfeatures = list(map(lambda meta: meta["name"].lower().replace(" ", ""), cfeatures))
                    if set(rfeatures).issubset(set(cfeatures)) :
                        print (cfeatures)
                        final.append(frontend_prefix.format(prop))
                        break
    return final

def getVehicleType(vrn) :
    type = retrieve_vehicle(vrn)
    print ("*******", type)
    return type
    