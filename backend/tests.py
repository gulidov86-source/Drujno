import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # ← это загружает .env

print("Текущая директория:", os.getcwd())
print("Файл .env существует:", Path('.env').exists())
print("TELEGRAM_BOT_TOKEN:", os.getenv('TELEGRAM_BOT_TOKEN'))