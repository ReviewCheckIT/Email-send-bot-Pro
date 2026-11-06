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
import re  
import dns.resolver  
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
RETARGET_CAMPAIGN_ID = f"camp_{int(time.time())}"  

# =========================================================
# 🔗 MULTI-URL HELPERS (NEW)
# =========================================================

def get_all_urls():
    """Return list of (key, data) sorted by creation order (push key = time sorted)."""
    try:
        urls = db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_urls').get() or {}
        return sorted(urls.items(), key=lambda x: x[0])
    except Exception as e:
        logger.error(f"get_all_urls error: {e}")
        return []

def get_current_or_first_url():
    """Return (key, data) of active/next available URL with remaining limit, or (None, None)."""
    urls = get_all_urls()
    # 1) Any URL currently marked 'running' with remaining limit -> resume
    for key, data in urls:
        if data.get('status') == 'running' and data.get('enabled', True):
            if data.get('sent_count', 0) < data.get('limit', 0):
                return key, data
    # 2) Next pending URL in order
    for key, data in urls:
        if not data.get('enabled', True):
            continue
        if data.get('status') in ('completed', 'failed'):
            continue
        if data.get('sent_count', 0) < data.get('limit', 0):
            return key, data
    return None, None

def all_limits_exhausted():
    """True if no enabled URL with remaining limit exists."""
    for key, data in get_all_urls():
        if not data.get('enabled', True):
            continue
        if data.get('status') == 'failed':
            continue
        if data.get('sent_count', 0) < data.get('limit', 0):
            return False
    return True

def get_gas_url(context=None):
    """Get any enabled URL for retarget/spam-check. Prefers URLs with remaining limit."""
    for key, data in get_all_urls():
        if not data.get('enabled', True): continue
        if data.get('status') == 'failed': continue
        if data.get('sent_count', 0) < data.get('limit', 0):
            return data.get('url')
    # Fallback: any enabled URL (even if limit exhausted)
    for key, data in get_all_urls():
        if data.get('enabled', True) and data.get('status') != 'failed':
            return data.get('url')
    # Legacy fallback
    try:
        stored = db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_url').get()
        return stored if stored else GAS_URL_ENV
    except:
        return GAS_URL_ENV

def migrate_legacy_url():
    """One-time migration: old single gas_url -> new gas_urls/{pushKey}."""
    try:
        flag = db.reference(f'bot_configs/{BOT_ID_PREFIX}/legacy_migrated').get()
        if flag:
            return
        urls = db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_urls').get()
        if urls:
            db.reference(f'bot_configs/{BOT_ID_PREFIX}/legacy_migrated').set(True)
            return
        old_url = db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_url').get() or GAS_URL_ENV
        if old_url:
            db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_urls').push({
                'email': 'Legacy Account',
                'url': old_url,
                'limit': 999999,
                'sent_count': 0,
                'error_count': 0,
                'enabled': True,
                'status': 'pending',
                'started_at': None,
                'finished_at': None,
                'created_at': datetime.now().isoformat()
            })
            logger.info(f"✅ Migrated legacy URL")
        db.reference(f'bot_configs/{BOT_ID_PREFIX}/legacy_migrated').set(True)
    except Exception as e:
        logger.error(f"Migration error: {e}")

def save_stop_reason(reason):
    try:
        db.reference(f'bot_configs/{BOT_ID_PREFIX}/last_stop_reason').set({
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })
    except: pass

# =========================================================
# 🟢 HELPERS
# =========================================================

async def notify_owner(context, message):
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=f"{message}", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Notification Error: {e}")

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
    except Exception:
        return False, "সার্ভার কানেকশন সমস্যা"
    return False, "Unknown Error"

async def verify_email_domain(email):
    return await asyncio.to_thread(verify_email_domain_sync, email)

# --- Firebase Init (Dual) ---
try:
    if not firebase_admin._apps:
        if FB_JSON:
            try:
                cred_dict = json.loads(FB_JSON) if FB_JSON.startswith("{") else FB_JSON
                cred1 = credentials.Certificate(cred_dict) if isinstance(cred_dict, dict) else credentials.Certificate(FB_JSON)
                firebase_admin.initialize_app(cred1, {'databaseURL': FB_URL})
                logger.info(f"🔥 First Firebase Connected: {BOT_ID_PREFIX}")
            except Exception as e:
                logger.error(f"❌ First Firebase Auth Error: {e}")
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

