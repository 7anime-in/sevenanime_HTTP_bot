from contextlib import asynccontextmanager
import json
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

CHANNEL_IDS = os.getenv("CHANNEL_ID", "-1004315586873,-1004409520918").split(",")

pyro_client = None
anime_database = {}


def parse_anime_info(caption: str, forward_title: str = ""):
  text = caption or ""

  # 1. Season Extraction (e.g. "Season - 01" or "S01")
  season_match = re.search(
      r"(?:Season|S)[\s\-\_]*0*(\d+)", text, re.IGNORECASE
  )
  season = season_match.group(1) if season_match else "1"

  # 2. Episode Extraction (e.g. "Episode - 02" or "Ep 02")
  ep_match = re.search(
      r"(?:Episode|Ep|E)[\s\-\_]*0*(\d+)", text, re.IGNORECASE
  )
  episode = int(ep_match.group(1)) if ep_match else 1

  # 3. Dynamic Anime Title Cleaning
  explicit_name = re.search(
      r"(?:Anime|Title|Name)\s*:\s*([^\n\r\t|]+)", text, re.IGNORECASE
  )

  if explicit_name:
    raw_title = explicit_name.group(1).strip()
  elif forward_title:
    raw_title = forward_title
  else:
    # First line fallback
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    raw_title = lines[0] if lines else "Unknown Anime"

  # Clean noise words from Title
  clean_title = re.sub(
      r"(?i)\b(in|hindi|dubbed|dub|sub|official|1080p|720p|480p|fhd|hd|hevc|x264|x265|episode|season|language|quality|main channel)\b",
      "",
      raw_title,
  )
  clean_title = re.sub(r"[^\w\s]", " ", clean_title)
  clean_title = re.sub(r"\s+", " ", clean_title).strip().title()

  if not clean_title or len(clean_title) < 2:
    clean_title = "Solo Leveling"

  return clean_title, str(int(season)), episode


def add_to_database(chat_id: str, msg_id: int, caption: str, forward_title: str):
  anime_name, season_num, ep_num = parse_anime_info(caption, forward_title)
  slug_key = anime_name.lower().replace(" ", "_")

  if slug_key not in anime_database:
    anime_database[slug_key] = {"title": anime_name, "seasons": {}}

  anime_database[slug_key]["title"] = anime_name

  if season_num not in anime_database[slug_key]["seasons"]:
    anime_database[slug_key]["seasons"][season_num] = []

  ep_list = anime_database[slug_key]["seasons"][season_num]
  existing_ep = next((item for item in ep_list if item["ep"] == ep_num), None)

  if existing_ep:
    existing_ep["chat_id"] = str(chat_id)
    existing_ep["msg_id"] = msg_id
  else:
    ep_list.append({"ep": ep_num, "chat_id": str(chat_id), "msg_id": msg_id})
    ep_list.sort(key=lambda x: x["ep"])


