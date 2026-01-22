#reset` - ডাটাবেজ রিসেট করার জন্য।
৪. **বাটন:** Start, Stop, Report (Stats), Set Email, Reset DB.

### ✅ Final Corrected Code (Copy & Paste)

```python
# -*- coding: utf-8 -*-
import logging
import os
import json
import asyncio
import random
import -*- coding: utf-8 -*-
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
    CallbackQueryHandler,
    MessageHandler,
    filters
)
import firebase_admin
from firebase_admin import credentials, db

# --- Load Environment Variables ---
load string
import requests
import time
import threading
from datetime import datetime
from flask import Flask
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application_dotenv()

# --- Configuration ---
TOKEN = os.environ.get('EMAIL_BOT_TOKEN')
, 
    CommandHandler, 
    ContextTypes, 
    CallbackQueryHandler,
    MessageHandler,
    filters
OWNER_ID = os.environ.get('BOT_OWNER_ID')
FB_JSON = os)
import firebase_admin
from firebase_admin import credentials, db

# --- Load Environment Variables ---
load_dotenv()

# --- Configuration ---
TOKEN = os.environ.get('EMAIL_BOT_TOKEN')
.environ.get('FIREBASE_CREDENTIALS_JSON')
FB_URL = os.environ.getOWNER_ID = os.environ.get('BOT_OWNER_ID')
FB_JSON = os.environ.get('FIREBASE_CREDENTIALS_JSON')
FB_URL = os.environ.get('FIREBASE_DATABASE_URL')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL('FIREBASE_DATABASE_URL')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
PORT = int(os.environ.get('PORT', '10000'))

# GAS URLs Rotation
GAS_URLS_STR = os.environ.get('GAS_URLS', '') 
')
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
CURRENT_KEY_GAS_URL_POOL = [url.strip() for url in GAS_URLS_STR.split(',') if url.strip()]

# Gemini API Keys
GEMINI_KEYS_STR = os.environ.get('GEMINI_API_KEYS', '') 
GEMINI_KEYS = [k.strip() for k in GEMINI_KEYS_STR.split(',') if k.strip()]

# --- Logging ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger =INDEX = 0
CURRENT_GAS_INDEX = 0

# --- Flask Server for Uptime ---
app logging.getLogger(__name__)

# --- Global State ---
IS_SENDING = False
CURRENT_KEY_INDEX = 0
CURRENT_GAS_INDEX = 0

# --- Flask Server for Uptime ---
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot is Alive & Running!", 200

def run_flask():
    app_flask.run(host="0.0.0.0", port=PORT)

# --- Firebase Init ---
if not firebase_admin._apps is Alive & Running!", 200

def run_flask():
    app_flask.run(host="0.0.0.0", port=PORT)

# --- Firebase Init ---
if not firebase_admin._apps:
    if FB_JSON:
        try:
            if os.path.exists(FB_JSON):
                cred = credentials.Certificate(FB_JSON)
            else:
                cred = credentials.Certificate(json.loads(FB_JSON))
            firebase_admin.initialize_app(cred, {'databaseURL': FB_URL})
            logger.info("🔥 Firebase Connected!")
        except Exception as e:
            :
    if FB_JSON:
        try:
            if os.path.exists(FB_JSON):
                cred = credentials.Certificate(FB_JSON)
            else:
                cred = credentials.Certificatelogger.error(f"❌ Firebase Auth Error: {e}")
    else:
        logger.error("❌ FIREBASE_CREDENTIALS_JSON missing!")

def is_owner(uid):
    return str(uid) == str(OWNER_ID)

# --- Helper Functions ---

def get_next_gemini(json.loads(FB_JSON))
            firebase_admin.initialize_app(cred, {'databaseURL': FB_URL})
            logger.info("🔥 Firebase Connected!")
        except Exception as e:
            logger.error(f"❌ Firebase Auth Error: {e}")
    else:
        logger.error("❌ FIREBASE_CREDENTIALS_JSON missing!")

def is_owner(uid):
    return str(_key():
    global CURRENT_KEY_INDEX
    if not GEMINI_KEYS: return None
    key = GEMINI_KEYS[CURRENT_KEY_INDEX % len(GEMINI_KEYS)]
    CURRENT_KEY_INDEX += 1
    return key

def get_next_gas_url():
    global CURRENTuid) == str(OWNER_ID)

# --- Helper Functions ---

def get_next_gemini_key():
    global CURRENT_KEY_INDEX
    if not GEMINI_KEYS: return None
    key = GEMINI_KEYS[CURRENT_KEY_INDEX % len(GEMINI_KEYS)]
    CURRENT__GAS_INDEX
    if not GAS_URL_POOL: return None
    url = GAS_URL_POOL[CURRENT_GAS_INDEX % len(GAS_URL_POOL)]
    CURRENT_GAS_INDEX += 1
    return url

def generate_random_id(length=12):
    return ''.joinKEY_INDEX += 1
    return key

def get_next_gas_url():
    global CURRENT_GAS_INDEX
    if not GAS_URL_POOL: return None
    url = GAS_URL_(random.choices(string.ascii_letters + string.digits, k=length))

async def rewrite_email_with_ai(original_sub, original_body, app_name):
    if not GEMINI_KEYS: return original_sub, original_body
    for _ in range(3):
        api_POOL[CURRENT_GAS_INDEX % len(GAS_URL_POOL)]
    CURRENT_GAS_INDEX += 1
    return url

def generate_random_id(length=12):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

async def rewrite_key = get_next_gemini_key()
        if not api_key: break
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
        prompt = f"""Rewrite email foremail_with_ai(original_sub, original_body, app_name):
    if not GEMINI_KEYS: return original_sub, original_body
    for _ in range(3):
        api_key = get_next_gemini_key()
        if not api_key: break
        url = app "{app_name}". Rules: Change greetings, keep core message, output HTML. Original: {original_sub} | {original_body} Format: Subject: [Sub] ||| Body: [Body]"""
         f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
        prompt = f"""Rewrite email fortry:
            response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
            if response.status_code == 200:
                text = response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
                if "|||" in text:
                    parts = text.split("|||")
                    return parts[0].replace("Subject app "{app_name}". Rules: Change greetings, keep core message, output HTML. Original: {original_sub} | {original_body} Format: Subject: [Sub] ||| Body: [Body]"""
        try:
            response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]:", "").strip(), parts[1].replace("Body:", "").replace("```html", "").replace("```", "").strip()
        except: pass
        await asyncio.sleep(1)
    return original_sub, original_body

def call_gas_api_rotated(payload):
    for _ in range(3):
}]}, timeout=15)
            if response.status_code == 200:
                text = response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
                if "|||" in text:
                    parts = text.split("|||")
                    return parts[0].replace("Subject:", "").strip(), parts[1].replace("Body:", "").replace("```html", "").replace("```", "").        url = get_next_gas_url()
        if not url: return {"status": "error", "msg": "No GAS URL"}
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code in [200, 30strip()
        except: pass
        await asyncio.sleep(1)
    return original_sub, original_body

def call_gas_api_rotated(payload):
    for _ in range(3):
        url = get_next_gas_url()
        if not url: return {"status": "error", "msg": "No GAS URL"}
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code in [200, 302]: return {"status": "success"}
        except: time.sleep(1)
    return {"status2]: return {"status": "success"}
        except: time.sleep(1)
    return {"status": "error", "msg": "All GAS URLs failed"}

# --- UI Functions ---
def main_menu_keyboard": "error", "msg": "All GAS URLs failed"}

# --- UI Functions ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🚀 Start Sending", callback_data='btn_start_send')],
        [InlineKeyboardButton("🛑 Stop", callback_data='btn_stop_send')],
        [():
    keyboard = [
        [InlineKeyboardButton("🚀 Start Sending", callback_data='btn_start_send')],
        [InlineKeyboardButton("🛑 Stop", callback_data='btn_stop_send')],
        [InlineKeyboardButton("📊 Report", callback_data='btn_stats'),
         InlineKeyboardButton("📝 Set Email", callbackInlineKeyboardButton("📊 Report", callback_data='btn_stats'),
         InlineKeyboardButton("📝 Set Email", callback_data='btn_set_content')],
        [InlineKeyboardButton("🔄 Reset DB", callback_data='btn_reset_all')]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='btn_main_menu')]])

# --- Core Worker Logic ---
async def email_worker(context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING
    chat_id = context.job.chat_id
    bot_id = TOKEN._data='btn_set_content')],
        [InlineKeyboardButton("🔄 Reset DB", callback_data='btn_reset_all')]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='btn_main_menu')]])

# ---split(':')[0]
    
    try:
        leads_ref = db.reference('scraped_emails')
        config_ref = db.reference('shared_config/email_template')
        config = config Core Worker Logic ---
async def email_worker(context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING
    chat_id = context.job.chat_id
    bot_id = TOKEN._ref.get()
        if not config:
            await context.bot.send_message(chat_id, "⚠️ ইমেইল টেম্পলেট নেই! /set_email দিয়ে সেট করুন।")
            IS_SENDING = False
            return
    except Exception as e:
        logger.error(f"DB Error: {e}")
        IS_SENDING = False
        return

    await context.bot.send_message(split(':')[0]
    
    try:
        leads_ref = db.reference('scraped_emails')
        config_ref = db.reference('shared_config/email_template')
        config = config_ref.get()
        if not config:
            await context.bot.send_message(chat_id, "⚠️ ইমেইল টেম্পলেট নেই! /set_email দিয়ে সেট করুন।")
            IS_chat_id, "🚀 Bot Started: Scanning & Sending...")

    while IS_SENDING:
        try:
            SENDING = False
            return
    except Exception as e:
        logger.error(f"DB Error: {e}")
        IS_SENDING = False
        return

    await context.bot.send_message(chat_id, "🚀 Bot Started: Scanning & Sending...")

    while IS_SENDING:
        try:
            # Fixed Query Logic
            query = leads_ref.order_by_child('status').limit_to_first(50).get()
            if not query:
                await context.bot.send_message(chat_id, "💤 No leads found. Waiting...")
                await asyncio.sleep(60)
                # Fixed Query Logic
            query = leads_ref.order_by_child('status').limit_to_first(50).get()
            if not query:
                await context.bot.send_message(chat_id, "💤 No leads found. Waiting...")
                await asyncio.sleep(60)
                continue

            target_key = None
            current_time = time.time()

            for key, val in query.items():
                if val.get('status') is not None: continue
                p_by = val.get('processing_by')
                l_ping = val.get('last_ping', 0)
                if p_by is None or (current_time - l_ping > 300):
                    target_key = key
                    break
            
            if not target_key:
                await asyncio.sleep(10)
                continue

            leads_ref.child(target_key).update({'processing_by': bot_id, 'last_ping': current_time})
            data = query[target_key]
            
            sub, body = await rewrite_email_with_ai(
                config.get('subject', '').replace('{app_name}', data.get('app_name', 'App')),
                config.get('body', '').replace('{app_name}', data.get('app_name', 'App')),
                data.get('app_name', 'App')
            )

            track_base = GAS_URL_POOL[0] if GAS_URL_POOL else ""
            sep = "&" if "?" in trackcontinue

            target_key = None
            current_time = time.time()

            for key, val in query.items():
                if val.get('status') is not None: continue
                p_by = val.get('processing_by')
                l_ping = val.get('last_ping', 0)
                if p_by is None or (current_time - l_ping > 300):
                    target_key = key
                    break
            
            if not target_key:
                await asyncio.sleep(10)
                continue

            leads_ref.child(target_key).update({'processing_by': bot_id, 'last_ping': current_time})
            data = query[target_key]
            
            sub, body = await rewrite_email_with_ai(
                config.get('subject', '').replace('{app_name}', data.get('app_name', 'App')),
                config.get('body', '').replace('{app_name}', data.get('app_name', 'App')),
                data.get('app_name', 'App')
            )

            track_base = GAS__base else "?"
            pixel_url = f"{track_base}{sep}action=track&id={target_key}"
            final_body = f"{body}<br><br><img src='{pixel_URL_POOL[0] if GAS_URL_POOL else ""
            sep = "&" if "?" in track_base else "?"
            pixel_url = f"{track_base}{sep}action=track&id={url}' width='1' height='1' style='display:none;'/><span style='display:none;'>Ref: {generate_random_id()}</span>"

            res = call_gas_api_rotated({"target_key}"
            final_body = f"{body}<br><br><img src='{pixel_url}' width='1' height='1' style='display:none;'/><span style='display:none;'>Ref: {generate_random_id()}</span>"

            res = call_gas_api_rotated({"action": "sendEmail", "to": data.get('email'), "subject": sub, "body": final_body})

            if res.get('status') == 'success':
                leads_ref.child(action": "sendEmail", "to": data.get('email'), "subject": sub, "body": final_body})

            if res.get('status') == 'success':
                leads_ref.child(target_key).update({'status': 'sent', 'sent_at': datetime.now().isoformat(), 'processing_by': None})
                logger.info(f"✅ Sent: {data.get('email')}")
                await asyncio.sleep(random.randint(30, 90))
            else:
                leads_ref.child(target_key).update({'processing_by': None})
                await asyncio.target_key).update({'status': 'sent', 'sent_at': datetime.now().isoformat(), 'processing_by': None})
                logger.info(f"✅ Sent: {data.get('email')sleep(5)

        except Exception as e:
            logger.error(f"Worker Error: {e}")
            await asyncio.sleep(10)

# --- Handlers ---
async def start(update: Update, context}")
                await asyncio.sleep(random.randint(30, 90))
            else:
                leads_ref.child(target_key).update({'processing_by': None})
                await asyncio.: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):sleep(5)

        except Exception as e:
            logger.error(f"Worker Error: {e}")
            await asyncio.sleep(10)

# --- Handlers ---
async def start(update: Update, context return
    await update.message.reply_text("🤖 **Email Bot Manager**\nStatus: Online", reply_markup=main_menu_keyboard())

async def button_tap(update: Update, context: Context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    await update.message.reply_text("🤖 **Email Bot Manager**\nStatus: Online", reply_markup=main_menu_keyboard())

async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING
    query = update.callback_query
    Types.DEFAULT_TYPE):
    global IS_SENDING
    query = update.callback_query
    await query.answer()
    
    if query.data == 'btn_main_menu':
        await query.edit_message_text("🤖 **Main Menu**", reply_markup=main_menu_keyboard())
    elif query.data == 'btn_start_send':
        if not IS_SENDING:
            IS_SENDING = True
            if context.job_queue:
                context.job_queue.run_onceawait query.answer()
    
    if query.data == 'btn_main_menu':
        await query.edit_message_text("🤖 **Main Menu**", reply_markup=main_menu_keyboard())
    elif(email_worker, 1, chat_id=query.message.chat_id)
                await query.edit_message_text("🚀 Sending Started...", reply_markup=back_button())
            else:
 query.data == 'btn_start_send':
        if not IS_SENDING:
            IS_                await query.edit_message_text("❌ JobQueue Error!", reply_markup=back_button())
SENDING = True
            if context.job_queue:
                context.job_queue.run_once    elif query.data == 'btn_stop_send':
        IS_SENDING = False
        await query.edit_message_text("🛑 Stopping...", reply_markup=back_button())
    elif query.data == '(email_worker, 1, chat_id=query.message.chat_id)
                await query.edit_message_text("🚀 Sending Started...", reply_markup=back_button())
            else:
                await query.edit_message_text("❌ JobQueue Error!", reply_markup=back_button())
btn_stats':
        leads = db.reference('scraped_emails').get() or {}
        sent = sum(1 for v in leads.values() if v.get('status') == 'sent')
        opened = sum(1 for v in leads.values() if v.get('status') == 'opened')
    elif query.data == 'btn_stop_send':
        IS_SENDING = False
        await query.edit_message_text("🛑 Stopping...", reply_markup=back_button())
    elif query.data == '        await query.edit_message_text(f"📊 **Stats:**\nTotal: {len(leadsbtn_stats':
        leads = db.reference('scraped_emails').get() or {}
        sent)}\nSent: {sent}\nOpened: {opened}", reply_markup=back_button())
    elif query.data == 'btn_set_content':
        await query.edit_message_text("ব্যবহার:\n`/set = sum(1 for v in leads.values() if v.get('status') == 'sent')
        opened = sum(1 for v in leads.values() if v.get('status') == 'opened')
        await query.edit_message_text(f"📊 **Stats:**\nTotal: {len(leads_email Subject | Body`", reply_markup=back_button())
    elif query.data == 'btn_reset_all':
        await query.edit_message_text("Type `/confirm_reset` to clear DB.", reply_markup=back_button())