# --- AI Helpers ---
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
            response = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                res_json = response.json()
                new_sub = res_json['choices'][0]['message']['content'].strip().replace('"', '')
                return new_sub.replace("{app_id}", app_id), final_body
        except: pass
        await asyncio.sleep(1)

    return original_sub.replace("{app_name}", app_name).replace("{app_id}", app_id), final_body

async def call_gas_api(payload, context, url=None):
    """Send to specific URL, or fallback to first available."""
    if url is None:
        url = get_gas_url(context)
    if not url:
        await notify_owner(context, "⚠️ GAS URL খুঁজে পাওয়া যায়নি!")
        return {"status": "error"}
    try:
        response = await asyncio.to_thread(requests.post, url, json=payload, timeout=60)
        if response.status_code != 200:
            return {"status": "error", "code": response.status_code}
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_safe_key(email):
    if not email: return "unknown"
    return str(email).replace('.', '_').replace('@', '_at_').replace('#', '').replace('$', '').replace('[', '').replace(']', '')

# =========================================================
# 🚀 MAIN EMAIL WORKER (Multi-URL rotation)
# =========================================================
async def email_worker(context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING
    chat_id = context.job.chat_id
    history_app = get_history_db()
    
    try:
        config = db.reference('shared_config/email_template').get()
        leads_ref = db.reference('scraped_emails')
        if not config:
            await notify_owner(context, "⚠️ ইমেইল টেম্পলেট নেই। /set_email কমান্ড দিন।")
            save_stop_reason("No email template configured")
            IS_SENDING = False
            return
    except:
        IS_SENDING = False
        return

    # Check if any URL exists
    urls = get_all_urls()
    if not urls:
        await context.bot.send_message(chat_id, "⚠️ **কোনো GAS URL সেট নেই!**\n\nআগে 'Manage GAS URLs' থেকে URL যোগ করুন।")
        save_stop_reason("No URLs configured")
        IS_SENDING = False
        return

    key, url_data = get_current_or_first_url()
    if not key:
        await context.bot.send_message(chat_id, "🏁 **সব URL-এর লিমিট শেষ** বা সব ডিজেবল।\nনতুন URL সেট করুন বা Reset Count চাপুন।")
        save_stop_reason("All URL limits exhausted at start")
        IS_SENDING = False
        return

    await context.bot.send_message(chat_id, f"✅ **মেইন ইমেইল সেন্ডিং শুরু হচ্ছে**\n📧 Active URL: `{url_data.get('email', 'N/A')}`")
    
    # Live progress message
    try:
        progress_msg = await context.bot.send_message(
            chat_id,
            f"📊 **লাইভ প্রোগ্রেস**\n"
            f"📧 `{url_data.get('email', 'N/A')}`\n"
            f"📈 {url_data.get('sent_count', 0)}/{url_data.get('limit', 0)}",
            parse_mode='Markdown'
        )
    except:
        progress_msg = None

    is_first = True

    while IS_SENDING:
        key, url_data = get_current_or_first_url()
        if not key:
            if all_limits_exhausted():
                await context.bot.send_message(chat_id, "🏁 **সব URL-এর লিমিট শেষ!**\nবট বন্ধ করা হয়েছে।")
                save_stop_reason("All URL limits exhausted")
            else:
                await context.bot.send_message(chat_id, "🏁 **কোনো সক্রিয় URL নেই** (সব ডিজেবল/ফেইল)।\nবট বন্ধ।")
                save_stop_reason("No enabled URL available")
            break

        url_email = url_data.get('email', 'N/A')
        url_ref = db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_urls/{key}')
        
        # Mark running if needed
        if url_data.get('status') != 'running':
            url_ref.update({
                'status': 'running',
                'started_at': datetime.now().isoformat()
            })

        all_leads = leads_ref.get()
        if not all_leads:
            await notify_owner(context, "🏁 ডাটাবেজে কোনো ইমেইল লিস্ট নেই!")
            save_stop_reason("No leads in DB")
            break
        
        target_key = next((k for k, v in all_leads.items() if v.get('processing_by') is None), None)
        if not target_key:
            await context.bot.send_message(chat_id, "🏁 সব নতুন ইমেইল পাঠানো শেষ হয়েছে।")
            save_stop_reason("All leads processed")
            break

        target_data = all_leads[target_key]
        target_email = target_data.get('email', '')
        safe_email_key = get_safe_key(target_email)

        # Duplicate check
        if history_app:
            history_ref = db.reference('sent_history', app=history_app)
            try:
                if history_ref.child(safe_email_key).get():
                    leads_ref.child(target_key).delete()
                    await asyncio.sleep(2)
                    continue
            except: pass

        leads_ref.child(target_key).update({'processing_by': BOT_ID_PREFIX})
        
        # Email verify
        is_valid, reject_reason = await verify_email_domain(target_email)
        if not is_valid:
            app_name = target_data.get('app_name', 'Unknown App')
            await notify_owner(context, f"🚫 **ডেড ইমেইল স্কিপ!**\nApp: {app_name}\nEmail: `{target_email}`\n{reject_reason}")
            leads_ref.child(target_key).delete()
            await asyncio.sleep(2)
            continue

        final_sub, final_body = await rewrite_email_with_ai(config.get('subject'), config.get('body'), target_data, context)
        res = await call_gas_api({"action": "sendEmail", "to": target_email, "subject": final_sub, "body": final_body}, context, url=url_data.get('url'))
        
        if is_first:
            status = "সফল" if res.get("status") == "success" else "ব্যর্থ"
            await context.bot.send_message(chat_id, f"🚀 প্রথম ইমেইল এটেম্পট ({status}) — `{url_email}`")
            is_first = False

        # Reload URL data (in case it was deleted mid-send)
        fresh_url = url_ref.get()
        if fresh_url is None:
            await asyncio.sleep(2)
            continue

        if res.get("status") == "success":
            # Save to history
            if history_app:
                try:
                    target_data['sent_at'] = datetime.now().isoformat()
                    target_data['sent_by_bot'] = BOT_ID_PREFIX
                    target_data['retarget_status'] = 'pending'
                    target_data['sent_via_url_email'] = url_email
                    history_ref.child(safe_email_key).set(target_data)
                except: pass
            
            leads_ref.child(target_key).delete()
            db.reference(f'bot_configs/{BOT_ID_PREFIX}/sent_count').transaction(lambda c: (c or 0) + 1)
            
            new_sent = (fresh_url.get('sent_count', 0) or 0) + 1
            url_ref.update({'sent_count': new_sent, 'error_count': 0})

            # Check limit
            if new_sent >= fresh_url.get('limit', 0):
                url_ref.update({
                    'status': 'completed',
                    'finished_at': datetime.now().isoformat()
                })
                await context.bot.send_message(
                    chat_id,
                    f"✅ **URL শেষ!**\n📧 `{url_email}` — {new_sent}/{fresh_url.get('limit', 0)} সম্পন্ন\n➡️ পরবর্তী URL-এ যাওয়া হচ্ছে..."
                )

            # Live progress update
            if progress_msg:
                try:
                    nk, nd = get_current_or_first_url()
                    if nd:
                        await progress_msg.edit_text(
                            f"📊 **লাইভ প্রোগ্রেস**\n"
                            f"📧 `{nd.get('email', 'N/A')}`\n"
                            f"📈 {nd.get('sent_count', 0)}/{nd.get('limit', 0)}\n"
                            f"⏱ Started: {(nd.get('started_at') or 'N/A')[:19]}",
                            parse_mode='Markdown'
                        )
                except: pass
            
            await asyncio.sleep(random.randint(300, 360))

        else:
            # Failure handling
            error_count = (fresh_url.get('error_count', 0) or 0) + 1
            leads_ref.child(target_key).update({'processing_by': None})
            
            if error_count >= 3:
                url_ref.update({'status': 'failed', 'error_count': error_count})
                await notify_owner(context, f"⚠️ URL `{url_email}` ৩ বার ফেইল!\nপরবর্তী URL-এ যাওয়া হচ্ছে...")
                await context.bot.send_message(chat_id, f"⚠️ URL `{url_email}` ফেইল → পরবর্তী URL")
                continue
            else:
                url_ref.update({'error_count': error_count})
                await asyncio.sleep(60)
                continue

    IS_SENDING = False

# =========================================================
# 🔄 RETARGET WORKER (unchanged logic, uses get_gas_url)
# =========================================================
async def retarget_worker(context: ContextTypes.DEFAULT_TYPE):
    global IS_RETARGETING, RETARGET_CAMPAIGN_ID
    chat_id = context.job.chat_id
    history_app = get_history_db()
    is_first = True 
    
    if not history_app:
        await context.bot.send_message(chat_id, "⚠️ দ্বিতীয় ফায়ারবেস কানেক্ট নেই!")
        IS_RETARGETING = False
        return

    try:
        config = db.reference('shared_config/email_template').get()
        history_ref = db.reference('sent_history', app=history_app)
        if not config:
            await context.bot.send_message(chat_id, "⚠️ ইমেইল টেমপ্লেট নেই।")
            IS_RETARGETING = False
            return
    except:
        IS_RETARGETING = False
        return

    await context.bot.send_message(chat_id, "♻️ **রি-মার্কেটিং শুরু!**")

    while IS_RETARGETING:
        all_history = history_ref.get()
        if not all_history:
            await context.bot.send_message(chat_id, "⚠️ হিস্ট্রি ডাটাবেজে কোনো ইমেইল নেই!")
            break
        
        target_key = next((k for k, v in all_history.items() if v.get('retarget_status') != 'sent' and v.get('status') != 'dead'), None)
        if not target_key:
            await context.bot.send_message(chat_id, "🏁 সব পেন্ডিং রি-মার্কেটিং শেষ!")
            break

        target_data = all_history[target_key]
        target_email = target_data.get('email', '')

        is_valid, reject_reason = await verify_email_domain(target_email)
        if not is_valid:
            app_name = target_data.get('app_name', 'Unknown App')
            await notify_owner(context, f"🚫 রি-মার্কেটিং ডেড: `{target_email}`\n{reject_reason}")
            history_ref.child(target_key).update({
                'retarget_campaign': RETARGET_CAMPAIGN_ID,
                'status': 'dead'
            })
            await asyncio.sleep(2)
            continue

        final_sub, final_body = await rewrite_email_with_ai(config.get('subject'), config.get('body'), target_data, context)
        res = await call_gas_api({"action": "sendEmail", "to": target_email, "subject": final_sub, "body": final_body}, context)
        
        if is_first:
            status = "সফল" if res.get("status") == "success" else "ব্যর্থ"
            await context.bot.send_message(chat_id, f"🚀 রি-মার্কেটিং প্রথম এটেম্পট ({status})")
            is_first = False

        if res.get("status") == "success":
            history_ref.child(target_key).update({
                'retarget_campaign': RETARGET_CAMPAIGN_ID,
                'retarget_status': 'sent',
                'retarget_count': target_data.get('retarget_count', 0) + 1,
                'last_retargeted_at': datetime.now().isoformat()
            })
            db.reference(f'bot_configs/{BOT_ID_PREFIX}/retarget_sent_count').transaction(lambda c: (c or 0) + 1)
            await asyncio.sleep(random.randint(300, 360))
        else:
            IS_RETARGETING = False
            await notify_owner(context, "🛑 GAS API Error! রি-মার্কেটিং বন্ধ।")
            break

    IS_RETARGETING = False

# =========================================================
# 🎛️ URL MANAGER VIEW
# =========================================================
async def show_url_manager(edit_func, context):
    urls = get_all_urls()
    
    if not urls:
        keyboard = [
            [InlineKeyboardButton("➕ Add First URL", callback_data='btn_url_add')],
            [InlineKeyboardButton("🔙 Back to Main", callback_data='btn_back_main')]
        ]
        text = "🔗 **GAS URL Manager**\n\nকোনো URL সেট নেই।\n\n'➕ Add First URL' চাপুন।"
        try:
            await edit_func(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except: pass
        return
    
    text = f"🔗 **GAS URL Manager**\n📊 মোট: {len(urls)} টি URL\n\n"
    keyboard = []
    
    for i, (key, data) in enumerate(urls, 1):
        email = data.get('email', 'N/A')
        sent = data.get('sent_count', 0)
        limit = data.get('limit', 0)
        enabled = data.get('enabled', True)
        status = data.get('status', 'pending')
        
        if status == 'completed': icon = "✅"
        elif status == 'failed': icon = "❌"
        elif status == 'running': icon = "🟢"
        elif not enabled: icon = "⏸"
        else: icon = "⚪"
        
        text += f"{icon} **{i}. {email}**\n"
        text += f"   {sent}/{limit} | `{status}`"
        if data.get('started_at'):
            text += f"\n   ⏱ `{data['started_at'][:19]}`"
        if data.get('finished_at'):
            text += f"\n   🏁 `{data['finished_at'][:19]}`"
        text += "\n\n"
        
        toggle_text = "⏸ Disable" if enabled else "▶️ Enable"
        toggle_cb = f'url_toggle_{key}'
        reset_cb = f'url_reset_{key}'
        del_cb = f'url_del_{key}'
        
        keyboard.append([
            InlineKeyboardButton(f"{i}. {email[:18]}", callback_data='noop'),
            InlineKeyboardButton(toggle_text, callback_data=toggle_cb),
            InlineKeyboardButton("🔄", callback_data=reset_cb),
            InlineKeyboardButton("🗑", callback_data=del_cb)
        ])
    
    keyboard.append([InlineKeyboardButton("➕ Add New URL", callback_data='btn_url_add')])
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data='btn_manage_urls'),
                     InlineKeyboardButton("🔙 Back", callback_data='btn_back_main')])
    
    try:
        await edit_func(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"show_url_manager error: {e}")

