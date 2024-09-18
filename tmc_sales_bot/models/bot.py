from config import (ModelType, PromptTemplate, FunctionTemplate, get_prompt_template, get_function_template,
                    TOP_K, FRONTEND_URL, VEHICLE_WITH_VIDEO_JSON)
import os
from os import environ
from openai import OpenAI
from pinecone import Pinecone
import json
from tenacity import retry, wait_random_exponential, stop_after_attempt

from tmc_sales_bot.utils import embedding, compose_header, valuate_vehicle, get_company_vehicle_reference, \
    send_whatsapp, send_sms, send_email, calculate_distance, validate_postcode, finance_calc, check_company_vehicle_vrn
from tmc_sales_bot.sql_utils import get_vehicle_data, getVehicleType
from tmc_sales_bot.utils import get_completion

pc = Pinecone(api_key=environ["PINECONE_API_KEY"])
completion = get_completion()
        
class ChatBot:
    def __init__(self):
        self.index_name = environ['PINECONE_INDEX_NAME']
        self.pinecone_index = pc.Index(self.index_name)
        self.top_k = TOP_K
        self.encoding_name = ModelType.encoding
        self.init_messages()
        self.model = ModelType.gpt4
        self.state_variables = {"user_contact_info": {"name": "", "e-mail": "", "number": ""},
                                "user_location_info":{"postcode": "", "town":"", "county":""}, 
                                "user_vehicle_info": {"vrn": "", "mileage": "", "cost": "", "make": "", "model": "", "generation": "", "links":[], "condition":"", "service_history":"", "active": "","type":""},
                                "finance_info": {"vin": "", "deposit": "", "term": "", "active": ""},
                                "full_pay_info": {"vin": "", "active": ""},
                                "user_location": {}, "viewed_vehicles": [], "stripe": ""}
        self.chat_mode = "guest"
        with open(VEHICLE_WITH_VIDEO_JSON, "r") as f:
            vehicle_data = json.load(f)
        self.vehicle_data = vehicle_data["data"]["results"]

    def set_location(self, location):
        print ("#####", location)
        if location != self.state_variables["user_location"]:
            self.state_variables["user_location"] = location
        if "vehicles-for-sale" in location :
            vin_number = location.split("-")[-1]
            print ("&&&&", vin_number)
            if vin_number not in self.state_variables["viewed_vehicles"]:
                self.state_variables["viewed_vehicles"].append(vin_number)

    def set_chat_mode(self, mode):
        self.chat_mode = mode

    def update_state(self, variables):
        self.state_variables = variables

    def init_messages(self):
        self.messages = []

    def query_db(self, query, property=None, top_k=5):
        query_vector = embedding(query)
        if property is not None:
            result = self.pinecone_index.query(
                vector=query_vector, filter={"prop":property}, top_k=top_k, namespace=self.index_name)
        else:
            result = self.pinecone_index.query(
                vector=query_vector, top_k=top_k)
        matches = result.to_dict()["matches"]
        ids = []
        for match in matches:
            ids.append(match["id"])
        if ids == []:
            return []
        else:
            data = self.pinecone_index.fetch(ids, namespace=self.index_name).to_dict()["vectors"]
            descriptions = []
            for id in ids:
                descriptions.append(data[id]["metadata"])
        return descriptions

    def get_reference(self, query, property=None):
        query_result = self.query_db(query=query, property=property, top_k=self.top_k)
        reference = ""
        for res in query_result:
            reference += res["content"]
        return reference

    def compose_prompt(self, query):
        extra_message = ""
        params = self.determine_params(query)
        print ("######", params)
        if "user_vehicle_registration_number" in params.keys() and params["user_vehicle_registration_number"] is not None:
            if check_company_vehicle_vrn(params["user_vehicle_registration_number"]):
                extra_message += r"\nVehicle with registration number {} is in the company's stock.\n".format(params["user_vehicle_registration_number"])
                params["user_vehicle_registration_number"] = ""
                params["user_vehicle_mileage"] = ""
                params["user_vehicle_condition"] = ""
                params["user_vehicle_service_history"] = ""
        user_contact_info = self.compose_user_contact_info(params)
        user_vehicle_info = self.compose_user_vehicle_info(params)
        user_location_info = self.compose_user_location_info(params)
        user_finance_info = self.compose_user_finance_info(params)

        if "features" not in params.keys() :
            params["features"] = []
            
            
        reference_data = "Not specified"
        focused_vehicle_reference = "Not specified"
        return_list = []
        print ("Query:", query)
        print ("Params:", params)
        if "conversation_intent" in params.keys() and params["conversation_intent"] is not None:
            intent = params["conversation_intent"]
            if intent == "searching_vehicle":
                recommended_vehicles = get_vehicle_data(self.vehicle_data, self.format_messages(), params["features"])
                print ("***Query Result:", len(recommended_vehicles))
                if len(recommended_vehicles) > 1:
                    reference_data = f"There are {str(len(recommended_vehicles))} vehicles that matches the user's preference in the company's stock.\nReturn_list: True"
                    return_list = recommended_vehicles
                elif len(recommended_vehicles) == 1:
                    reference_data = f"There are 1 vehicle that matches the user's preference in the company's stock.\n{get_company_vehicle_reference(recommended_vehicles[0])}\nReturn_list: False"
                elif len(recommended_vehicles) == 0:
                    # reference_data = self.get_reference(query, property="vehicle") + "\nReturn_list: False"
                    reference_data = "There's no vehicle that matches user preferences in the stock.\nReturn_list: False"
            elif intent == "vehicle_valuation":
                try :
                    print ("```###", self.state_variables["user_vehicle_info"]["cost"])
                    if not isinstance(self.state_variables["user_vehicle_info"]["cost"], int) :
                        print ("^^^^%%%%")
                        reference_data = self.state_variables["user_vehicle_info"]["cost"] + " I can't valuate your vehicle. We will have a valuation expert contact you."
                except Exception as e:
                    print (e)
                    pass
            elif intent == "total_interest_payable":
                if self.state_variables["finance_info"]["deposit"] > 0 and self.state_variables["finance_info"]["term"] > 0:
                    vin = self.state_variables["viewed_vehicles"][-1]
                    print ("@@@", self.state_variables["finance_info"])
                    payment_calc = finance_calc(vin, self.state_variables["finance_info"]["term"], self.state_variables["finance_info"]["deposit"])
                    TotalAmountPayableExcludingContributions = payment_calc["data"]["TotalAmountPayableExcludingContributions"]
                    focused_vehicle = self.state_variables["viewed_vehicles"][-1]
                    focused_vehicle_reference = get_company_vehicle_reference(focused_vehicle)
                    print ("####$$$", TotalAmountPayableExcludingContributions, focused_vehicle_reference["forecourtPrice"]["amountGBP"])
                    payable = TotalAmountPayableExcludingContributions - focused_vehicle_reference["forecourtPrice"]["amountGBP"]
                    reference_data = f"The total interest oayable is {payable}"
                else :
                    reference_data = "You must provide deposit and term details."
            elif intent == "total_payable" :
                print ("???????????")
                if self.state_variables["finance_info"]["deposit"] > 0 and self.state_variables["finance_info"]["term"] > 0 :
                    vin = self.state_variables["viewed_vehicles"][-1]
                    payment_calc = finance_calc(vin, self.state_variables["finance_info"]["term"], self.state_variables["finance_info"]["deposit"])
                    TotalAmountPayableExcludingContributions = payment_calc["data"]["TotalAmountPayableExcludingContributions"]
                    reference_data = f"The total amount payable is {TotalAmountPayableExcludingContributions}"
                else :
                    reference_data = "You must provide deposit and term details."
            # elif intent == "general_question":
            else :
                reference_data = self.get_reference(query, property="general") + "\nReturn_list: False"
        else :
            reference_data = self.get_reference(query, property="general") + "\nReturn_list: False"
        if self.state_variables["viewed_vehicles"] != []:
            focused_vehicle = self.state_variables["viewed_vehicles"][-1]
            focused_vehicle_reference = get_company_vehicle_reference(focused_vehicle)
        chat_location = ""
        if self.chat_mode == 'guest':
            chat_location = "The user is chatting as guest"
        else:
            chat_location = "The user is chatting with phone number"
        prompt = get_prompt_template(PromptTemplate.AIO_PROMPT).format(chat_model=chat_location,
                                                                       reference_data=reference_data,
                                                                       contact_info=user_contact_info,
                                                                       location_info=user_location_info,
                                                                       finance_info=user_finance_info,
                                                                       vehicle_info=user_vehicle_info,
                                                                       focused_vehicle=focused_vehicle_reference)
        
        prompt += extra_message

        return prompt, return_list

    def compose_user_location_info(self, parameters: dict) -> str:
        for key in parameters.keys():
            if key == "user_post_code" and parameters["user_post_code"] != "" and parameters["user_post_code"] is not None:
                self.state_variables["user_location_info"]["postcode"] = parameters["user_post_code"]
                val = validate_postcode(parameters["user_post_code"])
                if val["message"] == "Valid postcode":
                    self.state_variables["user_location_info"]["town"] = val["data"]["Town"]
                    self.state_variables["user_location_info"]["county"] = val["data"]["County"]
        
        user_location = ""
        office_location = ""
        distance = ""

        if self.state_variables["user_location_info"]["postcode"] != "":
            if validate_postcode(self.state_variables["user_location_info"]["postcode"])["message"] == "Valid postcode":
                if len(self.state_variables["viewed_vehicles"]) > 0:
                    vin = self.state_variables["viewed_vehicles"][-1]
                    calDis = calculate_distance(self.state_variables["user_location_info"]["postcode"], self.state_variables["viewed_vehicles"][-1])
                    if calDis["message"] == "success":
                        user_location = calDis["result"]["client_address"]
                        office_location = calDis["result"]["forecourt_address"]
                        distance = calDis["result"]["distance"]
                    else:
                        user_location = self.state_variables["user_location_info"]["postcode"]
                else:
                    user_location = self.state_variables["user_location_info"]["postcode"]
                    office_location = ""
                    distance = "User interested vehicle is not provided."
            else:
                user_location = r"{} (The postcode is not valid in UK.)".format(self.state_variables["user_location_info"]["postcode"])

        prompt = get_prompt_template(PromptTemplate.USER_LOCATION_INFO).format(
            user_postcode=user_location,
            office_postcode=office_location,
            distance=distance
        )

        return prompt


    def compose_user_finance_info(self, parameters: dict) -> str:
        for key in parameters.keys():
            if key == "finance_term" and parameters["finance_term"] != "0" and parameters["finance_term"] is not None:
                self.state_variables["finance_info"]["term"] = parameters["finance_term"]
            elif key == "finance_deposit" and parameters["finance_deposit"] != "0" and parameters["finance_deposit"] is not None:
                self.state_variables["finance_info"]["deposit"] = parameters["finance_deposit"]
        
        if len(self.state_variables["viewed_vehicles"]) > 0:
            vin = self.state_variables["viewed_vehicles"][-1]
        else:
            vin = ""
        term = self.state_variables["finance_info"]["term"]
        deposit = self.state_variables["finance_info"]["deposit"]

        payment_calc = finance_calc(vin, term, deposit)
        print (";;;;;; finace: ", vin, term, deposit, payment_calc)
        regular_payment = ""
        apr=""
        # TotalAmountPayableExcludingContributions = 0
        if payment_calc["message"] == "Success!":        
            regular_payment = payment_calc["data"]["AllInclusiveRegularPayment"]
            apr = payment_calc["data"]["Apr"]
            # TotalAmountPayableExcludingContributions = payment_calc["data"]["TotalAmountPayableExcludingContributions"]
            if payment_calc["data"]["vatStatus"]:
                deposit = r"Orignal Deposit value is {}. This vehicle include VAT so user need to pay extra {}.".format(payment_calc["data"]["Deposit"], payment_calc["data"]["vatPrice"])
        print ("^^^^^^^^^^", deposit, term, apr)
        prompt = get_prompt_template(PromptTemplate.USER_FINANCE_INFO).format(
            vin=vin,
            deposit=deposit,
            term=term,
            regular_payment=regular_payment,
            apr=apr
        )

        return prompt


    def compose_user_contact_info(self, parameters: dict) -> str:
        for key in parameters.keys():
            if key == "user_name" and parameters["user_name"] != "" and parameters["user_name"] is not None:
                self.state_variables["user_contact_info"]["name"] = parameters["user_name"]
            elif key == "user_email_address" and parameters["user_email_address"] != "" and parameters["user_email_address"] is not None:
                self.state_variables["user_contact_info"]["e-mail"] = parameters["user_email_address"]
            elif key == "user_contact_number" and parameters["user_contact_number"] != "" and parameters["user_contact_number"] is not None:
                self.state_variables["user_contact_info"]["number"] = parameters["user_contact_number"]

        prompt = get_prompt_template(PromptTemplate.USER_CONTACT_INFO).format(
            user_name=self.state_variables["user_contact_info"]["name"],
            contact_number=self.state_variables["user_contact_info"]["number"],
            email=self.state_variables["user_contact_info"]["e-mail"]
        )

        return prompt

    def compose_user_vehicle_info(self, parameters: dict) -> str:
        print("@##$", parameters)
        for key in parameters.keys():
            if key == "user_vehicle_registration_number" and parameters["user_vehicle_registration_number"] != "" and parameters["user_vehicle_registration_number"] is not None:
                self.state_variables["user_vehicle_info"]["vrn"] = parameters["user_vehicle_registration_number"]
                self.state_variables["user_vehicle_info"]["type"] = getVehicleType(parameters["user_vehicle_registration_number"])
            elif key == "user_vehicle_mileage" and parameters["user_vehicle_mileage"] != "" and parameters["user_vehicle_mileage"] is not None:
                self.state_variables["user_vehicle_info"]["mileage"] = parameters["user_vehicle_mileage"]
            elif key == "user_vehicle_condition" and parameters["user_vehicle_condition"] != "" and parameters["user_vehicle_condition"] is not None:
                self.state_variables["user_vehicle_info"]["condition"] = parameters["user_vehicle_condition"]
            elif key == "user_vehicle_service_history" and parameters["user_vehicle_service_history"] != "" and parameters["user_vehicle_service_history"] is not None:
                self.state_variables["user_vehicle_info"]["service_history"] = parameters["user_vehicle_service_history"]
            elif key == "user_vehicle_material_links" and parameters["user_vehicle_material_links"] != "" and parameters["user_vehicle_material_links"] is not None:
                self.state_variables["user_vehicle_info"]["links"] = parameters["user_vehicle_material_links"]
        if self.state_variables["user_vehicle_info"]["vrn"] != "" and self.state_variables["user_vehicle_info"][
            "mileage"] != "":
            if check_company_vehicle_vrn(self.state_variables["user_vehicle_info"]["vrn"]):
                self.state_variables["user_vehicle_info"]["cost"] = r"Vehicle with registration number {} is in the company's stock. And you can not provide valuation for company's vehicle.".format(self.state_variables["user_vehicle_info"]["vrn"])
            else:
                valuation_res = valuate_vehicle(
                    self.state_variables["user_vehicle_info"]["vrn"], self.state_variables["user_vehicle_info"]["mileage"], self.state_variables["user_vehicle_info"]["condition"], self.state_variables["user_vehicle_info"]["service_history"],
                    self.state_variables["user_contact_info"]["name"], self.state_variables["user_contact_info"]["e-mail"], self.state_variables["user_contact_info"]["number"]
                )
                if valuation_res["status"] == "success":
                    self.state_variables["user_vehicle_info"]["cost"] = valuation_res["cost"]
                    self.state_variables["user_vehicle_info"]["make"] = valuation_res["make"]
                    self.state_variables["user_vehicle_info"]["model"] = valuation_res["model"]
                    self.state_variables["user_vehicle_info"]["generation"] = valuation_res["generation"]
                else:
                    print ("*((", valuation_res["message"])
                    self.state_variables["user_vehicle_info"]["cost"] = valuation_res["message"]
        elif self.state_variables["user_vehicle_info"]["vrn"] == "":
            self.state_variables["user_vehicle_info"]["cost"] = ""
        elif self.state_variables["user_vehicle_info"]["vrn"] != "" and self.state_variables["user_vehicle_info"][
            "mileage"] == "":
            self.state_variables["user_vehicle_info"]["cost"] = "vehicle mileage is required to provide valuation"

        if "type" not in self.state_variables["user_vehicle_info"].keys() :
            self.state_variables["user_vehicle_info"]["type"] = ""
            
        prompt = get_prompt_template(PromptTemplate.USER_VEHICLE_INFO).format(
            vrn=self.state_variables["user_vehicle_info"]["vrn"],
            vehicle_mileage=self.state_variables["user_vehicle_info"]["mileage"],
            make=self.state_variables["user_vehicle_info"]["make"],
            model=self.state_variables["user_vehicle_info"]["model"],
            generation=self.state_variables["user_vehicle_info"]["generation"],
            price=self.state_variables["user_vehicle_info"]["cost"],
            type=self.state_variables["user_vehicle_info"]["type"])

        return prompt

    def format_messages(self):
        res = ""
        for message in self.messages:
            if message["role"] == "system":
                pass
            elif message["role"] == "assistant":
                res += r"Bot: {}\n".format(message["content"])
            elif message["role"] == "user":
                res += r"Customer: {}\n".format(message["content"])
            else:
                raise Exception(f"Message Role {message['role']} Occurred!")
        return res

    def determine_params(self, query):
        messages = self.messages
        messages.append({"role": "user", "content": query})
        response = completion(
            messages=messages,
            tools=get_function_template(FunctionTemplate.DETERMINE_PARAMS),
            tool_choice={"type": "function", "function": {"name": "determine_params"}}
        )
        # print("================================")
        # print(response.json())
        # print("================================")
        try:
            params = json.loads(
                response.json()['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        except:
            params = {}

        # print("================================")
        # print(params)
        # print("================================")
        
        return params

    def analyze_image(self, query):
        pass

    def update_message_history(self, history):
        message_history = []
        message_history.append({"role": "system", "content": get_prompt_template(PromptTemplate.SYSTEM_PROMPT)})
        for chat in history[:-1]:
            if chat.isBot:
                message_history.append({"role": "assistant", "content": chat.text})
            else:
                message_history.append({"role": "user", "content": chat.text})
        self.init_messages()
        self.messages += message_history

    def run_function(self, func):
        args = json.loads(func['arguments'])
        function_name = func["name"]
        if function_name == "send_whatsapp":
            number = args["number"]
            message = args["message"]
            number = str(number)
            if number == "0" and self.state_variables["user_contact_info"]["number"] == "":
                return "Whatsapp number was not provided before."
            else:
                if number == "0":
                    number = self.state_variables["user_contact_info"]["number"]
                number = "+" + number
                print ("!!!!", number, message)
                send_whatsapp(number, message)
                return "You sent message via whatsapp to the customer."
        elif function_name == "send_sms":
            number = args["number"]
            message = args["message"]
            number = str(number)
            if number == "0" and self.state_variables["user_contact_info"]["number"] == "":
                return "sms number was not provided before."
            else:
                if number == "0":
                    number = self.state_variables["user_contact_info"]["number"]
                number = "+" + number
                send_sms(number, message)
                return "You sent message via sms to the customer"
        elif function_name == "send_email":
            email = args["email"]
            message = args["message"]
            title = args["title"]
            if email == "" and self.state_variables["user_contact_info"]["e-mail"] == "":
                return "email address was not provided before."
            else:
                if email == "":
                    email = self.state_variables["user_contact_info"]["e-mail"]
                send_email(email, message, title)
                return "You sent message via email to the customer"
        elif function_name == "proceed_finance_reservation":
            vin = args["vin"]
            deposit = args["deposit"]
            term = args["term"]
            self.state_variables["finance_info"]["vin"] = vin
            self.state_variables["finance_info"]["deposit"] = deposit
            self.state_variables["finance_info"]["term"] = term
            self.state_variables["finance_info"]["active"] = "true"
            if args["PX"] == "true":
                self.state_variables["user_vehicle_info"]["active"] = "true"
            if term == 0:
                return "finance term is not provided."
            elif deposit == 0:
                return "finance deposit is not provided."
            else:
                self.state_variables["stripe"] = "paying"
                return "You need to tell user to fill the payment details at the top of chat panel."
        elif function_name == "proceed_direct_purchase_reservation":
            vin = args["vin"]
            self.state_variables["full_pay_info"]["vin"] = vin
            self.state_variables["full_pay_info"]["active"] = "true"
            self.state_variables["stripe"] = "paying"
            if args["PX"] == "true":
                self.state_variables["user_vehicle_info"]["active"] = "true"

            return "You need to tell user to fill the payment details at the top of chat panel."
        else:
            return "" 


    def run(self, query):
        if query == "All right. I just paid £149 to reserve.":
            self.state_variables["stripe"] = "paid"
            prompt = "\nUser just paid 149 pounds for reservation and inquery was sent to TMC sales team. TMC sales person will contact user soon with details."
            return_list = []
        else:
            prompt, return_list = self.compose_prompt(query)
        ms = self.messages
        ms.append({"role": "system", "content": prompt})

        # print("=======Prompt========")
        # print(prompt)
        # print("=====================")

        response = completion(
            messages=ms,
            tools=get_function_template(FunctionTemplate.DETERMINE_ACTIONS),
            stream=False
        )
        # for chunk in response:
        #     content = chunk['choices'][0].delta.content
        #     if content is not None:
        #         yield f"content: {json.dumps({'content': content })}\n\n".encode("utf-8")
        #     # yield f"data: {json.dumps(chunk)}\n\n"
        response = response.json()
        # print ("$#@!", response)
        if response['choices'][0]['message']["content"]:
            self.messages.append({"role": "assistant", "content": response["choices"][0]["message"]["content"]})
            return {"text": response["choices"][0]["message"]["content"], "vehicles": return_list,
                    "state": self.state_variables}
            # yield f"content: {json.dumps({ 'vehicles': return_list, 'state': self.state_variables})}\n\n".encode("utf-8")
        else:
            func = response['choices'][0]['message']['tool_calls'][0]['function']
            state = self.run_function(func)
            print("(((((", state)
            ms = self.messages
            _prompt = prompt + "\n" + state
            ms.append({"role": "system", "content": _prompt})
            response = completion(
                messages=ms
            )
            response = response.json()
            self.messages.append({ "type": "info", "role": "assistant", "content": response["choices"][0]["message"]["content"]})
            # yield f"content: {json.dumps({ 'vehicles': return_list, 'state': self.state_variables})}\n\n".encode("utf-8")
            
            
            return {"text": response["choices"][0]["message"]["content"], "vehicles": return_list,
                    "state": self.state_variables}
