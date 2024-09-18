from enum import Enum
from glob import glob
from logging import getLogger
from logging.config import fileConfig
from os.path import join, isfile
from os import environ
from json import loads
from dotenv import load_dotenv

TOP_K = 5


class ModelType(str, Enum):
    gpt4 = 'gpt-4-turbo'
    gpt3 = 'gpt-3.5-turbo'
    embedding = 'text-embedding-ada-002'
    embedding_v3_small = "text-embedding-3-small"
    embedding_v3_large = "text-embedding-3-large"
    encoding = "cl100k_base"
    palm2 = 'palm/chat-bison-001'
    codey = 'palm/codechat-bison-001'


PROJECT_ROOT = ""
LOG_INI = join(PROJECT_ROOT, 'log.ini')
FIXTURES = join(PROJECT_ROOT, 'fixture')
VEHICLE_WITH_VIDEO_JSON = join(FIXTURES, "vehicles_with_video.json")
FRONTEND_URL = "https://ai.tmcmotors.co.uk"
BACKEND_URL = "http://localhost:8000"
# BACKEND_URL = "https://api-app.tmcmotors.co.uk"
GET_STOCK_URL = BACKEND_URL + "/api/vehicle/getAll"
VALUATION_URL = BACKEND_URL + "/api/autotrader/valuation"
SEND_SMS_URL = BACKEND_URL + "/api/twilio/sendsms"
SEND_EMAIL_URL = BACKEND_URL + "/api/main/sendmail"
FINANCE_LIMIT = BACKEND_URL + "/api/finance/limit"
FINANCE_CALC = BACKEND_URL + "/api/finance/calculate"
VALIDATE_POSTCODE = BACKEND_URL + "/api/main/validatePostcode"
CALC_DISTANCE = BACKEND_URL + "/api/main/calcRoadDistance"
RETRIEVE_VEHICLE_URL = BACKEND_URL + "/api/autotrader/retrieveVehicleByRegistration"

SQL_DB = join(FIXTURES, "vehicle.db")

class ModelChoice(Enum):
    OPENAI = "gpt-4-0125-preview"
    ANTHROPIC = "anthropic/claude-3-opus-20240229"


class PromptTemplate(Enum):
    AIO_PROMPT = "AIO.txt"
    SYSTEM_PROMPT = "system.txt"
    USER_CONTACT_INFO = "user_contact_info.txt"
    USER_VEHICLE_INFO = "user_vehicle_info.txt"
    USER_LOCATION_INFO = "user_location_info.txt"
    USER_FINANCE_INFO = "user_finance_info.txt"
    REFERENCE_VEHICLE_COST = "reference_vehicle_cost.txt"
    REFERENCE_VEHICLE_WITH_VIDEO_COST = "reference_vehicle_with_video_cost.txt"


class FunctionTemplate(Enum):
    DETERMINE_PARAMS = "determine_params.json"
    DETERMINE_ACTIONS = "determine_actions.json"


def load_env():
    load_dotenv(join(PROJECT_ROOT, ".env"), override=True)


def get_prompt_template(prompt_template: PromptTemplate):
    with open(join(PROJECT_ROOT, "prompt_templates", prompt_template.value), "rt") as f:
        return f.read()


def get_function_template(function_template: FunctionTemplate):
    with open(join(PROJECT_ROOT, "function_templates", function_template.value), "r") as f:
        return loads(f.read())


logging_configured = False


def configure_logging(get_logger=False):
    global logging_configured
    if not logging_configured:
        fileConfig(LOG_INI)
        logging_configured = True
    if get_logger:
        logger = getLogger('tmc')
        return logger