# =========================================================
# 🎛️ HANDLERS
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    
    urls = get_all_urls()
    active_email = None
    for key, data in urls:
        if data.get('enabled', True) and data.get('status') not in ('completed', 'failed') \
           and data.get('sent_count', 0) < data.get('limit', 0):
            active_email = data.get('email')
            break
    
    status_text = f"📧 Active: `{active_email}`" if active_email else "⚠️ কোনো সক্রিয় URL নেই"
    
    keyboard = [
        [InlineKeyboardButton("🚀 শুরু করুন (Main DB)", callback_data='btn_start_send'), 
         InlineKeyboardButton("🛑 বন্ধ করুন", callback_data='btn_stop_send')],
        [InlineKeyboardButton("📂 হিস্ট্রি ডাটাবেস (Firebase 2)", callback_data='btn_history_menu')],
        [InlineKeyboardButton("📊 রিপোর্ট", callback_data='btn_stats'), 
         InlineKeyboardButton("📧 স্পাম চেক", callback_data='btn_spam_check')],
        [InlineKeyboardButton("🔗 Manage GAS URLs", callback_data='btn_manage_urls'), 
         InlineKeyboardButton("🔄 Reset Count", callback_data='btn_reset_count')]
    ]
    await update.message.reply_text(
        f"🤖 **মেইন ড্যাশবোর্ড**\nBot ID: {BOT_ID_PREFIX}\n"
        f"🔗 URLs: {len(urls)}\n"
        f"{status_text}", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='Markdown'
    )

