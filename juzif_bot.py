#!/usr/bin/env python3
# Media Minifier Bot - BotHosting Ready (Polling Mode) with Real Progress
import os, uuid, shutil, tempfile, subprocess, time, re
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ---------------- Config ----------------
BOT_TOKEN = "8412113399:AAEKkxOk-JHL1Q-mVJYNZZ3hdc2Q9oxxbg4"
CHANNEL_ID = "-1003203955147"
ADMIN_ID = 1973076813
SUBSCRIBE_CHANNEL = "TILAWA_1"
BOT_LINK = "http://t.me/MediaMinifierBot"

bot = telebot.TeleBot(BOT_TOKEN)
pending = {}

# ---------------- Helpers ----------------
def cleanup_pending(max_age=3600):
    now = time.time()
    for k, v in list(pending.items()):
        if now - v.get("created", 0) > max_age:
            if os.path.exists(os.path.dirname(v.get("orig", ""))):
                shutil.rmtree(os.path.dirname(v["orig"]), ignore_errors=True)
            pending.pop(k, None)

def ffmpeg_available():
    from shutil import which
    return which("ffmpeg") is not None

def download_file(file_id, dest):
    try:
        finfo = bot.get_file(file_id)
        data = bot.download_file(finfo.file_path)
    except Exception as e:
        print("Download error:", e)
        return False
    with open(dest, "wb") as f:
        f.write(data)
    return True

def ffmpeg_progress(command, msg, chat_id):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    duration = None
    last_progress = 0
    for line in process.stdout:
        if duration is None:
            m = re.search(r'Duration: (\d+):(\d+):(\d+.\d+)', line)
            if m:
                h, m_, s = m.groups()
                duration = int(h)*3600 + int(m_)*60 + float(s)
        m = re.search(r'time=(\d+):(\d+):(\d+.\d+)', line)
        if m and duration:
            h, m_, s = m.groups()
            elapsed = int(h)*3600 + int(m_)*60 + float(s)
            progress = int((elapsed / duration) * 100)
            if progress > last_progress and progress <= 100:
                last_progress = progress
                try:
                    bot.edit_message_text(f"⏳ جاري ضغط الملف... {progress}%", chat_id, msg.message_id)
                except:
                    pass
    process.wait()
    return process.returncode == 0

def user_name(m):
    return f"@{m.from_user.username}" if m.from_user.username else m.from_user.first_name

def subscription_check(user_id):
    try:
        member = bot.get_chat_member(f"@{SUBSCRIBE_CHANNEL}", user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ---------------- /start ----------------
@bot.message_handler(commands=["start"])
def cmd_start(m):
    if not subscription_check(m.from_user.id):
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("اشترك أولاً", url=f"https://t.me/{SUBSCRIBE_CHANNEL}"))
        bot.reply_to(m, f"⚠️ يجب الاشتراك في قناة @{SUBSCRIBE_CHANNEL} لاستخدام البوت.", reply_markup=kb)
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("أَذّكَارِي.🫧", url="https://t.me/Er42Bot"))
    kb.add(InlineKeyboardButton("غرَاسَ الْجَنَّةِ. 🤍", url="https://t.me/JuzifAliBot"))
    bot.reply_to(
        m,
        f"السلام عليكم، {user_name(m)}\n\n"
        "ـ Media Minifier بُوت مُتَخَصّص فِي ضَغطِ الصَّوتِياتِ والفِيدِيوهُاتِ، قُم بإرسَالِ مَقّطَع الصُوتِ او الفِيديُو وانّتَظِر حَتَّى ينّتَهي مِن ضَغّطِه.\n\n"
        "ـ مُلاحَظةٌ:- لَا أُسَامَحْ ابَدًا مَنْ اسّتَخَدَم البُوت فِي ضَغطِ الأغَانِي والمُوسِيقَى "
        "او شَيٌء لَا يُرضِي رَبَّنَا عَزَّ وجَلْ.\n\n"
        "ـ بُوتَاتِي الأُخّرَى:\n"
        "١ـ أَذّكَارِي.🫧 ، نَشرُ صَوتِيات وصور دينية.\n"
        "٢ـ غرَاسَ الْجَنَّةِ. 🤍 ، نَشرُ تَسبِيح تلقائي كل ساعة.",
        reply_markup=kb
    )

