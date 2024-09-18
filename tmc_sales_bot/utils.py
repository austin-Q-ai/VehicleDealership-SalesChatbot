import requests
from os import environ
from openai import OpenAI
import tiktoken
import re
import json
from urllib.parse import urlparse
from config import ModelType, VEHICLE_WITH_VIDEO_JSON, FRONTEND_URL, VALUATION_URL, SEND_SMS_URL, SEND_EMAIL_URL, RETRIEVE_VEHICLE_URL, \
    FINANCE_CALC, FINANCE_LIMIT, VALIDATE_POSTCODE, CALC_DISTANCE, ModelChoice
from litellm import completion
import litellm
litellm.modify_params = True
litellm.telemetry=False
litellm.logging = False
client = OpenAI(api_key=environ['OPENAI_API_KEY'])

        
def get_completion():
    if environ["MODEL_CHOICE"] == "OPENAI":
        def chat_completion(messages, tools=None, tool_choice=None, stream=False):
            return completion(model=ModelChoice.OPENAI.value, messages=messages, tools=tools, tool_choice=tool_choice, stream=stream)
    elif environ["MODEL_CHOICE"] == "ANTHROPIC":
        def chat_completion(messages, tools=None, tool_choice=None, stream=False):
            return completion(model=ModelChoice.ANTHROPIC.value, messages=messages, tools=tools, tool_choice=tool_choice, stream=stream)
    return chat_completion

def get_vehicle_data():
    with open(VEHICLE_WITH_VIDEO_JSON, "r") as f:
        vehicle_detail = json.load(f)
    vehicle_data = vehicle_detail["data"]["results"]
    return vehicle_data


def get_company_vehicle_reference(vin: str):    
    vehicle_data = get_vehicle_data()
    vin = vin.split("/")
    if vin[-1] == "":
        vin = vin[-2]
    else:
        vin = vin[-1]
    reference = {}
    for vehicle in vehicle_data:
        if vin.lower() == vehicle['vehicle']['vin'].lower():

            reference = vehicle['vehicle']
            key_list = list(reference.keys())

            reference["forecourtPrice"] = vehicle["adverts"]["forecourtPrice"]
            reference["videoLink"] = vehicle["media"]["video"]["href"]
            reference["website_link"] = FRONTEND_URL + "/vehicles-for-sale/viewdetail/" + vehicle['vehicle']['vin']

            if "forecourtPriceVatStatus" in vehicle["adverts"].keys():
                reference["forecourtPriceVatStatus"] = vehicle["adverts"]["forecourtPriceVatStatus"]
            else:
                reference["forecourtPriceVatStatus"] = None

            if reference["forecourtPriceVatStatus"] == "Ex VAT":
                reference["extraVatPrice"] = {"amountGBP": reference["forecourtPrice"]["amountGBP"] * 0.2}
            else:
                reference["extraVatPrice"] = "This vehicle does not include VAT"
            
            if "attentionGrabber" in vehicle["adverts"].keys():
                reference["attentionGrabber"] = vehicle["adverts"]["attentionGrabber"]
            else:
                reference["attentionGrabber"] = None


            if "emissionClass" in vehicle["vehicle"].keys() and vehicle["vehicle"]["emissionClass"] == "Euro 6":
                reference["ULEZ"] = "ULEZ compliant"
            elif "emissionClass" in vehicle["vehicle"].keys() and vehicle["vehicle"]["emissionClass"] is None:
                reference["ULEZ"] = "Not ULEZ compliant"
            else:
                reference["ULEZ"] = "Not sure, Please contact TMC team for the details."
            reference["priceIndicatorRating"] = vehicle["adverts"]["retailAdverts"]["priceIndicatorRating"]


            for key in key_list:
                if reference[key] is None or key == 'standard':
                    del reference[key]
            del reference["finance"]
            limit = finance_limit(vin)
            reference["finance"] = limit

            return reference

    return reference


def get_vin_from_vrn(vrn: str):
    vehicle_data = get_vehicle_data()
    for vehicle in vehicle_data:
        # print(vin.lower(), vehicle['vehicle']['vin'].lower())
        if vrn.lower() == vehicle['vehicle']['registration'].lower():
            return vehicle['vehicle']["vin"]
    if validate_vrn(vrn):
        return "vehicle not found"
    else:
        return "invalid vrn"


def get_vin_from_url(url: str):
    vehicle_data = get_vehicle_data()
    hostname = urlparse(url).hostname
    frontend_host = urlparse(FRONTEND_URL).hostname
    if hostname != frontend_host:
        return "Wrong Website"
    elements = urlparse(url).path
    elements = elements.split("/")
    if len(elements) > 3 and elements[2] == 'viewdetail':
        return elements[3]
    else:
        return ""


