# -*- coding: utf-8 -*-
import logging
import os
import json
import asyncio
import random
import string
import requests
import time
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

# --- Load Environment Variables ---
load_dotenv()

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
TOKEN = os.environ.get('EMAIL_BOT_TOKEN')
OWNER_ID = os.environ.get('BOT_OWNER_ID')
FB_JSON = os.environ.get('FIREBASE_CREDENTIALS_JSON')
FB_URL = os.environ.get('FIREBASE_DATABASE_URL')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
PORT = int(os.environ.get('PORT', '10000'))
GAS_URL_ENV = os.environ.get('GAS_URL')

# Groq API Keys
GROQ_KEYS_STR = os.environ.get('GROQ_API_KEYS', '') 
GROQ_KEYS =[k.strip() for k in GROQ_KEYS_STR.split(',') if k.strip()]

# --- Global Control ---
IS_SENDING = False
CURRENT_KEY_INDEX = 0
BOT_ID_PREFIX = TOKEN.split(':')[0] if TOKEN else "Unknown"

# --- Helper: Send Direct Error to Owner ---
async def notify_owner(context, message):
    """মালিককে সরাসরি টেলিগ্রামে সমস্যার কথা জানাবে"""
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=f"⚠️ **বট এলার্ট!**\n\n{message}")
    except Exception as e:
        logger.error(f"Notification Error: {e}")

# --- Firebase Initialization ---
try:
    if not firebase_admin._apps:
        if FB_JSON:
            try:
                if os.path.exists(FB_JSON):
                    cred = credentials.Certificate(FB_JSON)
                else:
                    cred_dict = json.loads(FB_JSON)
                    cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {'databaseURL': FB_URL})
                logger.info(f"🔥 Firebase Connected: {BOT_ID_PREFIX}")
            except Exception as e:
                logger.error(f"❌ Firebase Auth Error: {e}")
        else:
            logger.warning("⚠️ FIREBASE_CREDENTIALS_JSON missing!")
except Exception as e:
    logger.error(f"❌ Firebase Init Error: {e}")

def is_owner(uid):
    return str(uid) == str(OWNER_ID)

# --- Keep Alive ---
async def keep_alive_task(context: ContextTypes.DEFAULT_TYPE):
    if not RENDER_URL:
        await notify_owner(context, "RENDER_EXTERNAL_URL সেট করা নেই। বট স্লিপ মোডে চলে যেতে পারে!")
        return
    
    while True:
        try:
            requests.get(RENDER_URL, timeout=20)
            logger.info("📡 Keep-alive sent.")
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")
        await asyncio.sleep(600)

# --- AI Helper Functions ---
def get_next_api_key():
    global CURRENT_KEY_INDEX
    if not GROQ_KEYS: return None
    key = GROQ_KEYS[CURRENT_KEY_INDEX % len(GROQ_KEYS)]
    CURRENT_KEY_INDEX += 1
    return key

