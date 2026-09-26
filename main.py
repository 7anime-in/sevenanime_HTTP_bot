import os
import re
import asyncio
from urllib.parse import quote
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from pyrogram import Client, filters
from pyrogram.errors import PeerIdInvalid, ChannelInvalid, RPCError, FloodWait

# ==================== ENVIRONMENT VARIABLES ====================
API_ID = int(os.getenv("API_ID", "31169133"))
API_HASH = os.getenv("API_HASH", "b836f4b836df4cf83c2d475a5ad3b285")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8895047045:AAE6uBXrMfsHy_OwW_Jx-3OegdzOpndzSWA")
APP_URL = os.getenv("APP_URL", "https://sevenanime-http-bot.onrender.com")

CHANNEL_INPUT = os.getenv("CHANNEL_ID", "-1004315586873,-1004409520918,sevenanime_ch1")
CHANNEL_IDS = [ch.strip() for ch in CHANNEL_INPUT.split(",") if ch.strip()]

pyro_client = None
anime_database = {}

# ==================== PARSING & DATABASE LOGIC ====================
def parse_anime_info(caption: str, forward_title: str = ""):
    text = caption or ""

    # Official vs Unofficial/Fandub Detection
    dub_type = "official"
    if re.search(r"\b(unofficial|fandub|fan_dub|fan-dub|fan dub)\b", text, re.IGNORECASE) or "#unofficial" in text.lower() or "#fandub" in text.lower():
        dub_type = "unofficial"
    elif "#official" in text.lower():
        dub_type = "official"

    season_match = re.search(r"(?:Season|S)[\s\-\_]*0*(\d+)", text, re.IGNORECASE)
    season = season_match.group(1) if season_match else "1"

    ep_match = re.search(r"(?:Episode|Ep|E)[\s\-\_]*0*(\d+)", text, re.IGNORECASE)
    episode = int(ep_match.group(1)) if ep_match else 1

    explicit_name = re.search(r"(?:Anime|Title|Name)\s*:\s*([^\n\r\t|]+)", text, re.IGNORECASE)

    if explicit_name:
        raw_title = explicit_name.group(1).strip()
    elif forward_title:
        raw_title = forward_title
    else:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        raw_title = lines[0] if lines else "Unknown Anime"

    clean_title = re.sub(
        r"(?i)\b(in|hindi|dubbed|dub|sub|official|unofficial|fandub|1080p|720p|480p|fhd|hd|hevc|x264|x265|episode|season|language|quality|main channel)\b",
        "",
        raw_title,
    )
    clean_title = re.sub(r"[^\w\s]", " ", clean_title)
    clean_title = re.sub(r"\s+", " ", clean_title).strip().title()

    if not clean_title or len(clean_title) < 2:
        clean_title = "Solo Leveling"

    return clean_title, str(int(season)), episode, dub_type


def add_to_database(chat_id: str, msg_id: int, caption: str, forward_title: str):
    anime_name, season_num, ep_num, dub_type = parse_anime_info(caption, forward_title)
    slug_key = anime_name.lower().replace(" ", "_")

    if slug_key not in anime_database:
        anime_database[slug_key] = {"title": anime_name, "seasons": {}}

    anime_database[slug_key]["title"] = anime_name

    if season_num not in anime_database[slug_key]["seasons"]:
        anime_database[slug_key]["seasons"][season_num] = []

    ep_list = anime_database[slug_key]["seasons"][season_num]
    
    existing_ep = next((item for item in ep_list if item["ep"] == ep_num and item.get("type", "official") == dub_type), None)

    formatted_chat_id = chat_id if chat_id.startswith("-") or chat_id.startswith("@") or chat_id.isdigit() else f"@{chat_id}"

    if existing_ep:
        existing_ep["chat_id"] = str(formatted_chat_id)
        existing_ep["msg_id"] = msg_id
    else:
        ep_list.append({
            "ep": ep_num,
            "chat_id": str(formatted_chat_id),
            "msg_id": msg_id,
            "type": dub_type
        })
        ep_list.sort(key=lambda x: x["ep"])


async def auto_scan_channels():
    print("🔍 Auto Scanning Telegram Channels (Batch ID Scan - Unlimited Range)...")

    for ch_id in CHANNEL_IDS:
        if not ch_id:
            continue
        try:
            target_chat = int(ch_id) if (ch_id.startswith("-") or ch_id.isdigit()) else (ch_id if ch_id.startswith("@") else f"@{ch_id}")
            
            chunk_size = 100
            current_id = 1
            empty_count = 0

            while empty_count < 5:
                msg_ids = list(range(current_id, current_id + chunk_size))
                try:
                    messages = await pyro_client.get_messages(target_chat, msg_ids)
                    has_media_in_chunk = False

                    if messages:
                        for message in messages:
                            if message and not message.empty:
                                has_media_in_chunk = True
                                if message.video or message.document:
                                    caption = message.caption or getattr(message.video or message.document, "file_name", "") or ""
                                    forward_title = (
                                        message.forward_from_chat.title
                                        if message.forward_from_chat
                                        else (message.forward_sender_name or "")
                                    )
                                    add_to_database(str(target_chat), message.id, caption, forward_title)

                    if not has_media_in_chunk:
                        empty_count += 1
                    else:
                        empty_count = 0

                    current_id += chunk_size
                    await asyncio.sleep(0.1)

                except FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                except Exception as e:
                    print(f"Batch fetch info at ID {current_id}: {e}")
                    current_id += chunk_size

            print(f"✅ Channel '{target_chat}' scanned completely!")
        except Exception as e:
            print(f"⚠️ Error scanning channel {ch_id}: {e}")

