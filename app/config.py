"""Application configuration. No third-party API credentials are needed."""

import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_PATH = os.getenv("DATABASE_PATH", "running_coach.db")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1024"))
MAX_XML_MB = int(os.getenv("MAX_XML_MB", "2048"))
# Required for the iOS-to-API sync endpoint. Keep this private and use HTTPS outside local development.
SYNC_API_TOKEN = os.getenv("SYNC_API_TOKEN", "")

# Optional: Google Gemini API key for natural language AI coaching plans
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

if MAX_UPLOAD_MB < 1 or MAX_XML_MB < 1:
    raise ValueError("MAX_UPLOAD_MB and MAX_XML_MB must be positive integers")