def check_company_vehicle(vin: str):
    vehicle_data = get_vehicle_data()

    for vehicle in vehicle_data:
        if vin.lower() == vehicle['vehicle']['vin'].lower():
            return True
    return False
    

def check_company_vehicle_vrn(vrn: str):
    vehicle_data = get_vehicle_data()

    for vehicle in vehicle_data:
        if vrn.lower() == vehicle['vehicle']['registration'].lower():
            return True
    return False



def get_video_link(vin: str):
    vehicle_data = get_vehicle_data()

    for vehicle in vehicle_data:
        if vin.lower() == vehicle['vehicle']['vin'].lower():
            return vehicle['media']['video']['href']


def get_forecourt_price(vin: str):
    vehicle_data = get_vehicle_data()

    for vehicle in vehicle_data:

        if vin.lower() == vehicle['vehicle']['vin'].lower():
            return vehicle["adverts"]["forecourtPrice"]["amountGBP"]


def validate_vrn(vrn: str):
    payload = json.dumps({
        "registration": vrn,
        "miles": '10000'
    })
    headers = {
        'Content-Type': 'application/json'
    }
    response = requests.request("POST", VALUATION_URL, headers=headers, data=payload)
    if response.status_code == 200:
        return True
    else:
        return False


def validate_mileage(mileage: str):
    try:
        mileage = int(mileage)
        if mileage < 1000000:
            return True
        else:
            return False
    except:
        return False


def validata_vin(vin: str):
    vehicle_data = get_vehicle_data()

    for vehicle in vehicle_data:
        if vin.lower() == vehicle["vehicle"]["vin"].lower():
            return True
    return False


def valuate_vehicle(vrn: str, mileage: str, condition: str, service_history: str, name: str, email: str, number: str):
    payload = json.dumps({
        "registration": vrn,
        "miles": mileage,
        "condition" : condition,
        "service_history" : service_history,
        "name": name,
        "email": email,
        "number": number
    })
    headers = {
        'Content-Type': 'application/json'
    }

    print ("########################VALUATION###########################")
    response = requests.request("POST", VALUATION_URL, headers=headers, data=payload)
    if response.status_code == 200:
        response = response.json()
        if response["data"]["valuations"]["trade"]["amountGBP"]:
            print("Valuation:", response["data"]["valuations"]["trade"]["amountGBP"], vrn, mileage, condition, service_history)
            return {"cost": response["data"]["valuations"]["trade"]["amountGBP"], "status":"success", "make":response["data"]["vehicle"]["make"], "model":response["data"]["vehicle"]["model"], "generation":response["data"]["vehicle"]["generation"]}
        else:
            print("Valuation:", response["data"]["valuations"]["trade"]["amountExcludingVatGBP"], vrn, mileage, condition, service_history)
            return {"cost": response["data"]["valuations"]["trade"]["amountExcludingVatGBP"], "status":"success", "make":response["data"]["vehicle"]["make"], "model":response["data"]["vehicle"]["model"], "generation":response["data"]["vehicle"]["generation"]}
    else:
        response = response.json()
        return {"message": response["message"], "status":"failed"}


def extract_vehicle_id(url):
    parts = url.split('/')
    vehicle_id = parts[-1]
    return vehicle_id


def extract_url(text):
    url_pattern = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')
    urls = re.findall(url_pattern, text)
    return urls


def get_embedding(text, model=ModelType.embedding_v3_large):
    text = text.replace("\n", " ")
    return client.embeddings.create(input=[text], model=model).data[0].embedding


def embedding(sentences):
    if isinstance(sentences, str):
        return get_embedding(sentences)
    elif isinstance(sentences, list):
        result = []
        for sentence in sentences:
            result.append(get_embedding(sentence))
        return result


def num_tokens_from_string(string: str, encoding_name: str) -> int:
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens


def compose_header(reference):
    header = "This car's "
    for key in reference.keys():
        header += str(key) + ' is ' + str(reference[key]) + ', and '
    header = header[:-4]
    return header


