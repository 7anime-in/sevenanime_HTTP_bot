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
BOT_TOKEN = os.getenv(
    "BOT_TOKEN", "8895047045:AAE6uBXrMfsHy_OwW_Jx-3OegdzOpndzSWA"
)
APP_URL = os.getenv("APP_URL", "https://sevenanime-http-bot.onrender.com")

pyro_client = None

# 🧠 IN-MEMORY DATABASE FOR WEBSITE SYNC
anime_database = {}


# Enhanced Helper function: Auto Detect Anime Name, Season & Episode Number
def parse_anime_info(text: str):
  if not text:
    return "Solo Leveling", "1", 1

  # 1. Custom Anime Name Override Check (e.g., "Anime: Naruto" ya "Title: Bleach")
  explicit_name = re.search(
      r"(?:Anime|Title|Name)\s*:\s*([^|\n\r\t]+)", text, re.IGNORECASE
  )

  # 2. Season Detection (e.g., S02, Season 2, S2)
  season_match = re.search(
      r"(?:S|Season\s*)([0-9]{1,2})", text, re.IGNORECASE
  )
  season = season_match.group(1) if season_match else "1"

  # 3. Episode Detection (e.g., E12, EP12, Episode 12, [12])
  ep_match = re.search(
      r"(?:E|Ep|Episode\s*|[\s\-\_\[])([0-9]{1,3})(?:[\s\.\-\_\]]|$)",
      text,
      re.IGNORECASE,
  )
  episode = int(ep_match.group(1)) if ep_match else 1

  # 4. Extract Anime Title
  if explicit_name:
    clean_title = explicit_name.group(1).strip().title()
  else:
    # Clean filename/caption by removing tags, extensions, quality specs
    clean_title = re.sub(
        r"(?i)(S[0-9]{1,2}|Season\s*[0-9]{1,2}|E[0-9]{1,3}|Ep\s*[0-9]{1,3}|Episode\s*[0-9]{1,3}|1080p|720p|480p|FHD|HD|HEVC|x264|x265|\[.*?\]|\(.*?\)|.mp4|.mkv|.avi|Hindi|Dubbed)",
        "",
        text,
    )
    clean_title = re.sub(r"[\_\-\.]+", " ", clean_title).strip().title()

  if not clean_title or len(clean_title) < 2:
    clean_title = "Solo Leveling"

  return clean_title, season, episode


@asynccontextmanager
async def lifespan(app: FastAPI):
  global pyro_client
  print("🔄 Starting Pyrogram SevenAnime Engine...")

  pyro_client = Client(
      "sevenanime_bot_session",
      api_id=API_ID,
      api_hash=API_HASH,
      bot_token=BOT_TOKEN,
      in_memory=True,
  )

  # Command: /start
  @pyro_client.on_message(filters.command("start"))
  async def start_cmd(client, message):
    await message.reply_text(
        "👋 **SevenAnime Bot Active Hai!**\n\n"
        "Video upload ya forward karo, direct stream & download links ready ho"
        " jayenge aur website par episode auto-update ho jayega!"
    )

  # Handler: Video Receiver & Parser
  @pyro_client.on_message(filters.video | filters.document)
  async def auto_link_gen(client, message):
    media = message.video or message.document
    if not media:
      return

    chat_id = str(message.chat.id)
    msg_id = message.id
    base_url = APP_URL.rstrip("/")

    # File Info & Auto-Detection
    file_name = (
        getattr(media, "file_name", "Anime_Video.mp4") or "Anime_Video.mp4"
    )
    caption = message.caption or file_name

    anime_name, season_num, ep_num = parse_anime_info(caption)

    # Database Slug Key (e.g. "solo_leveling")
    slug_key = anime_name.lower().replace(" ", "_")

    if slug_key not in anime_database:
      anime_database[slug_key] = {"seasons": {}}

    if season_num not in anime_database[slug_key]["seasons"]:
      anime_database[slug_key]["seasons"][season_num] = []

    # Episode database update
    ep_list = anime_database[slug_key]["seasons"][season_num]
    existing_ep = next((item for item in ep_list if item["ep"] == ep_num), None)
    if existing_ep:
      existing_ep["chat_id"] = chat_id
      existing_ep["msg_id"] = msg_id
    else:
      ep_list.append({"ep": ep_num, "chat_id": chat_id, "msg_id": msg_id})
      ep_list.sort(key=lambda x: x["ep"])

    # URLs
    stream_url = f"{base_url}/stream/{chat_id}/{msg_id}"
    download_url = f"{base_url}/download/{chat_id}/{msg_id}"

    # Telegram Message Direct Post Link Logic
    if chat_id.startswith("-100"):
      clean_chat_id = chat_id[4:]
      tg_post_link = f"https://t.me/c/{clean_chat_id}/{msg_id}"
    else:
      tg_post_link = getattr(message, "link", "N/A")

    # Detailed Reply with Post Link for Easy Verification
    await message.reply_text(
        f"🎬 **SevenAnime Media Processed!**\n\n"
        f"⛩️ **Anime Name:** `{anime_name}`\n"
        f"🌀 **Season:** `{season_num}` | 📌 **Episode:** `{ep_num}`\n\n"
        f"🔍 **Verify Video Post:**\n{tg_post_link}\n\n"
        f"📺 **Stream URL:**\n`{stream_url}`\n\n"
        f"📥 **One-Click Download URL:**\n`{download_url}`",
        quote=True,
        disable_web_page_preview=True,
    )

  await pyro_client.start()
  print("🚀 SevenAnime Engine Live!")
  yield
  await pyro_client.stop()


