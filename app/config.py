import os
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.environ["REDIS_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

STATUS_CHANNEL = "status"