def get_vehicle_description(vehicle):
    description = "This car's "
    important_props = ["make", "model", "generation", "derivative", "vehicleType", "trim", "bodyType", "fuelType", "cabType", "transmissionType", "wheelbaseType", "drivetrain", "seats", "doors", "cylinders", "valves", "bodyCondition","ULEZ","forecourtPrice","forecourtPriceVatStatus","attentionGrabber","priceIndicatorRating", "websiteLink"]
    for prop in important_props:
        if prop in vehicle["vehicle"].keys() and vehicle["vehicle"][prop] != None:
            description += str(prop) + ' is ' + str(vehicle["vehicle"][prop]) + ', and '
        elif prop == "ULEZ":
            if "emissionClass" in vehicle["vehicle"].keys() and vehicle["vehicle"]["emissionClass"] == "Euro 6":
                description += str(prop) + ' is ' + str("ULEZ compliant") + ', and '
            elif "emissionClass" in vehicle["vehicle"].keys() and vehicle["vehicle"]["emissionClass"] is None:
                description += str(prop) + ' is ' + str("Not ULEZ compliant") + ', and '
        elif prop == "forecourtPrice" and "forecourtPrice" in vehicle["adverts"].keys():
            description += str(prop) + ' is ' + str(vehicle["adverts"][prop]["amountGBP"]) + ', and '
        elif prop == "forecourtPriceVatStatus" and "forecourtPriceVatStatus" in vehicle["adverts"].keys():
            description += str(prop) + ' is ' + str(vehicle["adverts"][prop]) + ', and '
        elif prop == "attentionGrabber" and "attentionGrabber" in vehicle["adverts"].keys():
            description += str(prop) + ' is ' + str(vehicle["adverts"][prop]) + ', and '
        elif prop == "priceIndicatorRating" and "priceIndicatorRating" in vehicle["adverts"].keys():
            description += str(prop) + ' is ' + str(vehicle["adverts"][prop]) + ', and '
        elif prop == "websiteLink":
            description += str(prop) + ' is ' + FRONTEND_URL + "/vehicles-for-sale/viewdetail/" + vehicle['vehicle']['vin'] + ', and '
    description = description[:-6]
    features = "\nBelow are the features that this vehicle have.\n"
    for feature in vehicle["features"]:
        features += feature["name"]
        features += "\n"
    description += features
    return description


def validate_postcode(postcode: str):
    payload = json.dumps({
        "postcode": postcode
    })
    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", VALIDATE_POSTCODE, headers=headers, data=payload)
    response = response.json()

    return response


def calculate_distance(postcode: str, vin: str):
    payload = json.dumps({
        "postcode": postcode,
        "vin": vin
    })
    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", CALC_DISTANCE, headers=headers, data=payload)
    response = response.json()

    return response


def finance_limit(vin: str):
    if validata_vin(vin):
        url = FINANCE_LIMIT + "?vin={vin_number}"
        url = url.format(vin_number=vin)
        payload = {}
        headers = {}
        response = requests.request("GET", url, headers=headers, data=payload)
        response = response.json()
        return response
    else:
        return {
            "message": "Can not find vehicle in company's stock!"
        }


def finance_calc(vin: str, term: int, deposit: int):
    if validata_vin(vin):
        url = FINANCE_CALC + "?vin={vin}&term={term}&deposit={deposit}"
        url = url.format(vin=vin, term=term, deposit=deposit)
        payload = {}
        headers = {}
        response = requests.request("GET", url, headers=headers, data=payload)
        response = response.json()
        return response
    else:
        return {
            "message": "Can not find vehicle in company's stock!"
        }


def send_sms(number: str, message: str):
    headers = {
        'Content-Type': 'application/json'
    }
    body = json.dumps({"To": number, "Body": message, "type": "sms"})
    response = requests.request("POST", SEND_SMS_URL, headers=headers, data=body)
    print("PROP", response.status_code, response.text, "SMS")
    return response.status_code


def send_whatsapp(number: str, message: str):
    headers = {
        'Content-Type': 'application/json'
    }
    body = json.dumps({"To": number, "Body": message, "type": "whatsapp"})
    response = requests.request("POST", SEND_SMS_URL, headers=headers, data=body)
    print("PROP", response.status_code, response.text, "Whatsapp")
    return response.status_code


def send_email(email: str, message: str, title: str):
    headers = {
        'Content-Type': 'application/json'
    }
    body = json.dumps({"To": email, "Body": message, "title": title})
    response = requests.request("POST", SEND_EMAIL_URL, headers=headers, data=body)
    return response.status_code

def retrieve_vehicle(registration: str):
    headers = {
        'Content-Type': 'application/json'
    }
    body = json.dumps({"registration": registration})
    response = requests.request("POST", RETRIEVE_VEHICLE_URL, headers=headers, data=body)
    if response.status_code != 200 :
        return ""
    
    data = json.loads(response.text)
    type = data["data"]["vehicle"]["vehicleType"]
    print ("***VEHICLE TYPE:  ", type)
    if type.lower() == "van":
        return "VAN"
    else :
        return "NOT VAN"