app = FastAPI(lifespan=lifespan)

# CORS Policy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# API Endpoint for Website Player
@app.get("/api/episodes/{anime_slug}")
def get_anime_episodes(anime_slug: str):
  slug = anime_slug.lower().replace("-", "_")
  if slug in anime_database:
    return anime_database[slug]

  # Fallback sample data
  return {
      "seasons": {
          "1": [
              {"ep": 1, "chat_id": "-1004315586873", "msg_id": 80},
              {"ep": 2, "chat_id": "-1004315586873", "msg_id": 81},
          ]
      }
  }


# Streaming & Range Download Engine
async def get_media_response(
    chat_id: str,
    message_id: int,
    request: Request,
    range_header: str,
    is_download: bool = False,
):
  if not pyro_client:
    raise HTTPException(status_code=503, detail="Telegram engine offline hai.")

  try:
    msg = await pyro_client.get_messages(int(chat_id), message_id)
  except Exception as e:
    raise HTTPException(
        status_code=404, detail=f"Video message nahi mila: {str(e)}"
    )

  media = msg.video or msg.document
  if not media:
    raise HTTPException(
        status_code=400, detail="Is message me koi video nahi hai"
    )

  file_size = media.file_size
  mime_type = getattr(media, "mime_type", "video/mp4") or "video/mp4"
  file_name = (
      getattr(media, "file_name", "Anime_Video.mp4") or "Anime_Video.mp4"
  )

  from_bytes = 0
  until_bytes = file_size - 1

  if range_header:
    range_match = re.search(r"bytes=(\d+)-(\d*)", range_header)
    if range_match:
      start = range_match.group(1)
      end = range_match.group(2)
      from_bytes = int(start) if start else 0
      if end:
        until_bytes = int(end)

  chunk_length = until_bytes - from_bytes + 1

  async def media_streamer():
    async for chunk in pyro_client.stream_media(
        msg, offset=from_bytes, limit=chunk_length
    ):
      yield chunk

  headers = {
      "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
      "Accept-Ranges": "bytes",
      "Content-Length": str(chunk_length),
      "Content-Type": mime_type,
      "Access-Control-Allow-Origin": "*",
  }

  if is_download:
    encoded_filename = quote(file_name)
    headers["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{encoded_filename}"
    )

  status_code = 206 if range_header else 200
  return StreamingResponse(
      media_streamer(), status_code=status_code, headers=headers
  )


# Stream Endpoint
@app.get("/stream/{chat_id}/{message_id}")
async def stream_video(
    chat_id: str, message_id: int, request: Request, range: str = Header(None)
):
  return await get_media_response(
      chat_id, message_id, request, range, is_download=False
  )


# One-Click Download Endpoint
@app.get("/download/{chat_id}/{message_id}")
async def download_video(
    chat_id: str, message_id: int, request: Request, range: str = Header(None)
):
  return await get_media_response(
      chat_id, message_id, request, range, is_download=True
  )


@app.get("/")
def home():
  return {"status": "SevenAnime Full Engine Active 🚀"}
      
