import asyncio
import logging
import threading
import io
import time
import re
import requests
import feedparser

from flask import Flask
from bs4 import BeautifulSoup

# Selenium imports
import undetected_chromedriver as uc

from pyrogram import Client, errors, utils as pyroutils
from config import BOT, API, OWNER, CHANNEL

# Ensure proper chat/channel ID handling
pyroutils.MIN_CHAT_ID = -999999999999
pyroutils.MIN_CHANNEL_ID = -10099999999999

# Logging configuration
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

# Flask health check
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=8000)

# ——— Selenium setup ———
chrome_options = uc.ChromeOptions()
chrome_options.headless = True
# you can add more stealth flags here if needed
driver = uc.Chrome(options=chrome_options)

def fetch_page_with_selenium(url, wait: float = 2.0) -> str:
    """
    Use Selenium to navigate to the URL and return fully rendered HTML.
    """
    driver.get(url)
    time.sleep(wait)  # allow JS/challenges to complete
    return driver.page_source

def extract_size(text):
    match = re.search(r"Size:\s*(\d+(?:\.\d+)?\s*(?:GB|MB|KB))", text, re.IGNORECASE)
    return match.group(1) if match else "Unknown"

def crawl_torlock():
    rss_url = "https://www.torlock.com/movies/rss.xml"
    torrents = []

    try:
        # Parse the RSS feed
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries[:15]:  # Limit to 15 most recent entries
            try:
                # Get the torrent page URL from the guid
                torrent_page_url = entry.guid
                
                # Fetch the torrent page with Selenium
                page_html = fetch_page_with_selenium(torrent_page_url)
                page_soup = BeautifulSoup(page_html, "html.parser")
                
                # Find the download button and extract the torrent URL
                download_div = page_soup.find("div", class_="col-md-4 col-sm-4", style="text-align:center")
                if download_div:
                    torrent_url = download_div.find("a")["href"]
                    
                    # Extract title and size from the RSS entry
                    title = entry.title
                    size = extract_size(entry.description)
                    
                    torrents.append({
                        "title": title,
                        "size": size,
                        "torrent_url": torrent_url,
                        "page_url": torrent_page_url
                    })
                    
            except Exception as post_err:
                logging.error(f"Failed to parse Torlock page {entry.guid}: {post_err}")

    except Exception as e:
        logging.error(f"Failed to fetch Torlock RSS feed: {e}")

    return torrents

class MN_Bot(Client):
    MAX_MSG_LENGTH = 4000

    def __init__(self):
        super().__init__(
            "MN-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,
            plugins=dict(root="plugins"),
            workers=8
        )
        self.channel_id = CHANNEL.ID
        self.last_posted = set()
        self.seen_torrents = set()

    async def safe_send_message(self, chat_id, text, **kwargs):
        for chunk in (text[i:i+self.MAX_MSG_LENGTH] for i in range(0, len(text), self.MAX_MSG_LENGTH)):
            await self.send_message(chat_id, chunk, **kwargs)
            await asyncio.sleep(1)

    async def auto_post_torrents(self):
        while True:
            try:
                torrents = crawl_torlock()
                for t in torrents:
                    if t["torrent_url"] in self.last_posted:
                        continue

                    try:
                        # Download the torrent file
                        resp = requests.get(t["torrent_url"], timeout=10)
                        resp.raise_for_status()
                        file_bytes = io.BytesIO(resp.content)
                        filename = t["title"].replace(" ", "_") + ".torrent"
                        
                        # Create caption
                        caption = (
                            f"{t['title']}\n"
                            f"📦 {t['size']}\n"
                            f"🔗 [Source]({t['page_url']})\n"
                            "#torlock #torrent"
                        )
                        
                        # Send to channel
                        await self.send_document(
                            self.channel_id,
                            file_bytes,
                            file_name=filename,
                            caption=caption
                        )
                        
                        self.last_posted.add(t["torrent_url"])
                        logging.info(f"Posted Torlock: {t['title']}")
                        await asyncio.sleep(3)
                        
                    except Exception as e:
                        logging.error(f"Error sending Torlock file {t['torrent_url']}: {e}")

            except Exception as e:
                logging.error(f"Error in auto_post_torrents: {e}")

            await asyncio.sleep(900)

    async def start(self):
        await super().start()
        me = await self.get_me()
        BOT.USERNAME = f"@{me.username}"
        await self.send_message(
            OWNER.ID,
            text=f"{me.first_name} ✅ BOT started with Torlock support"
        )
        logging.info("MN‑Bot started with Torlock support")
        asyncio.create_task(self.auto_post_torrents())

    async def stop(self, *args):
        await super().stop()
        logging.info("MN‑Bot stopped")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    MN_Bot().run()
