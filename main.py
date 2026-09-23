from contextlib import asynccontextmanager
import os
import re
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

# Dynamic global client variable
pyro_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
  global pyro_client
  print("🔄 Active Event Loop par Pyrogram Client start ho raha hai...")

  # Initialize Client inside active event loop
  pyro_client = Client(
      "sevenanime_bot_session",
      api_id=API_ID,
      api_hash=API_HASH,
      bot_token=BOT_TOKEN,
      in_memory=True,
  )

  # Handler 1: /start Command (DM)
  @pyro_client.on_message(filters.command("start"))
  async def start_cmd(client, message):
    print(f"✅ /start received from {message.chat.id}")
    await message.reply_text(
        "👋 **SevenAnime Bot Active Hai!**\n\nVideo upload karo, direct stream"
        " link ready ho jayega!"
    )

  # Handler 2: Video Receiver (Channel, Group & DM)
  @pyro_client.on_message(filters.video | filters.document)
  async def auto_link_gen(client, message):
    media = message.video or message.document
    if not media:
      return

    chat_id = str(message.chat.id)
    msg_id = message.id
    base_url = APP_URL.rstrip("/")
    stream_url = f"{base_url}/stream/{chat_id}/{msg_id}"
    file_name = (
        getattr(media, "file_name", "Anime_Video.mp4") or "Anime_Video.mp4"
    )

    await message.reply_text(
        f"🎬 **Direct Stream Link Ready!**\n\n📁 **File Name:**"
        f" `{file_name}`\n🔗 **Direct Video URL:**\n`{stream_url}`",
        quote=True,
    )

  await pyro_client.start()
  print("🚀 Pyrogram Engine Live! Bot ab har message listen kar raha hai.")
  yield
  print("🛑 Stopping Pyrogram Engine...")
  await pyro_client.stop()


app = FastAPI(lifespan=lifespan)

# Allow Cross-Origin Requests for HTML5 Player
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Direct Fast Streaming Engine Endpoint
@app.get("/stream/{chat_id}/{message_id}")
async def stream_video(
    chat_id: str, message_id: int, request: Request, range: str = Header(None)
):
  if not pyro_client:
    raise HTTPException(
        status_code=503, detail="Telegram engine start nahi hua hai."
    )

  try:
    target_chat = int(chat_id)
    msg = await pyro_client.get_messages(target_chat, message_id)
  except Exception as e:
    raise HTTPException(
        status_code=404, detail=f"Video message not found: {str(e)}"
    )

  media = msg.video or msg.document
  if not media:
    raise HTTPException(
        status_code=400, detail="No video file found in this message"
    )

  file_size = media.file_size
  mime_type = getattr(media, "mime_type", "video/mp4") or "video/mp4"

  from_bytes = 0
  until_bytes = file_size - 1

  if range:
    range_match = re.search(r"bytes=(\d+)-(\d*)", range)
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

  status_code = 206 if range else 200
  return StreamingResponse(
      media_streamer(), status_code=status_code, headers=headers
  )


@app.get("/")
def home():
  return {"status": "Sevenanime Engine Active 🚀"}
    
