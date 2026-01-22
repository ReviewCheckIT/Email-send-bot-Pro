# -*- coding: utf-8 -*-
import logging
import os
import json
import asyncio
import random
import string
import requests
import time
import threading
from datetime import datetime
from flask import Flask
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    CallbackQueryHandler
)
import firebase_admin
from firebase_admin import credentials, db

# --- Load Environment Variables ---
load_dotenv()

# --- Configuration ---
TOKEN = os.environ.get('EMAIL_BOT_TOKEN')
OWNER_ID = os.environ.get('BOT_OWNER_ID')
FB_JSON = os.environ.get('FIREBASE_CREDENTIALS_JSON')
FB_URL = os.environ.get('FIREBASE_DATABASE_URL')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
PORT = int(os.environ.get('PORT', '10000'))

# GAS URLs Rotation
GAS_URLS_STR = os.environ.get('GAS_URLS', '') 
GAS_URL_POOL = [url.strip() for url in GAS_URLS_STR.split(',') if url.strip()]

# Gemini API Keys
GEMINI_KEYS_STR = os.environ.get('GEMINI_API_KEYS', '') 
GEMINI_KEYS = [k.strip() for k in GEMINI_KEYS_STR.split(',') if k.strip()]

# --- Logging ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Global State ---
IS_SENDING = False
CURRENT_KEY_INDEX = 0
CURRENT_GAS_INDEX = 0

# --- Flask Server for Uptime ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Alive & Running!", 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# --- Firebase Init ---
if not firebase_admin._apps:
    if FB_JSON:
        if os.path.exists(FB_JSON):
            cred = credentials.Certificate(FB_JSON)
        else:
            cred = credentials.Certificate(json.loads(FB_JSON))
        firebase_admin.initialize_app(cred, {'databaseURL': FB_URL})
    else:
        logger.error("❌ FIREBASE_CREDENTIALS_JSON missing!")

# --- Helper Functions ---

def get_next_gemini_key():
    global CURRENT_KEY_INDEX
    if not GEMINI_KEYS: return None
    key = GEMINI_KEYS[CURRENT_KEY_INDEX % len(GEMINI_KEYS)]
    CURRENT_KEY_INDEX += 1
    return key

def get_next_gas_url():
    global CURRENT_GAS_INDEX
    if not GAS_URL_POOL: return None
    url = GAS_URL_POOL[CURRENT_GAS_INDEX % len(GAS_URL_POOL)]
    CURRENT_GAS_INDEX += 1
    return url

def generate_random_id(length=12):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

async def rewrite_email_with_ai(original_sub, original_body, app_name):
    """Rewrites email using Gemini 2.0 Flash."""
    if not GEMINI_KEYS: return original_sub, original_body

    for _ in range(3): # Retry 3 times
        api_key = get_next_gemini_key()
        if not api_key: break

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
        
        prompt = f"""
        Rewrite this cold email for app "{app_name}".
        RULES:
        1. Change greetings and sentence structure completely.
        2. Keep core message (Organic installs, reviews).
        3. Output HTML format (use <br>).
        4. Do NOT change links or "Skyzone IT".
        5. FORMAT: Subject: [New Subject] ||| Body: [New HTML Body]
        
        Original Subject: {original_sub}
        Original Body: {original_body}
        """
        
        try:
            response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
            if response.status_code == 200:
                text = response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
                if "|||" in text:
                    parts = text.split("|||")
                    return parts[0].replace("Subject:", "").strip(), parts[1].replace("Body:", "").replace("```html", "").replace("```", "").strip()
        except Exception as e:
            logger.error(f"AI Error: {e}")
        await asyncio.sleep(1)

    return original_sub, original_body

def call_gas_api_rotated(payload):
    """Rotates GAS URLs with retries."""
    for _ in range(3): # Try 3 different URLs
        url = get_next_gas_url()
        if not url: return {"status": "error", "msg": "No GAS URL"}
        try:
            # GAS redirects (302) to success page usually, allow_redirects=True handles it
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code in [200, 302]:
                return {"status": "success"}
        except Exception as e:
            logger.warning(f"GAS Fail ({url}): {e}")
            time.sleep(1)
    return {"status": "error", "msg": "All GAS URLs failed"}

