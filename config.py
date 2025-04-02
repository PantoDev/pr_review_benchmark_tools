import os

from dotenv import load_dotenv

load_dotenv(
    dotenv_path=".envrc",
    verbose=True,
)
GEMINI_TOKEN = os.getenv("GEMINI_TOKEN")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL")
IS_GEMINI = bool(GEMINI_TOKEN and GEMINI_BASE_URL)
OPENAI_TOKEN = os.getenv("OPENAI_TOKEN")

GITHUB_TOKEN = os.getenv('GH_TOKEN')
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME')
GITHUB_EMAIL = os.getenv('GITHUB_EMAIL')