async def rewrite_email_with_ai(original_sub, original_body, target_data, context):
    """
    AI Logic Updated for Exact Play Store Interface:
    1. Formats score to exactly 1 decimal place (e.g. 3.7878 -> 3.8).
    2. Calculates actual percentage widths for 1 to 5 stars histogram.
    """
    # Extract basic app data
    app_name = target_data.get('app_name', 'Your App')
    
    # 🌟 NEW: Format Score to exactly 1 decimal place
    try:
        raw_score = float(target_data.get('score', 0.0))
        score = f"{raw_score:.1f}"  # Converts 3.7878788 to '3.8' (or '3.7' if it was 3.74)
    except Exception:
        score = "0.0"

    total_ratings_raw = target_data.get('total_ratings', 0)
    try:
        total_ratings_raw = int(total_ratings_raw)
    except:
        total_ratings_raw = 0
        
    total_ratings = str(total_ratings_raw)
    installs = str(target_data.get('installs', '0'))
    
    # Extract individual ratings
    r5 = int(target_data.get('ratings_5', 0))
    r4 = int(target_data.get('ratings_4', 0))
    r3 = int(target_data.get('ratings_3', 0))
    r2 = int(target_data.get('ratings_2', 0))
    r1 = int(target_data.get('ratings_1', 0))
    
    # Calculate percentages for the HTML progress bar width
    if total_ratings_raw > 0:
        pct_5 = str(int((r5 / total_ratings_raw) * 100))
        pct_4 = str(int((r4 / total_ratings_raw) * 100))
        pct_3 = str(int((r3 / total_ratings_raw) * 100))
        pct_2 = str(int((r2 / total_ratings_raw) * 100))
        pct_1 = str(int((r1 / total_ratings_raw) * 100))
    else:
        pct_5 = pct_4 = pct_3 = pct_2 = pct_1 = "0"

    # Fallback / Manual Replace logic if AI fails
    def manual_replace(sub, body):
        replaced_body = body.replace("{app_name}", app_name) \
                            .replace("{score}", score) \
                            .replace("{total_ratings}", total_ratings) \
                            .replace("{installs}", installs) \
                            .replace("{pct_5}", pct_5) \
                            .replace("{pct_4}", pct_4) \
                            .replace("{pct_3}", pct_3) \
                            .replace("{pct_2}", pct_2) \
                            .replace("{pct_1}", pct_1)
        return sub, replaced_body

    if not GROQ_KEYS:
        await notify_owner(context, "Groq API Key পাওয়া যাচ্ছে না! ENV ফাইল চেক করুন।")
        return manual_replace(original_sub, original_body)

    for i in range(len(GROQ_KEYS)):
        api_key = get_next_api_key()
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        # --- Updated Prompt for Groq AI ---
        prompt = (
            f"Task: Prepare email for sending.\n"
            f"Target App Data:\n"
            f"- App Name: {app_name}\n"
            f"- Score: {score}\n"
async def rewrite_email_with_ai(original_sub, original_body, target_data, context):
    """
    AI Logic Updated to PREVENT HTML CUT-OFF:
    1. Python handles the entire HTML replacement (100% safe, fast, and no truncation).
    2. AI is ONLY used to rewrite the subject line to avoid spam.
    """
    # Extract basic app data
    app_name = target_data.get('app_name', 'Your App')
    
    # Format Score to exactly 1 decimal place
    try:
        raw_score = float(target_data.get('score', 0.0))
        score = f"{raw_score:.1f}"
    except Exception:
        score = "0.0"

    total_ratings_raw = target_data.get('total_ratings', 0)
    try:
        total_ratings_raw = int(total_ratings_raw)
    except:
        total_ratings_raw = 0
        
    total_ratings = str(total_ratings_raw)
    installs = str(target_data.get('installs', '0'))
    
    # Extract individual ratings
    r5 = int(target_data.get('ratings_5', 0))
    r4 = int(target_data.get('ratings_4', 0))
    r3 = int(target_data.get('ratings_3', 0))
    r2 = int(target_data.get('ratings_2', 0))
    r1 = int(target_data.get('ratings_1', 0))
    
    # Calculate percentages for the HTML progress bar width
    if total_ratings_raw > 0:
        pct_5 = str(int((r5 / total_ratings_raw) * 100))
        pct_4 = str(int((r4 / total_ratings_raw) * 100))
        pct_3 = str(int((r3 / total_ratings_raw) * 100))
        pct_2 = str(int((r2 / total_ratings_raw) * 100))
        pct_1 = str(int((r1 / total_ratings_raw) * 100))
    else:
        pct_5 = pct_4 = pct_3 = pct_2 = pct_1 = "0"

    # 🌟 ALWAYS DO HTML REPLACEMENT IN PYTHON (This prevents the code cut-off issue)
    final_body = original_body.replace("{app_name}", app_name) \
                              .replace("{score}", score) \
                              .replace("{total_ratings}", total_ratings) \
                              .replace("{installs}", installs) \
                              .replace("{pct_5}", pct_5) \
                              .replace("{pct_4}", pct_4) \
                              .replace("{pct_3}", pct_3) \
                              .replace("{pct_2}", pct_2) \
                              .replace("{pct_1}", pct_1)

    # Append unique signature to avoid spam
    unique_id = random.randint(1000, 9999)
    final_body += f"<br><br><small style='color:#f4f6f8;'>Ref: {unique_id}</small>"

    # If no AI keys, return manual replacement
    if not GROQ_KEYS:
        return original_sub.replace("{app_name}", app_name), final_body

    # Ask AI ONLY to rewrite the Subject Line
    for i in range(len(GROQ_KEYS)):
        api_key = get_next_api_key()
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        prompt = (
            f"Rewrite this email subject to make it unique and avoid spam filters. "
            f"Keep the meaning same. Include the app name '{app_name}' if it fits naturally.\n"
            f"Original Subject: {original_sub}\n\n"
            f"OUTPUT FORMAT: Return ONLY the new subject line, nothing else."
        )

        payload = {
            "model": "llama-3.3-70b-versatile", 
            "messages":[{"role": "user", "content": prompt}], 
            "temperature": 0.7,
            "max_tokens": 50 # Limit tokens to make it super fast
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                res_json = response.json()
                new_sub = res_json['choices'][0]['message']['content'].strip().replace('"', '')
                return new_sub, final_body
        except Exception as e:
            logger.error(f"AI Error: {e}")
        await asyncio.sleep(1)

    # Fallback if AI fails
    return original_sub.replace("{app_name}", app_name), final_body

# --- Helper Functions ---
def get_gas_url(context):
    try:
        stored_url = db.reference(f'bot_configs/{BOT_ID_PREFIX}/gas_url').get()
        return stored_url if stored_url else GAS_URL_ENV
    except Exception as e:
        return GAS_URL_ENV

async def call_gas_api(payload, context):
    url = get_gas_url(context)
    if not url:
        await notify_owner(context, "GAS URL খুঁজে পাওয়া যায়নি! ডাটাবেজ বা ENV চেক করুন।")
        return {"status": "error"}
    try:
        response = requests.post(url, json=payload, timeout=60)
        if response.status_code != 200:
            await notify_owner(context, f"GAS API রেসপন্স এরর: {response.status_code}\nআপনার Google Script পাবলিশ করা আছে কি না চেক করুন।")
            return {"status": "error"}
        return response.json()
    except Exception as e:
        await notify_owner(context, f"GAS কানেকশন ফেইল্ড: {str(e)}")
        return {"status": "error"}

# --- Background Worker ---
async def email_worker(context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING
    chat_id = context.job.chat_id
    
    try:
        config = db.reference('shared_config/email_template').get()
        leads_ref = db.reference('scraped_emails')
        if not config:
            await notify_owner(context, "ইমেইল টেম্পলেট (email_template) ফায়ারবেসে নেই। /set_email কমান্ড দিন।")
            IS_SENDING = False
            return
    except Exception as e:
        await notify_owner(context, f"ফায়ারবেস রিড এরর: {str(e)}")
        IS_SENDING = False
        return

    await context.bot.send_message(chat_id, "✅ ইমেইল সেন্ডিং প্রসেস সফলভাবে শুরু হয়েছে।")

    while IS_SENDING:
        # Fetch fresh data each loop
        all_leads = leads_ref.get()
        if not all_leads:
            await notify_owner(context, "ডেটাবেজে কোনো ইমেইল লিস্ট (scraped_emails) নেই!")
            break
        
        # Find next pending lead (processing_by is None)
        target_key = next((k for k, v in all_leads.items() if v.get('processing_by') is None), None)
        if not target_key:
            await context.bot.send_message(chat_id, "🏁 সব ইমেইল পাঠানো শেষ হয়েছে।")
            break

        # Mark as processing
        leads_ref.child(target_key).update({'processing_by': BOT_ID_PREFIX})
        target_data = all_leads[target_key]
        
        # Get AI Rewritten Content (Passing full target_data)
        final_sub, final_body = await rewrite_email_with_ai(
            config.get('subject'), 
            config.get('body'), 
            target_data, 
            context
        )
        
        # Send via GAS
        res = await call_gas_api({
            "action": "sendEmail", 
            "to": target_data.get('email'), 
            "subject": final_sub, 
            "body": final_body
        }, context)
        
        if res.get("status") == "success":
            leads_ref.child(target_key).delete()  # lead removed from DB
            
            # Increment sent count (atomically)
            counter_ref = db.reference(f'bot_configs/{BOT_ID_PREFIX}/sent_count')
            counter_ref.transaction(lambda current: (current or 0) + 1)
            
            # Timer (Random 5-6 minutes)
            await asyncio.sleep(random.randint(300, 360))
        else:
            leads_ref.child(target_key).update({'processing_by': None})
            await notify_owner(context, f"ইমেইল পাঠাতে ব্যর্থ: {target_data.get('email')}\nGAS স্ক্রিপ্ট লগ চেক করুন।")
            await asyncio.sleep(60)

    IS_SENDING = False

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    await update.message.reply_text(f"🤖 **বট অনলাইন**\nBot ID: {BOT_ID_PREFIX}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 শুরু করুন", callback_data='btn_start_send')],
        [InlineKeyboardButton("🛑 বন্ধ করুন", callback_data='btn_stop_send')],
        [InlineKeyboardButton("📊 রিপোর্ট", callback_data='btn_stats')],[InlineKeyboardButton("📧 স্পাম চেক", callback_data='btn_spam_check')],[InlineKeyboardButton("🗑️ সেন্ড মেইল মুছুন", callback_data='btn_delete_sent')],[InlineKeyboardButton("🔄 Reset Count", callback_data='btn_reset_count')]
    ]))

