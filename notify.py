import os
import requests
from dotenv import load_dotenv

load_dotenv()

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

def notify(message):
    requests.post(WEBHOOK_URL, json={"content": message})

if __name__ == "__main__":
    notify("🏨 テスト通知：hotel-deal-watcher 稼働確認")