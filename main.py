from contextlib import asynccontextmanager
import os
import re
from urllib.parse import quote
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pyrogram import Client, filters

# Environment Variables
API_ID = int(os.getenv("API_ID", "31169133"))
API_HASH = os.getenv("API_HASH", "b836f4b836df4cf83c2d475a5ad3b285")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8895047045:AAE6uBXrMfsHy_OwW_Jx-3OegdzOpndzSWA")
APP_URL = os.getenv("APP_URL", "https://sevenanime-http-bot.onrender.com")

pyro_client = None

# 🧠 TEMPORARY DATABASE (List of latest episodes)
anime_database = {}

def parse_anime_info(text: str):
  if not text:
    return "Unknown Anime", "01", "01"
  season_match = re.search(r"(?:S|Season\s*)([0-9]{1,2})", text, re.IGNORECASE)
  season = season_match.group(1).zfill(2) if season_match else "01"
  ep_match = re.search(r"(?:E|Ep|Episode\s*|[\s\-\_\[])([0-9]{1,3})(?:[\s\.\-\_\]]|$)", text, re.IGNORECASE)
  episode = ep_match.group(1).zfill(2) if ep_match else "01"
  clean_title = re.sub(r"(?i)(S[0-9]{1,2}|Season\s*[0-9]{1,2}|E[0-9]{1,3}|Ep\s*[0-9]{1,3}|Episode\s*[0-9]{1,3}|1080p|720p|480p|FHD|HD|HEVC|x264|x265|\[.*?\]|\(.*?\)|.mp4|.mkv|.avi|Hindi|Dubbed)", "", text)
  clean_title = re.sub(r"[\_\-\.]+", " ", clean_title).strip().title()
  if not clean_title or len(clean_title) < 2:
    clean_title = "Anime Series"
  return clean_title, season, episode

@asynccontextmanager
async def lifespan(app: FastAPI):
  global pyro_client
  pyro_client = Client("sevenanime_bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

  @pyro_client.on_message(filters.video | filters.document)
  async def auto_link_gen(client, message):
    media = message.video or message.document
    if not media: return

    chat_id = str(message.chat.id)
    msg_id = message.id
    caption = message.caption or getattr(media, "file_name", "")
    anime_name, season_num, ep_num = parse_anime_info(caption)

    # 💾 DATA SAVE KAR RAHE HAIN API KE LIYE
    search_key = anime_name.lower().replace(" ", "_") # e.g. "solo_leveling"
    anime_database[search_key] = {
        "title": anime_name,
        "season": season_num,
        "episode": ep_num,
        "chat_id": chat_id,
        "msg_id": msg_id
    }

    await message.reply_text(f"✅ Website Auto-Updated for: {anime_name} S{season_num} E{ep_num}", quote=True)

  await pyro_client.start()
  yield
  await pyro_client.stop()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 🌐 NEW API: WEBSITE KO LATEST EPISODE DENE KE LIYE
@app.get("/api/latest/{anime_name}")
def get_latest_episode(anime_name: str):
    search_key = anime_name.lower().replace(" ", "_")
    if search_key in anime_database:
        return {"status": "success", "data": anime_database[search_key]}
    return {"status": "error", "message": "Anime not found"}

async def get_media_response(chat_id, message_id, range_header, is_download=False):
  msg = await pyro_client.get_messages(int(chat_id), message_id)
  media = msg.video or msg.document
  file_size = media.file_size
  mime_type = getattr(media, "mime_type", "video/mp4") or "video/mp4"
  file_name = getattr(media, "file_name", "video.mp4") or "video.mp4"
  
  from_bytes = 0
  until_bytes = file_size - 1
  if range_header:
    range_match = re.search(r"bytes=(\d+)-(\d*)", range_header)
    if range_match:
      from_bytes = int(range_match.group(1))
      until_bytes = int(range_match.group(2)) if range_match.group(2) else until_bytes
  
  chunk_length = until_bytes - from_bytes + 1
  async def media_streamer():
    async for chunk in pyro_client.stream_media(msg, offset=from_bytes, limit=chunk_length): yield chunk
  
  headers = {"Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}", "Accept-Ranges": "bytes", "Content-Length": str(chunk_length), "Content-Type": mime_type}
  if is_download: headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(file_name)}"
  return StreamingResponse(media_streamer(), status_code=206 if range_header else 200, headers=headers)

@app.get("/stream/{chat_id}/{message_id}")
async def stream_video(chat_id: str, message_id: int, range: str = Header(None)):
  return await get_media_response(chat_id, message_id, range, is_download=False)

@app.get("/download/{chat_id}/{message_id}")
async def download_video(chat_id: str, message_id: int, range: str = Header(None)):
  return await get_media_response(chat_id, message_id, range, is_download=True)
    