async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_SENDING
    query = update.callback_query
    await query.answer()
    
    if query.data == 'btn_start_send':
        if not IS_SENDING:
            IS_SENDING = True
            context.job_queue.run_once(email_worker, 1, chat_id=query.message.chat_id)
            await query.edit_message_text("🚀 প্রসেস স্টার্ট হচ্ছে... কোনো সমস্যা হলে আপনাকে জানানো হবে।")
        else:
            await query.message.reply_text("বট অলরেডি কাজ করছে!")
            
    elif query.data == 'btn_stop_send':
        IS_SENDING = False
        await query.edit_message_text("🛑 ইমেইল পাঠানো বন্ধ করা হয়েছে। বর্তমান লুপ শেষ হলে বট পুরোপুরি থেমে যাবে।")
        await notify_owner(context, "ইউজার কমান্ডের মাধ্যমে কাজ বন্ধ করা হয়েছে।")

    elif query.data == 'btn_stats':
        try:
            leads = db.reference('scraped_emails').get() or {}
            counter_ref = db.reference(f'bot_configs/{BOT_ID_PREFIX}/sent_count')
            sent = counter_ref.get() or 0
            await query.message.reply_text(f"📊 স্ট্যাটাস: মোট ইমেইল {len(leads)}, পাঠানো হয়েছে {sent}")
        except:
            await notify_owner(context, "স্ট্যাটাস দেখাতে সমস্যা হচ্ছে। ফায়ারবেস কানেকশন চেক করুন.")
            
    elif query.data == 'btn_spam_check':
        context.user_data['awaiting_test_email'] = True
        await query.message.reply_text("📧 আপনার টেস্ট ইমেইল এড্রেসটি লিখুন (যেমন: myemail@gmail.com):")

    elif query.data == 'btn_delete_sent':
        await query.message.reply_text("🗑️ সেন্ড হওয়া মেইল খোঁজা হচ্ছে এবং ডিলিট করা হচ্ছে...")
        try:
            leads_ref = db.reference('scraped_emails')
            all_leads = leads_ref.get()
            
            if not all_leads:
                await query.message.reply_text("⚠️ ডাটাবেজে কোনো মেইল নেই।")
                return

            keys_to_delete =[k for k, v in all_leads.items() if v.get('status') == 'sent']
            
            if not keys_to_delete:
                await query.message.reply_text("⚠️ ডিলিট করার মতো কোনো 'Sent' মেইল পাওয়া যায়নি।")
                return

            updates = {key: None for key in keys_to_delete}
            leads_ref.update(updates)
            
            await query.message.reply_text(f"✅ সফলভাবে **{len(keys_to_delete)}** টি সেন্ড মেইল ডিলিট করা হয়েছে।")
            
        except Exception as e:
            logger.error(f"Delete Sent Emails Error: {e}")
            await query.message.reply_text(f"❌ ডিলিট করতে সমস্যা হয়েছে: {str(e)}")

    elif query.data == 'btn_reset_count':
        try:
            counter_ref = db.reference(f'bot_configs/{BOT_ID_PREFIX}/sent_count')
            counter_ref.set(0)
            await query.message.reply_text("✅ Sent count has been reset to 0.")
        except Exception as e:
            logger.error(f"Reset count error: {e}")
            await query.message.reply_text("❌ Count reset করতে সমস্যা হয়েছে।")