async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING, IS_RETARGETING, RETARGET_CAMPAIGN_ID
    query = update.callback_query
    await query.answer()

    # === URL Manager actions ===
    if query.data == 'btn_manage_urls':
        await show_url_manager(query.edit_message_text, context)
        return
    
    if query.data == 'btn_url_add':
        context.user_data['url_add_state'] = 'email'
        context.user_data.pop('awaiting_test_email', None)
        await query.edit_message_text(
            "➕ **নতুন URL যোগ করুন**\n\n"
            "**ধাপ ১/৩:** এই URL-এর email/account name লিখুন\n"
            "_(উদাহরণ: `user1@gmail.com`)_",
            parse_mode='Markdown'
        )
        return
    
    if query.data.startswith('url_toggle_'):
        key = query.data.replace('url_toggle_', '', 1)
        url_ref = db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_urls/{key}')
        d = url_ref.get()
        if d:
            url_ref.update({'enabled': not d.get('enabled', True)})
        await show_url_manager(query.edit_message_text, context)
        return
    
    if query.data.startswith('url_reset_'):
        key = query.data.replace('url_reset_', '', 1)
        db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_urls/{key}').update({
            'sent_count': 0, 'error_count': 0, 'status': 'pending',
            'started_at': None, 'finished_at': None
        })
        await show_url_manager(query.edit_message_text, context)
        return
    
    if query.data.startswith('url_del_'):
        key = query.data.replace('url_del_', '', 1)
        db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_urls/{key}').delete()
        await show_url_manager(query.edit_message_text, context)
        return
    
    if query.data == 'noop':
        return

    # === Main actions ===
    if query.data == 'btn_start_send':
        if not IS_SENDING:
            urls = get_all_urls()
            if not urls:
                await query.message.reply_text("⚠️ আগে 'Manage GAS URLs' থেকে URL যোগ করুন!")
                return
            IS_SENDING = True
            context.job_queue.run_once(email_worker, 1, chat_id=query.message.chat_id)
            await query.edit_message_text("🚀 ইমেইল পাঠানো শুরু হচ্ছে...")
        else:
            await query.message.reply_text("মেইন সেন্ডার অলরেডি চলছে!")
            
    elif query.data == 'btn_stop_send':
        IS_SENDING = False
        save_stop_reason("Manual stop by owner")
        await query.edit_message_text("🛑 **ইমেইল পাঠানো বন্ধ**।\nপরবর্তীতে শুরু করলে যেখানে ছিল সেখান থেকে চলবে।")

    elif query.data == 'btn_stats':
        try:
            leads = db.reference('scraped_emails').get() or {}
            sent = db.reference(f'bot_configs/{BOT_ID_PREFIX}/sent_count').get() or 0
            retarget_sent = db.reference(f'bot_configs/{BOT_ID_PREFIX}/retarget_sent_count').get() or 0
            
            urls = get_all_urls()
            url_lines = ""
            for i, (k, d) in enumerate(urls, 1):
                url_lines += f"\n{i}. `{d.get('email','N/A')}` — {d.get('sent_count',0)}/{d.get('limit',0)} ({d.get('status','pending')})"
            
            await query.message.reply_text(
                f"📊 **রিপোর্ট:**\n"
                f"- মেইন DB অপেক্ষমান: {len(leads)} টি\n"
                f"- মেইন পাঠানো: {sent} টি\n"
                f"- রি-মার্কেটিং: {retarget_sent} টি\n"
                f"\n**URL Progress:**{url_lines if url_lines else ' কোনো URL নেই'}"
            )
        except: pass
            
    elif query.data == 'btn_spam_check':
        context.user_data['awaiting_test_email'] = True
        context.user_data.pop('url_add_state', None)
        await query.message.reply_text("📧 টেস্ট ইমেইল এড্রেস লিখুন:")

    elif query.data == 'btn_reset_count':
        db.reference(f'bot_configs/{BOT_ID_PREFIX}/sent_count').set(0)
        db.reference(f'bot_configs/{BOT_ID_PREFIX}/retarget_sent_count').set(0)
        
        urls_ref = db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_urls')
        urls = urls_ref.get() or {}
        for k in urls:
            urls_ref.child(k).update({
                'sent_count': 0, 'error_count': 0, 'status': 'pending',
                'started_at': None, 'finished_at': None
            })
        
        await query.message.reply_text("✅ সব কাউন্ট রিসেট! পরবর্তী শুরু প্রথম URL থেকে হবে।")

    elif query.data == 'btn_history_menu':
        keyboard = [
            [InlineKeyboardButton("📊 হিস্ট্রি স্ট্যাটাস", callback_data='btn_history_stats')],
            [InlineKeyboardButton("📥 হিস্ট্রি ডাউনলোড (CSV)", callback_data='btn_history_dl')],
            [InlineKeyboardButton("♻️ রি-মার্কেটিং শুরু", callback_data='btn_start_retarget')],
            [InlineKeyboardButton("🛑 রি-মার্কেটিং বন্ধ", callback_data='btn_stop_retarget')],
            [InlineKeyboardButton("🔄 রিসেট রি-মার্কেটিং মার্ক", callback_data='btn_reset_retarget')],
            [InlineKeyboardButton("🔙 মেইন মেনু", callback_data='btn_back_main')]
        ]
        await query.edit_message_text("📂 **হিস্ট্রি প্যানেল (Firebase 2)**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif query.data == 'btn_history_stats':
        history_app = get_history_db()
        if history_app:
            history_ref = db.reference('sent_history', app=history_app)
            data = history_ref.get() or {}
            total = len(data)
            sent_rt = sum(1 for v in data.values() if v.get('retarget_status') == 'sent')
            pending_rt = sum(1 for v in data.values() if v.get('retarget_status') != 'sent' and v.get('status') != 'dead')
            await query.message.reply_text(
                f"📊 **হিস্ট্রি স্ট্যাটাস:**\n"
                f"- মোট ইমেইল: **{total}**\n"
                f"- রি-মার্কেটিং সম্পন্ন: **{sent_rt}**\n"
                f"- পেন্ডিং: **{pending_rt}**",
                parse_mode='Markdown'
            )
        else:
            await query.message.reply_text("⚠️ ২য় ফায়ারবেস কানেক্ট নেই।")

    elif query.data == 'btn_history_dl':
        history_app = get_history_db()
        if not history_app:
            await query.message.reply_text("⚠️ ২য় ফায়ারবেস কানেক্ট নেই।")
            return
        await query.message.reply_text("⏳ ডাউনলোড হচ্ছে...")
        data = db.reference('sent_history', app=history_app).get() or {}
        if not data:
            await query.message.reply_text("⚠️ খালি।")
            return
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['App', 'Email', 'Phone', 'Installs', 'Sent At', 'Retarget Status', 'Retarget Count', 'Sent Via URL'])
        for k, v in data.items():
            cw.writerow([v.get('app_name','N/A'), v.get('email','N/A'), v.get('phone','N/A'),
                         v.get('installs','N/A'), v.get('sent_at','N/A'),
                         v.get('retarget_status','pending'), v.get('retarget_count', 0),
                         v.get('sent_via_url_email','N/A')])
        output = io.BytesIO(si.getvalue().encode('utf-8'))
        output.name = f"History_DB_{datetime.now().strftime('%Y%m%d')}.csv"
        await context.bot.send_document(query.message.chat_id, output, caption=f"✅ মোট: {len(data)}")

    elif query.data == 'btn_start_retarget':
        if not IS_RETARGETING:
            IS_RETARGETING = True
            RETARGET_CAMPAIGN_ID = f"camp_{int(time.time())}" 
            context.job_queue.run_once(retarget_worker, 1, chat_id=query.message.chat_id)
            await query.message.reply_text("♻️ রি-মার্কেটিং স্টার্ট হচ্ছে...")
        else:
            await query.message.reply_text("⚠️ অলরেডি চলছে!")

    elif query.data == 'btn_stop_retarget':
        IS_RETARGETING = False
        await query.message.reply_text("🛑 রি-মার্কেটিং বন্ধ।")

    elif query.data == 'btn_reset_retarget':
        history_app = get_history_db()
        if history_app:
            history_ref = db.reference('sent_history', app=history_app)
            data = history_ref.get() or {}
            if data:
                for k, v in data.items():
                    if v.get('retarget_status') == 'sent':
                        history_ref.child(k).update({'retarget_status': 'pending'})
                await query.message.reply_text("✅ রি-মার্কেটিং মার্ক রিসেট!")
            else:
                await query.message.reply_text("⚠️ খালি।")
        else:
            await query.message.reply_text("⚠️ ২য় ফায়ারবেস কানেক্ট নেই।")

    elif query.data == 'btn_back_main':
        urls = get_all_urls()
        active_email = None
        for key, data in urls:
            if data.get('enabled', True) and data.get('status') not in ('completed', 'failed') \
               and data.get('sent_count', 0) < data.get('limit', 0):
                active_email = data.get('email')
                break
        status_text = f"📧 Active: `{active_email}`" if active_email else "⚠️ কোনো সক্রিয় URL নেই"
        keyboard = [
            [InlineKeyboardButton("🚀 শুরু করুন (Main DB)", callback_data='btn_start_send'), 
             InlineKeyboardButton("🛑 বন্ধ করুন", callback_data='btn_stop_send')],
            [InlineKeyboardButton("📂 হিস্ট্রি ডাটাবেস (Firebase 2)", callback_data='btn_history_menu')],
            [InlineKeyboardButton("📊 রিপোর্ট", callback_data='btn_stats'), 
             InlineKeyboardButton("📧 স্পাম চেক", callback_data='btn_spam_check')],
            [InlineKeyboardButton("🔗 Manage GAS URLs", callback_data='btn_manage_urls'), 
             InlineKeyboardButton("🔄 Reset Count", callback_data='btn_reset_count')]
        ]
        await query.edit_message_text(
            f"🤖 **মেইন ড্যাশবোর্ড**\nBot ID: {BOT_ID_PREFIX}\n"
            f"🔗 URLs: {len(urls)}\n{status_text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

# =========================================================
# 📝 TEXT INPUT HANDLER (URL add flow + Spam check)
# =========================================================
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return

    # === URL Add Flow (priority) ===
    state = context.user_data.get('url_add_state')
    if state:
        text = update.message.text.strip()
        
        if state == 'email':
            if '@' not in text:
                await update.message.reply_text("❌ সঠিক email দিন (যেমন: user@gmail.com):")
                return
            context.user_data['new_url_email'] = text
            context.user_data['url_add_state'] = 'url'
            await update.message.reply_text(
                f"✅ Email: `{text}`\n\n"
                f"**ধাপ ২/৩:** এখন GAS Web App URL দিন (`https` দিয়ে শুরু):",
                parse_mode='Markdown'
            )
            return
        
        elif state == 'url':
            if not text.startswith('http'):
                await update.message.reply_text("❌ URL `http` দিয়ে শুরু হতে হবে:")
                return
            context.user_data['new_url_url'] = text
            context.user_data['url_add_state'] = 'limit'
            await update.message.reply_text(
                f"✅ URL সেভ হয়েছে\n\n"
                f"**ধাপ ৩/৩:** এই URL-এর জন্য কতটি ইমেইল পাঠাতে চান? (সংখ্যা দিন)",
                parse_mode='Markdown'
            )
            return
        
        elif state == 'limit':
            try:
                limit = int(text)
                if limit <= 0: raise ValueError
            except:
                await update.message.reply_text("❌ সঠিক ধনাত্মক সংখ্যা দিন:")
                return
            
            email = context.user_data.get('new_url_email')
            url = context.user_data.get('new_url_url')
            
            # Save to Firebase
            try:
                db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_urls').push({
                    'email': email,
                    'url': url,
                    'limit': limit,
                    'sent_count': 0,
                    'error_count': 0,
                    'enabled': True,
                    'status': 'pending',
                    'started_at': None,
                    'finished_at': None,
                    'created_at': datetime.now().isoformat()
                })
            except Exception as e:
                await update.message.reply_text(f"❌ Save error: {e}")
                return
            
            # Clear state
            context.user_data['url_add_state'] = None
            context.user_data.pop('new_url_email', None)
            context.user_data.pop('new_url_url', None)
            
            keyboard = [[InlineKeyboardButton("🔙 URL Manager", callback_data='btn_manage_urls')]]
            await update.message.reply_text(
                f"✅ **URL সফলভাবে যোগ হয়েছে!**\n\n"
                f"📧 `{email}`\n"
                f"🎯 Limit: {limit}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return

    # === Spam Check Flow ===
    if context.user_data.get('awaiting_test_email'):
        test_email = update.message.text.strip()
        context.user_data['awaiting_test_email'] = False
        
        try:
            leads_ref = db.reference('scraped_emails')
            all_leads = leads_ref.get()
            if not all_leads:
                await update.message.reply_text("⚠️ ডাটাবেজে লিড নেই।")
                return
            
            target_key = next((k for k, v in all_leads.items() if v.get('processing_by') is None), None)
            if not target_key:
                await update.message.reply_text("⚠️ পেন্ডিং লিড নেই।")
                return

            target_data = all_leads[target_key].copy()
            app_name = target_data.get('app_name', 'Unknown App')
            
            config = db.reference('shared_config/email_template').get()
            if not config:
                await update.message.reply_text("⚠️ টেমপ্লেট নেই।")
                return

            # Use current active URL
            key, url_data = get_current_or_first_url()
            if not url_data:
                await update.message.reply_text("⚠️ কোনো সক্রিয় URL নেই।")
                return

            await update.message.reply_text(f"⏳ স্প্যাম চেক তৈরি হচ্ছে (via `{url_data.get('email')}`)...")
            
            final_sub, final_body = await rewrite_email_with_ai(config.get('subject'), config.get('body'), target_data, context)
            res = await call_gas_api(
                {"action": "sendEmail", "to": test_email, "subject": final_sub, "body": final_body},
                context, url=url_data.get('url')
            )
            
            if res.get("status") == "success":
                await update.message.reply_text(
                    f"✅ **স্প্যাম চেক সফল!**\n"
                    f"App: **{app_name}**\n"
                    f"Test→ `{test_email}`\n"
                    f"Via: `{url_data.get('email')}`\n\n"
                    f"_(লিড ডাটাবেজ অক্ষত)_"
                )
            else:
                await update.message.reply_text("❌ GAS API error। ইমেইল যায়নি।")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error: {e}")

async def set_email_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not is_owner(u.effective_user.id): return
    try:
        content = u.message.text.split('/set_email ', 1)[1]
        if '|' in content:
            sub, body = content.split('|', 1)
            db.reference('shared_config/email_template').set({'subject': sub.strip(), 'body': body.strip()})
            await u.message.reply_text("✅ টেমপ্লেট সেভ।")
        else:
            await u.message.reply_text("⚠️ '|' দিয়ে সাবজেক্ট ও বডি আলাদা করুন।")
    except:
        await u.message.reply_text("❌ ভুল ফরম্যাট। উদাহরণ: `/set_email সাবজেক্ট | বডি`")

# =========================================================
# 🚀 MAIN
# =========================================================
def main():
    # Migrate legacy URL once
    migrate_legacy_url()
    
    app = Application.builder().token(TOKEN).build()
    app.job_queue.run_once(keep_alive_task, 5)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_email", set_email_cmd))
    app.add_handler(CallbackQueryHandler(button_tap))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    logger.info("🤖 Bot is running...")
    if RENDER_URL:
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN[-10:], webhook_url=f"{RENDER_URL}/{TOKEN[-10:]}")
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