# ---------------- Media Handler ----------------
@bot.message_handler(content_types=['audio','voice','video','document','video_note'])
def handle_media(m):
    # ✅ التعديل 1: تجاهل صامت لأي شخص ليس المالك
    if not m.from_user or m.from_user.id != ADMIN_ID:
        return

    cleanup_pending()
    file_id, filename, mime = None, None, None
    content_type = m.content_type

    if content_type == 'audio':
        file_id = m.audio.file_id
        filename = m.audio.file_name or f"audio_{uuid.uuid4().hex}.ogg"
    elif content_type == 'voice':
        file_id = m.voice.file_id
        filename = f"voice_{uuid.uuid4().hex}.ogg"
        mime = "audio/ogg"
    elif content_type == 'video':
        file_id = m.video.file_id
        filename = m.video.file_name or f"video_{uuid.uuid4().hex}.mp4"
    elif content_type == 'video_note':
        file_id = m.video_note.file_id
        filename = f"vidnote_{uuid.uuid4().hex}.mp4"
        mime = "video/mp4"
    elif content_type == 'document':
        file_id = m.document.file_id
        filename = m.document.file_name or f"file_{uuid.uuid4().hex}"
        mime = m.document.mime_type
    else:
        bot.reply_to(m, "نوع الملف غير مدعوم.")
        return

    session_dir = tempfile.mkdtemp(prefix="job_")
    orig_path = os.path.join(session_dir, filename)
    download_file(file_id, orig_path)

    pending[m.chat.id] = {
        "orig": orig_path,
        "title": os.path.splitext(filename)[0],
        "is_audio": (content_type in ['audio','voice']) or (mime and mime.startswith("audio")),
        "created": time.time(),
        "user": m.from_user
    }

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🟢 عالية (128k)", callback_data="quality_128"))
    kb.add(InlineKeyboardButton("🟡 متوسطة (96k)", callback_data="quality_96"))
    kb.add(InlineKeyboardButton("🔵 منخفضة (64k)", callback_data="quality_64"))
    kb.add(InlineKeyboardButton("🔴 منخفضة جدًا (32k)", callback_data="quality_32"))
    bot.reply_to(m, "🎚 قم باختيار الجودة المرغوبة:", reply_markup=kb)

# ---------------- Callback for Quality ----------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("quality_"))
def handle_quality(call: CallbackQuery):
    # ✅ التعديل 1 (تكملة): تجاهل صامت لأي شخص ليس المالك
    if not call.from_user or call.from_user.id != ADMIN_ID:
        return

    chat_id = call.message.chat.id
    if chat_id not in pending:
        bot.answer_callback_query(call.id, "⛔ انتهت الجلسة، أرسل الملف مرة أخرى.")
        return

    bitrate = call.data.split("_")[1]
    info = pending.pop(chat_id)
    orig_path = info["orig"]
    title = info["title"]
    is_audio = info["is_audio"]
    user = info["user"]

    # تحديث نفس الرسالة لإظهار التقدم وحذف الأزرار
    msg_progress = bot.edit_message_text("⏳ جاري ضغط الملف... 0%", chat_id, call.message.message_id, reply_markup=None)
    chat_id_progress = chat_id
    session_dir = os.path.dirname(orig_path)

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Media Minifier", url=BOT_LINK))

    try:
        if is_audio:
            out_audio = os.path.join(session_dir, f"{title}_compressed.mp3")
            cmd = ["ffmpeg", "-y", "-i", orig_path, "-ac", "1", "-ar", "16000", f"-b:a", f"{bitrate}k", "-vn", out_audio]
            if not ffmpeg_progress(cmd, msg_progress, chat_id_progress):
                bot.send_message(chat_id, "❌ فشل ضغط الملف الصوتي.")
                shutil.rmtree(session_dir, ignore_errors=True)
                return

            caption_user = "تم ضغطه ومعالجته من قِبل بوت Media Minifier - @MediaMinifierBot"
            caption_channel = f"منشور من: @{user.username if user.username else user.first_name}\n{caption_user}"

            # ✅ التعديل 2: إرسال للخاص أولًا، ثم للقناة بـ file_id (بدون رفع مزدوج)
            sent = bot.send_audio(chat_id, open(out_audio, "rb"), caption=caption_user, reply_markup=kb)
            bot.send_audio(CHANNEL_ID, sent.audio.file_id, caption=caption_channel, reply_markup=kb)

        else:
            out_video = os.path.join(session_dir, f"{title}_compressed.mp4")
            vf = f"scale='min(320,iw)':-2"
            cmd = ["ffmpeg", "-y", "-i", orig_path, "-c:v", "libx264", "-preset", "veryfast",
                   "-b:v", f"{bitrate}k", "-maxrate", f"{bitrate}k", "-bufsize", "2M", "-vf", vf,
                   "-c:a", "aac", "-b:a", f"{bitrate}k", "-ac", "1", "-ar", "16000",
                   "-movflags", "+faststart", out_video]
            if not ffmpeg_progress(cmd, msg_progress, chat_id_progress):
                bot.send_message(chat_id, "❌ فشل ضغط الفيديو.")
                shutil.rmtree(session_dir, ignore_errors=True)
                return

            caption_user = "تم ضغطه ومعالجته من قِبل بوت Media Minifier - @MediaMinifierBot"
            caption_channel = f"منشور من: @{user.username if user.username else user.first_name}\n{caption_user}"

            # ✅ التعديل 2: إرسال للخاص أولًا، ثم للقناة بـ file_id (بدون رفع مزدوج)
            sent = bot.send_video(chat_id, open(out_video, "rb"), caption=caption_user, reply_markup=kb)
            bot.send_video(CHANNEL_ID, sent.video.file_id, caption=caption_channel, reply_markup=kb)

        bot.edit_message_text("✅ تم ضغط الملف وإرساله بنجاح.", chat_id_progress, msg_progress.message_id)

    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ أثناء المعالجة: {e}")
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)

# ---------------- Run Bot ----------------
if __name__ == "__main__":
    print("✅ Bot is running via Long Polling...")
    try:
        bot.remove_webhook()
        print("✅ Webhook removed (if any).")
    except Exception as e:
        print("⚠️ remove_webhook warning:", e)
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=50)
        except Exception as e:
            print("Bot polling error:", e)
            time.sleep(5)