async def auto_scan_channels():
  print("🔍 Auto Scanning Telegram Channels for All Animes...")

  for ch_id in CHANNEL_IDS:
    ch_id = ch_id.strip()
    if not ch_id:
      continue
    try:
      # Invite Link, Username, ya Integer ID handle karne ke liye
      if ch_id.startswith("-100") or (ch_id.startswith("-") and ch_id[1:].isdigit()) or ch_id.isdigit():
        target_chat = int(ch_id)
      else:
        target_chat = ch_id

      # Fetch Chat details (handles Invite links and resolve hashes)
      chat_info = await pyro_client.get_chat(target_chat)

      # limit=0 means unlimited scanning
      async for message in pyro_client.get_chat_history(
          chat_info.id, limit=0
      ):
        media = message.video or message.document
        if media:
          caption = message.caption or getattr(media, "file_name", "") or ""
          forward_title = (
              message.forward_from_chat.title
              if message.forward_from_chat
              else (message.forward_sender_name or "")
          )
          add_to_database(str(chat_info.id), message.id, caption, forward_title)
      print(f"✅ Channel '{chat_info.title}' ({chat_info.id}) scanned successfully!")
    except Exception as e:
      print(f"⚠️ Error scanning channel {ch_id}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
  global pyro_client
  print("Starting Pyrogram Engine...")

  pyro_client = Client(
      "sevenanime_bot_session",
      api_id=API_ID,
      api_hash=API_HASH,
      bot_token=BOT_TOKEN,
      in_memory=True,
  )

  # BOT COMMAND HANDLERS
  @pyro_client.on_message(filters.command("start"))
  async def start_cmd(client, message):
    await message.reply_text(
        "👋 **Namaste! Welcome to SevenAnime Engine Bot**\n\n"
        "Mai aapki Telegram channel ki anime videos ko Web Player aur Website se connect karta hu.\n\n"
        "🛠 **Commands:**\n"
        "• `/start` - Check bot status\n"
        "• `/stats` - Total indexed anime and episode count\n\n"
        "📌 **How to use:** Channel me video upload karo, mai automatically Stream link generate kar dunga!",
        quote=True,
    )

  @pyro_client.on_message(filters.command("stats"))
  async def stats_cmd(client, message):
    total_anime = len(anime_database)
    total_eps = sum(
        len(ep_list)
        for anime in anime_database.values()
        for ep_list in anime.get("seasons", {}).values()
    )
    await message.reply_text(
        f"📊 **Database Statistics:**\n\n"
        f"⛩️ **Total Anime:** `{total_anime}`\n"
        f"🎬 **Total Episodes:** `{total_eps}`",
        quote=True,
    )

  # AUTO LINK GENERATOR FOR MEDIA
  @pyro_client.on_message((filters.video | filters.document) & ~filters.command(["start", "stats"]))
  async def auto_link_gen(client, message):
    media = message.video or message.document
    if not media:
      return

    chat_id = str(message.chat.id)
    msg_id = message.id
    base_url = APP_URL.rstrip("/")

    caption = message.caption or ""
    forward_title = (
        message.forward_from_chat.title
        if message.forward_from_chat
        else (message.forward_sender_name or "")
    )

    add_to_database(chat_id, msg_id, caption, forward_title)

    anime_name, season_num, ep_num = parse_anime_info(caption, forward_title)
    stream_url = f"{base_url}/stream/{chat_id}/{msg_id}"
    download_url = f"{base_url}/download/{chat_id}/{msg_id}"

    await message.reply_text(
        f"🎬 **Added to Database!**\n\n"
        f"⛩️ **Anime:** `{anime_name}`\n"
        f"📦 **Season:** `{season_num}` | **Episode:** `{ep_num}`\n"
        f"📺 **Stream:** `{stream_url}`\n"
        f"📥 **Download:** `{download_url}`",
        quote=True,
    )

  await pyro_client.start()
  await auto_scan_channels()
  print("SevenAnime Engine Live!")
  yield
  await pyro_client.stop()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Content-Length", "Accept-Ranges"],
)


@app.get("/api/all-anime")
def get_all_anime():
  return anime_database


@app.get("/api/episodes/{anime_slug}")
def get_anime_episodes(anime_slug: str):
  slug = anime_slug.lower().replace("-", "_")
  if slug in anime_database:
    return anime_database[slug]

  for key in anime_database:
    if slug in key or key in slug:
      return anime_database[key]

  return {"title": slug.replace("_", " ").title(), "seasons": {"1": []}}


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
    target_id = (
        int(chat_id) if (chat_id.startswith("-") or chat_id.isdigit()) else chat_id
    )
    chat_obj = await pyro_client.get_chat(target_id)
    msg = await pyro_client.get_messages(chat_obj.id, message_id)
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
  file_name = (
      getattr(media, "file_name", "Anime_Video.mp4") or "Anime_Video.mp4"
  )
  mime_type = getattr(media, "mime_type", "video/mp4") or "video/mp4"

  from_bytes = 0
  until_bytes = file_size - 1

  if range_header:
    range_match = re.search(r"bytes=(\d+)-(\d*)", range_header)
    if range_match:
      start = range_match.group(1)
      end = range_match.group(2)
      from_bytes = int(start) if start else 0
      until_bytes = int(end) if end else file_size - 1

  chunk_length = until_bytes - from_bytes + 1
  
  # Calculate 1MB chunk offset and precise remaining bytes alignment
  chunk_offset = from_bytes // (1024 * 1024)
  bytes_to_skip = from_bytes % (1024 * 1024)

  async def media_streamer():
    try:
      first_chunk = True
      async for chunk in pyro_client.stream_media(
          msg, offset=chunk_offset
      ):
        if first_chunk and bytes_to_skip > 0:
          chunk = chunk[bytes_to_skip:]
          first_chunk = False
        yield chunk
    except Exception as e:
      print(f"Streaming Error: {e}")

  headers = {
      "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
      "Accept-Ranges": "bytes",
      "Content-Length": str(chunk_length),
      "Content-Type": mime_type,
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "*",
      "Access-Control-Expose-Headers": (
          "Content-Range, Content-Length, Accept-Ranges"
      ),
      "Cache-Control": "no-cache",
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


@app.get("/stream/{chat_id}/{message_id}")
async def stream_video(
    chat_id: str, message_id: int, request: Request, range: str = Header(None)
):
  return await get_media_response(
      chat_id, message_id, request, range, is_download=False
  )


@app.get("/download/{chat_id}/{message_id}")
async def download_video(
    chat_id: str, message_id: int, request: Request, range: str = Header(None)
):
  return await get_media_response(
      chat_id, message_id, request, range, is_download=True
  )


@app.get("/")
def home():
  return {"status": "SevenAnime Engine Active 🚀"}
    