async def handle_spam_check_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    
    if context.user_data.get('awaiting_test_email'):
        test_email = update.message.text.strip()
        
        try:
            leads_ref = db.reference('scraped_emails')
            all_leads = leads_ref.get()
            
            if not all_leads:
                await update.message.reply_text("⚠️ ডাটাবেজে কোনো লিড নেই, তাই ইমেইল পরিবর্তন করা সম্ভব নয়।")
                context.user_data['awaiting_test_email'] = False
                return

            target_key = next((k for k, v in all_leads.items() if v.get('status') is None and v.get('processing_by') is None), None)
            
            if target_key:
                app_name = all_leads[target_key].get('app_name', 'Unknown App')
                leads_ref.child(target_key).update({'email': test_email})
                
                await update.message.reply_text(
                    f"✅ **সফল!**\n\nপরবর্তী অ্যাপ: **{app_name}**\nনতুন ইমেইল সেট করা হয়েছে: `{test_email}`\n\nবট যখন মেইল পাঠাবে, তখন এটি এই ঠিকানায় যাবে। আপনি স্পাম বক্স চেক করতে পারবেন।"
                )
            else:
                await update.message.reply_text("⚠️ কোনো পেন্ডিং লিড পাওয়া যায়নি। সম্ভবত সব মেইল পাঠানো শেষ।")
                
        except Exception as e:
            logger.error(f"Spam check update error: {e}")
            await update.message.reply_text("❌ ইমেইল আপডেট করতে সমস্যা হয়েছে।")
        
        context.user_data['awaiting_test_email'] = False

async def set_email_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not is_owner(u.effective_user.id): return
    try:
        content = u.message.text.split('/set_email ', 1)[1]
        if '|' in content:
            sub, body = content.split('|', 1)
            db.reference('shared_config/email_template').set({'subject': sub.strip(), 'body': body.strip()})
            await u.message.reply_text("✅ টেম্পলেট সেভ হয়েছে।")
        else:
            await u.message.reply_text("⚠️ ফরম্যাট ভুল। '|' (pipe) চিহ্ন পাওয়া যায়নি।")
    except:
        await u.message.reply_text("❌ ভুল ফরম্যাট! উদাহরণ: `/set_email সাবজেক্ট | বডি`")

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