async def set_email_cmd(u: Update, c)}\nSent: {sent}\nOpened: {opened}", reply_markup=back_button())
    elif query.data == 'btn_set_content':
        await query.edit_message_text("ব্যবহার:\n`/set: ContextTypes.DEFAULT_TYPE):
    if not is_owner(u.effective_user.id):_email Subject | Body`", reply_markup=back_button())
    elif query.data == 'btn_reset_all':
        await query.edit_message_text("Type `/confirm_reset` to clear return
    try:
        content = u.message.text.split('/set_email ', 1)[1]
        if '|' in content:
            sub, body = content.split('|', 1) DB.", reply_markup=back_button())

async def set_email_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not is_owner(u.effective_user.id):
            db.reference('shared_config/email_template').set({'subject': sub.strip(), 'body': body.strip()})
            await u.message.reply_text("✅ টেম্পলেট সেভ হয়েছে।")
        else:
            await u.message.reply_text("❌ `|` সিম্বল ব্যবহার করে সাবজেক্ট ও বডি আলাদা করুন।")
    except:
        await u.message.reply_ return
    try:
        content = u.message.text.split('/set_email ', 1)[1]
        if '|' in content:
            sub, body = content.split('|', 1)
            db.reference('shared_config/email_template').set({'subject': sub.strip(), 'bodytext("❌ ফরম্যাট ভুল।")

async def confirm_reset_cmd(u: Update, c: Context': body.strip()})
            await u.message.reply_text("✅ টেম্পলেট সেভ হয়েছেTypes.DEFAULT_TYPE):
    if not is_owner(u.effective_user.id): return
    leads = db.reference('scraped_emails').get() or {}
    count = 0
    ।")
        else:
            await u.message.reply_text("❌ `|` সিম্বল ব্যবহার করে সাবজেক্ট ও বডি আলাদা করুন।")
    except:
        await u.message.reply_text("❌ ফরম্যাট ভুল।")

async def confirm_reset_cmd(u: Update, c: Contextfor k in leads:
        db.reference(f'scraped_emails/{k}').update({'status': None, 'processing_by': None, 'last_ping': None})
        count += 1
    await u.message.reply_text(f"🔄 {count} ডাটা রিসেট সম্পন্ন।")

async def post_init(application: Application):
    logger.info("🧹 Cleaning up old webhooks...")
    await application.bot.delete_webhook(drop_pending_updates=True)

def main():
    # Types.DEFAULT_TYPE):
    if not is_owner(u.effective_user.id): return
    leads = db.reference('scraped_emails').get() or {}
    count = 0
    for k in leads:
        db.reference(f'scraped_emails/{k}').update({'status': None, 'processing_by': None, 'last_ping': None})
        count += 1
    await u1. Start Flask
    threading.Thread(target=run_flask, daemon=True).start()
    
    # 2. Setup Bot
    app = Application.builder().token(TOKEN).post_init(.message.reply_text(f"🔄 {count} ডাটা রিসেট সম্পন্ন।")

async def post_init(application: Application):
    logger.info("🧹 Cleaning up old webhooks...")
    await application.bot.delete_webhook(drop_pending_updates=True)

def main():
    # post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_email", set_email_cmd))
    app.add_handler(CommandHandler("confirm_reset", confirm_reset_cmd))
    app.add_handler(CallbackQuery1. Start Flask
    threading.Thread(target=run_flask, daemon=True).start()
    
    # 2. Setup Bot
    app = Application.builder().token(TOKEN).post_init(Handler(button_tap))
    
    logger.info("🤖 Bot is starting...")

    # 3. Run Polling
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_email", set_email_cmd))
    app.add_handler(CommandHandler("confirm_reset", confirm_reset_cmd))
    app.add_handler(CallbackQueryHandler(button_tap))
    
    logger.info("🤖 Bot is starting...")

    # 3. Run Polling
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
```pending_updates=True)

if __name__ == "__main__":
    main()
