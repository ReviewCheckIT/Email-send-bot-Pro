# -*- coding: utf-8 -*-
import logging
import os
import json
import asyncio
import random
import string
import requests
import time
import csv
import io
import re  # 🟢 NEW: Regular expression for email format check
import dns.resolver  # 🟢 NEW: For checking MX records
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    MessageHandler, 
    CallbackQueryHandler,
    filters
)
import firebase_admin
from firebase_admin import credentials, db

# 🌟 Import Google Play Scraper to fetch live icons using app_id
from google_play_scraper import app as play_app

# --- Load Environment Variables ---
load_dotenv()

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
TOKEN = os.environ.get('EMAIL_BOT_TOKEN')
OWNER_ID = os.environ.get('BOT_OWNER_ID')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
PORT = int(os.environ.get('PORT', '10000'))
GAS_URL_ENV = os.environ.get('GAS_URL')

# --- Firebase 1 (Main Leads DB) ---
FB_JSON = os.environ.get('FIREBASE_CREDENTIALS_JSON')
FB_URL = os.environ.get('FIREBASE_DATABASE_URL')

# --- Firebase 2 (History / Sent Emails DB) ---
FB_JSON_2 = os.environ.get('FIREBASE_CREDENTIALS_JSON_2')
FB_URL_2 = os.environ.get('FIREBASE_DATABASE_URL_2')

# Groq API Keys
GROQ_KEYS_STR = os.environ.get('GROQ_API_KEYS', '') 
GROQ_KEYS =[k.strip() for k in GROQ_KEYS_STR.split(',') if k.strip()]

# --- Global Control ---
IS_SENDING = False
IS_RETARGETING = False
CURRENT_KEY_INDEX = 0
BOT_ID_PREFIX = TOKEN.split(':')[0] if TOKEN else "Unknown"
RETARGET_CAMPAIGN_ID = f"camp_{int(time.time())}"  # রি-মার্কেটিং ট্র্যাক করার জন্য

# --- Helper: Send Direct Error to Owner ---
async def notify_owner(context, message):
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=f"{message}", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Notification Error: {e}")

# 🟢 NEW: Email Verification Helper Function (Sync)
def verify_email_domain_sync(email):
    if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return False, "ভুল ইমেইল ফরম্যাট"
    
    domain = email.split('@')[1]
    try:
        records = dns.resolver.resolve(domain, 'MX')
        if records:
            return True, "Valid"
    except dns.resolver.NXDOMAIN:
        return False, "ডোমেইনটির কোনো অস্তিত্ব নেই"
    except dns.resolver.NoAnswer:
        return False, "ডোমেইনে কোনো মেইল সার্ভার (MX Record) নেই"
    except Exception as e:
        return False, "সার্ভার কানেকশন সমস্যা"
        
    return False, "Unknown Error"

# 🟢 NEW: Async wrapper for Email Verification (বট যেন হ্যাং না করে)
async def verify_email_domain(email):
    return await asyncio.to_thread(verify_email_domain_sync, email)


# --- Firebase Initialization (Dual Database) ---
try:
    if not firebase_admin._apps:
        # Initialize First Firebase (Main)
        if FB_JSON:
            try:
                cred_dict = json.loads(FB_JSON) if FB_JSON.startswith("{") else FB_JSON
                cred1 = credentials.Certificate(cred_dict) if isinstance(cred_dict, dict) else credentials.Certificate(FB_JSON)
                firebase_admin.initialize_app(cred1, {'databaseURL': FB_URL})
                logger.info(f"🔥 First Firebase Connected: {BOT_ID_PREFIX}")
            except Exception as e:
                logger.error(f"❌ First Firebase Auth Error: {e}")
        
        # Initialize Second Firebase (History DB)
        if FB_JSON_2 and FB_URL_2:
            try:
                cred2_dict = json.loads(FB_JSON_2) if FB_JSON_2.startswith("{") else FB_JSON_2
                cred2 = credentials.Certificate(cred2_dict) if isinstance(cred2_dict, dict) else credentials.Certificate(FB_JSON_2)
                firebase_admin.initialize_app(cred2, {'databaseURL': FB_URL_2}, name='history_db')
                logger.info("🔥 Second Firebase (History) Connected!")
            except Exception as e:
                logger.error(f"❌ Second Firebase Auth Error: {e}")