# ==================== LIFECYCLE & BOT HANDLERS ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global pyro_client
    print("Starting Pyrogram Engine...")

    pyro_client = Client(
        "sevenanime_bot_session",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
    )

    @pyro_client.on_message(filters.command("start"))
    async def start_cmd(client, message):
        await message.reply_text(
            "👋 **Namaste! Welcome to SevenAnime Engine Bot**\n\n"
            "Mai aapki Telegram channel ki anime videos ko Web Player aur Website se connect karta hu.\n\n"
            "🛠 **Commands:**\n"
            "• `/start` - Check bot status\n"
            "• `/stats` - Total indexed anime and episode count",
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

    @pyro_client.on_message((filters.video | filters.document) & ~filters.command(["start", "stats"]))
    async def auto_link_gen(client, message):
        media = message.video or message.document
        if not media:
            return

        chat = message.chat
        chat_identifier = f"@{chat.username}" if chat.username else str(chat.id)
        msg_id = message.id
        base_url = APP_URL.rstrip("/")

        caption = message.caption or ""
        forward_title = (
            message.forward_from_chat.title
            if message.forward_from_chat
            else (message.forward_sender_name or "")
        )

        add_to_database(chat_identifier, msg_id, caption, forward_title)

        anime_name, season_num, ep_num, dub_type = parse_anime_info(caption, forward_title)
        stream_url = f"{base_url}/stream/{chat_identifier}/{msg_id}"
        download_url = f"{base_url}/download/{chat_identifier}/{msg_id}"

        await message.reply_text(
            f"🎬 **Added to Database!**\n\n"
            f"⛩️ **Anime:** `{anime_name}`\n"
            f"🎙️ **Type:** `{dub_type.upper()}`\n"
            f"📦 **Season:** `{season_num}` | **Episode:** `{ep_num}`\n"
            f"📺 **Stream:** `{stream_url}`\n"
            f"📥 **Download:** `{download_url}`",
            quote=True,
        )

    await pyro_client.start()
    asyncio.create_task(auto_scan_channels())
    print("SevenAnime Engine Live!")
    yield
    await pyro_client.stop()


app = FastAPI(title="SevenAnime Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Content-Length", "Accept-Ranges", "Content-Type", "Content-Disposition"],
)

# ==================== FASTAPI ENDPOINTS ====================

@app.api_route("/", methods=["GET", "HEAD"])
def home():
    return {"status": "SevenAnime Engine Active 🚀"}

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
        target_id = int(chat_id) if (chat_id.startswith("-") or chat_id.isdigit()) else (chat_id if chat_id.startswith("@") else f"@{chat_id}")
        msg = await pyro_client.get_messages(target_id, message_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Video message nahi mila: {str(e)}")

    media = msg.video or msg.document
    if not media:
        raise HTTPException(status_code=400, detail="Is message me koi video nahi hai")

    file_size = media.file_size
    file_name = getattr(media, "file_name", "Anime_Video.mp4") or "Anime_Video.mp4"

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

    if is_download:
        mime_type = "application/octet-stream"
        disposition = f"attachment; filename*=UTF-8''{quote(file_name)}"
    else:
        mime_type = "video/mp4"
        disposition = "inline"

    headers = {
        "Content-Type": mime_type,
        "Content-Disposition": disposition,
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
        "Content-Length": str(chunk_length),
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges, Content-Type, Content-Disposition",
        "Cache-Control": "no-cache",
    }

    # Browser ki HEAD Request Fix (Stream start hone se pehle browser video details check karta hai)
    if request.method == "HEAD":
        return Response(status_code=206 if range_header else 200, headers=headers)

    chunk_offset = from_bytes // (1024 * 1024)
    bytes_to_skip = from_bytes % (1024 * 1024)

    async def media_streamer():
        bytes_sent = 0
        try:
            first_chunk = True
            async for chunk in pyro_client.stream_media(msg, offset=chunk_offset):
                if first_chunk and bytes_to_skip > 0:
                    chunk = chunk[bytes_to_skip:]
                    first_chunk = False

                remaining = chunk_length - bytes_sent
                if len(chunk) >= remaining:
                    yield chunk[:remaining]
                    break

                yield chunk
                bytes_sent += len(chunk)
        except Exception as e:
            print(f"Streaming Error: {e}")

    status_code = 206 if range_header else 200
    return StreamingResponse(media_streamer(), status_code=status_code, headers=headers)


# HEAD + GET support endpoints par fix ke liye
@app.api_route("/stream/{chat_id}/{message_id}", methods=["GET", "HEAD"])
async def stream_video(chat_id: str, message_id: int, request: Request, range: str = Header(None)):
    return await get_media_response(chat_id, message_id, request, range, is_download=False)

@app.api_route("/download/{chat_id}/{message_id}", methods=["GET", "HEAD"])
async def download_video(chat_id: str, message_id: int, request: Request, range: str = Header(None)):
    return await get_media_response(chat_id, message_id, request, range, is_download=True)
    
