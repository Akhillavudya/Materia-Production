from dotenv import load_dotenv
import os

load_dotenv()

MODEL_PROVIDER = os.getenv("MODEL_PROVIDER")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")