except Exception as e:
    logger.error(f"❌ Firebase Init Error: {e}")

def get_history_db():
    try:
        return firebase_admin.get_app('history_db')
    except:
        return None

def is_owner(uid):
    return str(uid) == str(OWNER_ID)

# --- Keep Alive ---
async def keep_alive_task(context: ContextTypes.DEFAULT_TYPE):
    if not RENDER_URL: return
    while True:
        try: requests.get(RENDER_URL, timeout=20)
        except: pass
        await asyncio.sleep(600)

# --- AI Helper Functions ---
def get_next_api_key():
    global CURRENT_KEY_INDEX
    if not GROQ_KEYS: return None
    key = GROQ_KEYS[CURRENT_KEY_INDEX % len(GROQ_KEYS)]
    CURRENT_KEY_INDEX += 1
    return key

async def rewrite_email_with_ai(original_sub, original_body, target_data, context):
    app_name = target_data.get('app_name', 'Your App')
    app_id = target_data.get('app_id', '')
    app_icon = target_data.get('icon', '')

    if not app_icon or app_icon == 'N/A' or str(app_icon).strip() == '':
        if app_id and app_id != 'N/A':
            try:
                app_info = await asyncio.to_thread(play_app, app_id, lang='en', country='us')
                app_icon = app_info.get('icon', 'https://cdn-icons-png.flaticon.com/128/2267/2267777.png')
            except: app_icon = 'https://cdn-icons-png.flaticon.com/128/2267/2267777.png'
        else: app_icon = 'https://cdn-icons-png.flaticon.com/128/2267/2267777.png'
    
    try: score = f"{float(target_data.get('score', 0.0)):.1f}"
    except: score = "0.0"

    try: total_ratings_raw = int(target_data.get('total_ratings', 0))
    except: total_ratings_raw = 0
        
    total_ratings = str(total_ratings_raw)
    installs = str(target_data.get('installs', '0'))
    
    r5 = int(target_data.get('ratings_5', 0))
    r4 = int(target_data.get('ratings_4', 0))
    r3 = int(target_data.get('ratings_3', 0))
    r2 = int(target_data.get('ratings_2', 0))
    r1 = int(target_data.get('ratings_1', 0))
    
    if total_ratings_raw > 0:
        pct_5 = str(int((r5 / total_ratings_raw) * 100))
        pct_4 = str(int((r4 / total_ratings_raw) * 100))
        pct_3 = str(int((r3 / total_ratings_raw) * 100))
        pct_2 = str(int((r2 / total_ratings_raw) * 100))
        pct_1 = str(int((r1 / total_ratings_raw) * 100))
    else:
        pct_5 = pct_4 = pct_3 = pct_2 = pct_1 = "0"

    final_body = original_body.replace("{app_name}", app_name) \
                              .replace("{app_id}", app_id) \
                              .replace("{app_icon}", app_icon) \
                              .replace("{score}", score) \
                              .replace("{total_ratings}", total_ratings) \
                              .replace("{installs}", installs) \
                              .replace("{pct_5}", pct_5) \
                              .replace("{pct_4}", pct_4) \
                              .replace("{pct_3}", pct_3) \
                              .replace("{pct_2}", pct_2) \
                              .replace("{pct_1}", pct_1)

    unique_id = random.randint(1000, 9999)
    final_body += f"<br><br><small style='color:#f4f6f8; font-size: 1px;'>Ref: {unique_id}</small>"

    if not GROQ_KEYS: 
        return original_sub.replace("{app_name}", app_name).replace("{app_id}", app_id), final_body

    for i in range(len(GROQ_KEYS)):
        api_key = get_next_api_key()
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        prompt = (
    f"Act as a professional B2B email copywriter. Rewrite this email subject line for '{app_name}' "
    f"to make it unique, fresh, and completely natural to avoid automated spam filters. "
    f"STRICT RULES:\n"
    f"1. Keep the exact core meaning (App performance, growth insights, or review).\n"
    f"2. DO NOT use spam-trigger or exaggerated marketing words like 'Unlock', 'Exclusive', 'Boost', '100%', 'Guarantee', 'Urgent', or 'Free'.\n"
    f"3. Must include the app name '{app_name}' naturally.\n"
    f"4. Keep it short, clean, and professional (under 50 characters if possible).\n\n"
    f"Original Subject: {original_sub}\n\n"
    f"OUTPUT FORMAT: Return ONLY the new subject line, without quotes, labels, or extra text.")
        payload = {"model": "llama-3.3-70b-versatile", "messages":[{"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 50}

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                res_json = response.json()
                new_sub = res_json['choices'][0]['message']['content'].strip().replace('"', '')
                return new_sub.replace("{app_id}", app_id), final_body
        except: pass
        await asyncio.sleep(1)

    return original_sub.replace("{app_name}", app_name).replace("{app_id}", app_id), final_body

def get_gas_url(context):
    try:
        stored_url = db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_url').get()
        return stored_url if stored_url else GAS_URL_ENV
    except: return GAS_URL_ENV

async def call_gas_api(payload, context):
    url = get_gas_url(context)
    if not url:
        await notify_owner(context, "⚠️ GAS URL খুঁজে পাওয়া যায়নি! ডাটাবেজ বা ENV চেক করুন।")
        return {"status": "error"}
    try:
        response = requests.post(url, json=payload, timeout=60)
        if response.status_code != 200: return {"status": "error"}
        return response.json()
    except: return {"status": "error"}

def get_safe_key(email):
    if not email: return "unknown"
    return str(email).replace('.', '_').replace('@', '_at_').replace('#', '').replace('$', '').replace('[', '').replace(']', '')

# ================= MAIN WORKER (Firebase 1) =================
async def email_worker(context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING
    chat_id = context.job.chat_id
    history_app = get_history_db()
    is_first_email = True 
    
    try:
        config = db.reference('shared_config/email_template').get()
        leads_ref = db.reference('scraped_emails')
        if not config:
            await notify_owner(context, "⚠️ ইমেইল টেম্পলেট নেই। /set_email কমান্ড দিন।")
            IS_SENDING = False
            return
    except:
        IS_SENDING = False
        return

    await context.bot.send_message(chat_id, "✅ **মেইন ইমেইল সেন্ডিং** প্রসেস শুরু হয়েছে (৫-৬ মিনিট রেন্ডম ডিলে)।")

    while IS_SENDING:
        all_leads = leads_ref.get()
        if not all_leads:
            await notify_owner(context, "🏁 ডাটাবেজে কোনো ইমেইল লিস্ট নেই!")
            break
        
        target_key = next((k for k, v in all_leads.items() if v.get('processing_by') is None), None)
        if not target_key:
            await context.bot.send_message(chat_id, "🏁 সব নতুন ইমেইল পাঠানো শেষ হয়েছে।")
            break

        target_data = all_leads[target_key]
        target_email = target_data.get('email', '')
        safe_email_key = get_safe_key(target_email)

        # Duplicate Check in Firebase 2
        is_duplicate = False
        if history_app:
            history_ref = db.reference('sent_history', app=history_app)
            try:
                if history_ref.child(safe_email_key).get(): is_duplicate = True
            except: pass

        if is_duplicate:
            leads_ref.child(target_key).delete()
            await asyncio.sleep(2)
            continue

        leads_ref.child(target_key).update({'processing_by': BOT_ID_PREFIX})
        
        # 🟢 NEW: Email Verification Logic Before Sending (Main DB)
        is_valid_email, reject_reason = await verify_email_domain(target_email)
        if not is_valid_email:
            app_name = target_data.get('app_name', 'Unknown App')
            alert_msg = f"🚫 **ডেড ইমেইল স্কিপ করা হয়েছে!**\n\n*App Name:* {app_name}\n*Email:* `{target_email}`\n*সমস্যা:* {reject_reason}\n\n_(এই ইমেইলটি পাঠানো হয়নি এবং মেইন ডাটাবেজ থেকে মুছে দেওয়া হয়েছে)_"
            await notify_owner(context, alert_msg)
            
            leads_ref.child(target_key).delete()  # ডিলিট করে দিচ্ছি যেন পরে আর ট্রাই না করে
            await asyncio.sleep(2)
            continue
        # -------------------------------------------------------------

        final_sub, final_body = await rewrite_email_with_ai(config.get('subject'), config.get('body'), target_data, context)
        
        res = await call_gas_api({"action": "sendEmail", "to": target_email, "subject": final_sub, "body": final_body}, context)
        
        if is_first_email:
            status_msg = "সফল" if res.get("status") == "success" else "ব্যর্থ"
            await context.bot.send_message(chat_id, f"🚀 **কাজ শুরু হয়েছে!**\nপ্রথম ইমেইল পাঠানোর চেষ্টা ({status_msg}) সম্পন্ন হয়েছে।")
            is_first_email = False

        if res.get("status") == "success":
            if history_app:
                try:
                    target_data['sent_at'] = datetime.now().isoformat()
                    target_data['sent_by_bot'] = BOT_ID_PREFIX
                    history_ref.child(safe_email_key).set(target_data)
                except: pass
            
            leads_ref.child(target_key).delete()  
            db.reference(f'bot_configs/{BOT_ID_PREFIX}/sent_count').transaction(lambda current: (current or 0) + 1)
            await asyncio.sleep(random.randint(300, 360))
        else:
            IS_SENDING = False
            leads_ref.child(target_key).update({'processing_by': None})
            await notify_owner(context, "🛑 **GAS API Error / Limit Reached!**\nমেইল সেন্ডিং বন্ধ করা হয়েছে। দয়া করে নতুন GAS URL ড্যাশবোর্ড থেকে সেট করুন।")
            break

    IS_SENDING = False

# ================= RETARGET WORKER (Firebase 2) =================
async def retarget_worker(context: ContextTypes.DEFAULT_TYPE):
    global IS_RETARGETING, RETARGET_CAMPAIGN_ID
    chat_id = context.job.chat_id
    history_app = get_history_db()
    is_first_email = True 
    
    if not history_app:
        await context.bot.send_message(chat_id, "⚠️ দ্বিতীয় ফায়ারবেস (History DB) কানেক্ট করা নেই!")
        IS_RETARGETING = False
        return

    try:
        config = db.reference('shared_config/email_template').get()
        history_ref = db.reference('sent_history', app=history_app)
    except:
        IS_RETARGETING = False
        return

    await context.bot.send_message(chat_id, "♻️ **রি-মার্কেটিং শুরু হয়েছে!**\nহিস্ট্রি ডাটাবেস থেকে রেন্ডম টাইমে মেইল পাঠানো হচ্ছে...")

    while IS_RETARGETING:
        all_history = history_ref.get()
        if not all_history:
            await context.bot.send_message(chat_id, "⚠️ হিস্ট্রি ডাটাবেজে কোনো ইমেইল নেই!")
            break
        
        target_key = next((k for k, v in all_history.items() if v.get('retarget_campaign') != RETARGET_CAMPAIGN_ID and v.get('status') != 'dead'), None)
        
        if not target_key:
            await context.bot.send_message(chat_id, "🏁 হিস্ট্রি ডাটাবেজের সবাইকে মেইল পাঠানো শেষ!")
            break

        target_data = all_history[target_key]
        target_email = target_data.get('email', '')

        # 🟢 NEW: Email Verification Logic Before Sending (History DB)
        is_valid_email, reject_reason = await verify_email_domain(target_email)
        if not is_valid_email:
            app_name = target_data.get('app_name', 'Unknown App')
            alert_msg = f"🚫 **রি-মার্কেটিং ডেড ইমেইল স্কিপ!**\n\n*App Name:* {app_name}\n*Email:* `{target_email}`\n*সমস্যা:* {reject_reason}\n\n_(এই ইমেইলটিকে 'dead' মার্ক করা হয়েছে)_"
            await notify_owner(context, alert_msg)
            
            history_ref.child(target_key).update({
                'retarget_campaign': RETARGET_CAMPAIGN_ID,
                'status': 'dead' # ডেড মার্ক করে রাখলাম যেন ভবিষ্যতে আর ট্রাই না করে
            })
            await asyncio.sleep(2)
            continue
        # -------------------------------------------------------------

        final_sub, final_body = await rewrite_email_with_ai(config.get('subject'), config.get('body'), target_data, context)
        res = await call_gas_api({"action": "sendEmail", "to": target_email, "subject": final_sub, "body": final_body}, context)
        
        if is_first_email:
            status_msg = "সফল" if res.get("status") == "success" else "ব্যর্থ"
            await context.bot.send_message(chat_id, f"🚀 **রি-মার্কেটিং কাজ শুরু হয়েছে!**\nপ্রথম ইমেইল এটেম্পট ({status_msg}) সম্পন্ন।")
            is_first_email = False

        if res.get("status") == "success":
            history_ref.child(target_key).update({
                'retarget_campaign': RETARGET_CAMPAIGN_ID,
                'retarget_count': target_data.get('retarget_count', 0) + 1,
                'last_retargeted_at': datetime.now().isoformat()
            })
            await asyncio.sleep(random.randint(300, 360))
        else:
            IS_RETARGETING = False
            await notify_owner(context, "🛑 **GAS API Error / Limit Reached!**\nরি-মার্কেটিং বন্ধ করা হয়েছে। দয়া করে নতুন GAS URL সেট করুন।")
            break

    IS_RETARGETING = False

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    
    current_gas = get_gas_url(context)
    gas_status = current_gas if current_gas else "Not Set"
    
    keyboard = [
        [InlineKeyboardButton("🚀 শুরু করুন (Main DB)", callback_data='btn_start_send'), InlineKeyboardButton("🛑 বন্ধ করুন", callback_data='btn_stop_send')],
        [InlineKeyboardButton("📂 হিস্ট্রি ডাটাবেস (Firebase 2)", callback_data='btn_history_menu')],
        [InlineKeyboardButton("📊 রিপোর্ট", callback_data='btn_stats'), InlineKeyboardButton("📧 স্পাম চেক", callback_data='btn_spam_check')],
        [InlineKeyboardButton("🔗 Set GAS URL", callback_data='btn_set_gas'), InlineKeyboardButton("🔄 Reset Count", callback_data='btn_reset_count')]
    ]
    await update.message.reply_text(
        f"🤖 **মেইন ড্যাশবোর্ড**\nBot ID: {BOT_ID_PREFIX}\n🔗 **Active GAS URL:**\n`{gas_status}`", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='Markdown'
    )

async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING, IS_RETARGETING, RETARGET_CAMPAIGN_ID
    query = update.callback_query
    await query.answer()
    
    if query.data == 'btn_start_send':
        if not IS_SENDING:
            IS_SENDING = True
            context.job_queue.run_once(email_worker, 1, chat_id=query.message.chat_id)
            await query.edit_message_text("🚀 মেইন ডাটাবেজ থেকে ইমেইল পাঠানো শুরু হচ্ছে...")
        else: await query.message.reply_text("মেইন সেন্ডার অলরেডি কাজ করছে!")
            
    elif query.data == 'btn_stop_send':
        IS_SENDING = False
        await query.edit_message_text("🛑 মেইন ইমেইল পাঠানো বন্ধ করা হয়েছে।")

    elif query.data == 'btn_stats':
        try:
            leads = db.reference('scraped_emails').get() or {}
            sent = db.reference(f'bot_configs/{BOT_ID_PREFIX}/sent_count').get() or 0
            await query.message.reply_text(f"📊 মেইন ডাটাবেজ: অপেক্ষমান {len(leads)} টি, পাঠানো হয়েছে {sent} টি।")
        except: pass
            
    elif query.data == 'btn_spam_check':
        context.user_data['awaiting_test_email'] = True
        await query.message.reply_text("📧 আপনার টেস্ট ইমেইল এড্রেসটি লিখুন (ডাটাবেজ থেকে কোনো ডেটা ডিলিট হবে না):")

    elif query.data == 'btn_set_gas':
        context.user_data['awaiting_gas_url'] = True
        await query.message.reply_text("🔗 আপনার নতুন Google Apps Script (GAS) Web App URL টি বটের ইনবক্সে পেস্ট করুন:")

    elif query.data == 'btn_reset_count':
        db.reference(f'bot_configs/{BOT_ID_PREFIX}/sent_count').set(0)
        await query.message.reply_text("✅ Sent count reset to 0.")

    elif query.data == 'btn_history_menu':
        keyboard = [[InlineKeyboardButton("📊 হিস্ট্রি স্ট্যাটাস", callback_data='btn_history_stats')],
            [InlineKeyboardButton("📥 হিস্ট্রি ডাউনলোড (CSV)", callback_data='btn_history_dl')],[InlineKeyboardButton("♻️ রি-মার্কেটিং শুরু", callback_data='btn_start_retarget')],[InlineKeyboardButton("🛑 রি-মার্কেটিং বন্ধ", callback_data='btn_stop_retarget')],[InlineKeyboardButton("🔙 মেইন মেনু", callback_data='btn_back_main')]
        ]
        await query.edit_message_text("📂 **হিস্ট্রি প্যানেল (Firebase 2)**\nএখান থেকে আপনি আপনার সেভ করা লিডসগুলো দেখতে এবং পুনরায় মেইল পাঠাতে পারবেন।", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif query.data == 'btn_history_stats':
        history_app = get_history_db()
        if history_app:
            data = db.reference('sent_history', app=history_app).get() or {}
            await query.message.reply_text(f"📊 **হিস্ট্রি স্ট্যাটাস:**\nআপনার ২য় ডাটাবেজে মোট **{len(data)}** টি ইমেইল সুরক্ষিত আছে।", parse_mode='Markdown')
        else:
            await query.message.reply_text("⚠️ ২য় ফায়ারবেস কানেক্ট করা নেই।")

    elif query.data == 'btn_history_dl':
        history_app = get_history_db()
        if not history_app:
            await query.message.reply_text("⚠️ ২য় ফায়ারবেস কানেক্ট করা নেই।")
            return
        
        await query.message.reply_text("⏳ ডাটা ডাউনলোড হচ্ছে, দয়া করে অপেক্ষা করুন...")
        data = db.reference('sent_history', app=history_app).get() or {}
        if not data:
            await query.message.reply_text("⚠️ ডাটাবেজ খালি।")
            return
            
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['App Name', 'Email', 'Phone', 'Installs', 'Sent At', 'Retarget Count'])
        for k, v in data.items():
            cw.writerow([v.get('app_name', 'N/A'), v.get('email', 'N/A'), v.get('phone', 'N/A'), v.get('installs', 'N/A'), v.get('sent_at', 'N/A'), v.get('retarget_count', 0)])
            
        output = io.BytesIO(si.getvalue().encode('utf-8'))
        output.name = f"History_DB_{datetime.now().strftime('%Y%m%d')}.csv"
        await context.bot.send_document(query.message.chat_id, output, caption=f"✅ **হিস্ট্রি ডাটাবেজ ডাউনলোড সম্পন্ন!**\nমোট ইমেইল: {len(data)}")

    elif query.data == 'btn_start_retarget':
        if not IS_RETARGETING:
            IS_RETARGETING = True
            RETARGET_CAMPAIGN_ID = f"camp_{int(time.time())}" 
            context.job_queue.run_once(retarget_worker, 1, chat_id=query.message.chat_id)
            await query.message.reply_text("♻️ রি-মার্কেটিং ইঞ্জিন স্টার্ট করা হচ্ছে...")
        else:
            await query.message.reply_text("⚠️ রি-মার্কেটিং অলরেডি চলছে!")

    elif query.data == 'btn_stop_retarget':
        IS_RETARGETING = False
        await query.message.reply_text("🛑 রি-মার্কেটিং বন্ধ করা হয়েছে।")

    elif query.data == 'btn_back_main':
        current_gas = get_gas_url(context)
        gas_status = current_gas if current_gas else "Not Set"
        keyboard = [
            [InlineKeyboardButton("🚀 শুরু করুন (Main DB)", callback_data='btn_start_send'), InlineKeyboardButton("🛑 বন্ধ করুন", callback_data='btn_stop_send')],
            [InlineKeyboardButton("📂 হিস্ট্রি ডাটাবেস (Firebase 2)", callback_data='btn_history_menu')],
            [InlineKeyboardButton("📊 রিপোর্ট", callback_data='btn_stats'), InlineKeyboardButton("📧 স্পাম চেক", callback_data='btn_spam_check')],
            [InlineKeyboardButton("🔗 Set GAS URL", callback_data='btn_set_gas'), InlineKeyboardButton("🔄 Reset Count", callback_data='btn_reset_count')]
        ]
        await query.edit_message_text(f"🤖 **মেইন ড্যাশবোর্ড**\nBot ID: {BOT_ID_PREFIX}\n🔗 **Active GAS URL:**\n`{gas_status}`", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_spam_check_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    
    if context.user_data.get('awaiting_gas_url'):
        new_url = update.message.text.strip()
        if new_url.startswith("http"):
            db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_url').set(new_url)
            await update.message.reply_text(f"✅ নতুন GAS URL সফলভাবে সেট করা হয়েছে!\n(এটি ড্যাশবোর্ডে দেখতে /start কমান্ড দিন)")
        else:
            await update.message.reply_text("⚠️ URL টি সঠিক নয়। 'http' দিয়ে শুরু হতে হবে।")
        context.user_data['awaiting_gas_url'] = False
        return

    if context.user_data.get('awaiting_test_email'):
        test_email = update.message.text.strip()
        context.user_data['awaiting_test_email'] = False
        
        try:
            leads_ref = db.reference('scraped_emails')
            all_leads = leads_ref.get()
            if not all_leads:
                await update.message.reply_text("⚠️ মেইন ডাটাবেজে কোনো লিড নেই। টেস্ট করার জন্য অন্তত একটি লিড থাকতে হবে।")
                return
            
            target_key = next((k for k, v in all_leads.items() if v.get('processing_by') is None), None)
            if not target_key:
                await update.message.reply_text("⚠️ কোনো পেন্ডিং লিড পাওয়া যায়নি।")
                return

            target_data = all_leads[target_key].copy()
            app_name = target_data.get('app_name', 'Unknown App')
            
            config = db.reference('shared_config/email_template').get()
            if not config:
                await update.message.reply_text("⚠️ ইমেইল টেম্পলেট সেট করা নেই। /set_email কমান্ড দিন।")
                return

            await update.message.reply_text("⏳ স্প্যাম চেক ইমেইল তৈরি করা হচ্ছে (ডাটাবেজ অক্ষত থাকছে)...")
            
            final_sub, final_body = await rewrite_email_with_ai(config.get('subject'), config.get('body'), target_data, context)
            res = await call_gas_api({"action": "sendEmail", "to": test_email, "subject": final_sub, "body": final_body}, context)
            
            if res.get("status") == "success":
                await update.message.reply_text(f"✅ **স্প্যাম চেক সফল!**\n\nঅ্যাপ ডেটা: **{app_name}**\nটেস্ট মেইল পাঠানো হয়েছে: `{test_email}`\n\n*(নোট: এই লিডটি ডাটাবেজ থেকে মুছে ফেলা হয়নি এবং ২য় ডাটাবেজেও সেভ করা হয়নি)*")
            else:
                await update.message.reply_text("❌ GAS API থেকে এরর এসেছে। ইমেইল পাঠানো যায়নি।")
                
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error: {e}")

async def set_email_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not is_owner(u.effective_user.id): return
    try:
        content = u.message.text.split('/set_email ', 1)[1]
        if '|' in content:
            sub, body = content.split('|', 1)
            db.reference('shared_config/email_template').set({'subject': sub.strip(), 'body': body.strip()})
            await u.message.reply_text("✅ টেম্পলেট সেভ হয়েছে।")
        else: await u.message.reply_text("⚠️ ফরম্যাট ভুল। '|' (pipe) চিহ্ন পাওয়া যায়নি।")
    except: await u.message.reply_text("❌ ভুল ফরম্যাট! উদাহরণ: `/set_email সাবজেক্ট | বডি`")

def main():
    app = Application.builder().token(TOKEN).build()
    app.job_queue.run_once(keep_alive_task, 5)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_email", set_email_cmd))
    app.add_handler(CallbackQueryHandler(button_tap))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_spam_check_email))

    logger.info("🤖 Bot is running...")
    if RENDER_URL:
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN[-10:], webhook_url=f"{RENDER_URL}/{TOKEN[-10:]}")
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