# --- Core Worker Logic ---
async def email_worker(context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING
    chat_id = context.job.chat_id
    bot_id = TOKEN.split(':')[0]
    
    leads_ref = db.reference('scraped_emails')
    config_ref = db.reference('shared_config/email_template')

    await context.bot.send_message(chat_id, "🚀 Bot Started: Scanning for leads...")

    while IS_SENDING:
        try:
            # 1. OPTIMIZED FETCH: Only fetch leads where status is None (Limit 50 to save bandwidth)
            # This prevents fetching 30k leads every loop.
            query = leads_ref.order_by_child('status').equal_to(None).limit_to_first(50).get()
            
            if not query:
                await context.bot.send_message(chat_id, "💤 No new leads found. Waiting...")
                await asyncio.sleep(60)
                continue

            target_key = None
            current_time = time.time()

            # 2. LOCKING MECHANISM
            for key, val in query.items():
                p_by = val.get('processing_by')
                l_ping = val.get('last_ping', 0)
                
                # Check if Free OR Stale Lock (> 5 mins)
                if p_by is None or (current_time - l_ping > 300):
                    target_key = key
                    break
            
            if not target_key:
                await asyncio.sleep(10) # All 50 fetched are busy, wait a bit
                continue

            # 3. ACQUIRE LOCK
            leads_ref.child(target_key).update({
                'processing_by': bot_id,
                'last_ping': current_time
            })

            # 4. PREPARE DATA
            data = query[target_key]
            email = data.get('email')
            app_name = data.get('app_name', 'App')
            
            config = config_ref.get()
            if not config: 
                logger.error("No Config Found")
                break

            # 5. AI REWRITE
            sub, body = await rewrite_email_with_ai(
                config.get('subject', '').replace('{app_name}', app_name),
                config.get('body', '').replace('{app_name}', app_name),
                app_name
            )

            # 6. INJECT TRACKING & SPAM PROTECTION
            # We use the FIRST GAS URL for tracking pixel to keep it consistent, or rotate if needed.
            track_base = GAS_URL_POOL[0] if GAS_URL_POOL else ""
            # Ensure URL ends correctly for query params
            sep = "&" if "?" in track_base else "?"
            pixel_url = f"{track_base}{sep}action=track&id={target_key}"
            
            ref_id = generate_random_id()
            final_body = f"{body}<br><br><img src='{pixel_url}' width='1' height='1' alt='' style='display:none;'/><span style='display:none;font-size:0px;'>Ref: {ref_id}</span>"

            # 7. SEND VIA GAS
            res = call_gas_api_rotated({
                "action": "sendEmail",
                "to": email,
                "subject": sub,
                "body": final_body
            })

            # 8. UPDATE STATUS
            if res.get('status') == 'success':
                leads_ref.child(target_key).update({
                    'status': 'sent',
                    'sent_at': datetime.now().isoformat(),
                    'sent_by': bot_id,
                    'processing_by': None # Release lock
                })
                logger.info(f"✅ Sent: {email}")
                await asyncio.sleep(random.randint(30, 90)) # Random delay
            else:
                # Failed: Release lock so others can try
                leads_ref.child(target_key).update({'processing_by': None})
                logger.error(f"❌ Failed: {email}")
                await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"Worker Error: {e}")
            await asyncio.sleep(10)

# --- Telegram Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != OWNER_ID: return
    kb = [[InlineKeyboardButton("▶️ Start", callback_data='start'), InlineKeyboardButton("⏹️ Stop", callback_data='stop')]]
    await update.message.reply_text("🤖 **Email Bot Manager**", reply_markup=InlineKeyboardMarkup(kb))

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING
    q = update.callback_query
    await q.answer()
    if q.data == 'start':
        if not IS_SENDING:
            IS_SENDING = True
            context.job_queue.run_once(email_worker, 1, chat_id=q.message.chat_id)
            await q.edit_message_text("✅ Bot Started.")
    elif q.data == 'stop':
        IS_SENDING = False
        await q.edit_message_text("🛑 Bot Stopping...")

def main():
    # Start Flask in background thread
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    
    if RENDER_URL:
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{RENDER_URL}/{TOKEN}")
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
