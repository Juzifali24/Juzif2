#!/usr/bin/env python3
# juzif_bot.py
# Bot for FadeHost/Render: receives audio/video files, compresses them, posts to channel
# Mode: Polling + شريط تقدم + إرسال مزدوج بـ file_id (بدون رفع مزدوج)

import os
import uuid
import shutil
import tempfile
import subprocess
import re
from time import time
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton


# ------------------ Configuration ------------------

BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or os.getenv("TOKEN")
)

CHANNEL_ID = os.getenv("CHANNEL_ID") or "-1003203955147"
OWNER_ID = int(os.getenv("OWNER_ID", "1973076813"))

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN is not set in environment variables.")
if not CHANNEL_ID:
    raise SystemExit("CHANNEL_ID must be provided.")


# ------------------ Init ------------------

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

pending = {}


# ------------------ Helpers ------------------

def cleanup_pending(max_age_seconds=3600):
    now = time()
    for key, value in list(pending.items()):
        if now - value.get("created", 0) > max_age_seconds:
            try:
                base = os.path.dirname(value.get("orig", "")) or None
                if base and os.path.exists(base):
                    shutil.rmtree(base, ignore_errors=True)
            except Exception:
                pass
            pending.pop(key, None)


def file_size_mb(path):
    try:
        return os.path.getsize(path) / (1024.0 * 1024.0)
    except Exception:
        return 0.0


def ffmpeg_available():
    from shutil import which
    return which("ffmpeg") is not None


def download_telegram_file(file_id, dest_path):
    try:
        file_info = bot.get_file(file_id)
        data = bot.download_file(file_info.file_path)
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print("Download error:", e)
        return False


def _run_ffmpeg_with_progress(cmd, timeout, progress_msg=None, chat_id=None, label="جاري المعالجة"):
    if progress_msg and chat_id:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        duration = None
        last_progress = 0
        for line in process.stdout:
            if duration is None:
                m = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', line)
                if m:
                    h, mi, s = m.groups()
                    duration = int(h) * 3600 + int(mi) * 60 + float(s)
            m = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
            if m and duration:
                h, mi, s = m.groups()
                elapsed = int(h) * 3600 + int(mi) * 60 + float(s)
                progress = int((elapsed / duration) * 100)
                if progress > last_progress and progress <= 100:
                    last_progress = progress
                    try:
                        bot.edit_message_text(
                            f"⏳ {label}... {progress}%",
                            chat_id,
                            progress_msg.message_id,
                        )
                    except Exception:
                        pass
        process.wait()
        try:
            bot.edit_message_text(f"⏳ {label}... 100%", chat_id, progress_msg.message_id)
        except Exception:
            pass
        return process.returncode == 0

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=timeout)
        return True
    except Exception as e:
        print("ffmpeg error:", e)
        return False


def run_ffmpeg_convert_to_audio(input_path, output_path, bitrate_k="16k", samplerate=16000,
                                timeout=300, progress_msg=None, chat_id=None):
    if not ffmpeg_available():
        print("ffmpeg not available on system.")
        return False
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ac", "1",
        "-ar", str(samplerate),
        "-b:a", str(bitrate_k),
        "-vn",
        output_path
    ]
    ok = _run_ffmpeg_with_progress(
        cmd, timeout,
        progress_msg=progress_msg,
        chat_id=chat_id,
        label="جاري ضغط الصوت",
    )
    return ok and os.path.exists(output_path)


def run_ffmpeg_compress_video(input_path, output_path,
                              video_bitrate="200k", audio_bitrate="16k",
                              scale_width=320, samplerate=16000, timeout=600,
                              progress_msg=None, chat_id=None):
    if not ffmpeg_available():
        print("ffmpeg not available on system.")
        return False
    vf = f"scale='min({scale_width},iw)':-2"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", video_bitrate, "-maxrate", video_bitrate, "-bufsize", "2M",
        "-vf", vf,
        "-c:a", "aac", "-b:a", audio_bitrate, "-ac", "1", "-ar", str(samplerate),
        "-movflags", "+faststart",
        output_path
    ]
    ok = _run_ffmpeg_with_progress(
        cmd, timeout,
        progress_msg=progress_msg,
        chat_id=chat_id,
        label="جاري ضغط الفيديو",
    )
    return ok and os.path.exists(output_path)


# ------------------ Bot handlers ------------------

@bot.message_handler(commands=["start"])
def cmd_start(m):
    if m.from_user.id != OWNER_ID:
        bot.reply_to(m, "⛔ هذا البوت خاص بمالكه فقط.")
        return
    bot.reply_to(m, "أرسل ملف صوتي أو فيديو. الصوت يُضغط وينشر فوراً، الفيديو يُضغط ثم تُختار نشره كفيديو أو كصوت.")


@bot.message_handler(content_types=['audio', 'voice', 'video', 'document', 'video_note'])
def handle_media(m):
    if m.from_user.id != OWNER_ID:
        bot.reply_to(m, "⛔ هذا البوت خاص بمالكه فقط.")
        return

    cleanup_pending()

    file_id = None
    filename = None
    mime = None
    content_type = m.content_type

    if content_type == 'audio':
        file_id = m.audio.file_id
        filename = m.audio.file_name or f"audio_{uuid.uuid4().hex}.ogg"
        mime = m.audio.mime_type
    elif content_type == 'voice':
        file_id = m.voice.file_id
        filename = f"voice_{uuid.uuid4().hex}.ogg"
        mime = "audio/ogg"
    elif content_type == 'video':
        file_id = m.video.file_id
        filename = m.video.file_name or f"video_{uuid.uuid4().hex}.mp4"
        mime = m.video.mime_type
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

    progress_msg = bot.reply_to(m, "⏳ استلمت الملف، جاري ضغطه الآن... 0%")

    session_dir = tempfile.mkdtemp(prefix="job_")
    orig_path = os.path.join(session_dir, filename)

    if not download_telegram_file(file_id, orig_path):
        bot.edit_message_text("❌ فشل تنزيل الملف من تيليجرام.", m.chat.id, progress_msg.message_id)
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    title = os.path.splitext(filename)[0]
    is_audio = (content_type in ['audio', 'voice']) or (mime and mime.startswith("audio"))
    token = None

    try:
        if is_audio:
            out_audio = os.path.join(session_dir, f"{title}_compressed.mp3")
            ok = run_ffmpeg_convert_to_audio(
                orig_path, out_audio,
                bitrate_k="16k", samplerate=16000,
                progress_msg=progress_msg, chat_id=m.chat.id,
            )
            if not ok:
                bot.edit_message_text("❌ فشل ضغط الملف الصوتي (ffmpeg ربما غير متاح).", m.chat.id, progress_msg.message_id)
                shutil.rmtree(session_dir, ignore_errors=True)
                return
            size = file_size_mb(out_audio)

            # ✅ الإرسال الأول: إلى المستخدم في الخاص (يرفع الملف ويحصل على file_id)
            sent = bot.send_audio(
                m.chat.id,
                open(out_audio, "rb"),
                caption=f"🔊 {title} — مضغوط {size:.2f} MB",
                timeout=120,
            )
            # ✅ الإرسال الثاني: إلى القناة باستخدام file_id (بدون رفع)
            bot.send_audio(
                CHANNEL_ID,
                sent.audio.file_id,
                caption=f"🔊 {title} — مضغوط {size:.2f} MB",
                timeout=120,
            )

            bot.edit_message_text(f"✅ تم ضغط الصوت ({size:.2f} MB) وإرساله في الخاص والقناة.", m.chat.id, progress_msg.message_id)
            shutil.rmtree(session_dir, ignore_errors=True)
            return

        # فيديو: نسخة فيديو + نسخة صوت
        out_video = os.path.join(session_dir, f"{title}_compressed.mp4")
        out_audio_from_video = os.path.join(session_dir, f"{title}_audio.mp3")

        ok_video = run_ffmpeg_compress_video(
            orig_path, out_video,
            video_bitrate="200k", audio_bitrate="16k", scale_width=320,
            progress_msg=progress_msg, chat_id=m.chat.id,
        )
        ok_audio = run_ffmpeg_convert_to_audio(
            orig_path, out_audio_from_video,
            bitrate_k="16k", samplerate=16000,
            progress_msg=progress_msg, chat_id=m.chat.id,
        )

        token = uuid.uuid4().hex
        pending[token] = {
            "video": out_video if ok_video and os.path.exists(out_video) else None,
            "audio": out_audio_from_video if ok_audio and os.path.exists(out_audio_from_video) else None,
            "orig": orig_path,
            "title": title,
            "created": time()
        }

        parts = [f"✅ الملف جاهز: {title}"]
        if pending[token]["video"]:
            parts.append(f"🔹 فيديو مضغوط ~ {file_size_mb(pending[token]['video']):.2f} MB")
        else:
            parts.append("⚠️ لم يتم إنشاء فيديو مضغوط صالح.")
        if pending[token]["audio"]:
            parts.append(f"🔹 صوت مضغوط ~ {file_size_mb(pending[token]['audio']):.2f} MB")
        else:
            parts.append("⚠️ لم يتم إنشاء صوت من الفيديو.")

        kb = InlineKeyboardMarkup()
        if pending[token]["video"]:
            kb.add(InlineKeyboardButton("📤 نشر كفيديو مضغوط", callback_data=f"post:video:{token}"))
        if pending[token]["audio"]:
            kb.add(InlineKeyboardButton("🎧 نشر كصوت مضغوط", callback_data=f"post:audio:{token}"))
        kb.add(InlineKeyboardButton("🗑️ إلغاء وحذف", callback_data=f"cancel:{token}"))

        bot.edit_message_text("\n".join(parts), m.chat.id, progress_msg.message_id, reply_markup=kb)

    except Exception as e:
        print("Processing error:", e)
        bot.edit_message_text(f"❌ حدث خطأ أثناء المعالجة: {e}", m.chat.id, progress_msg.message_id)
        shutil.rmtree(session_dir, ignore_errors=True)
        if token:
            pending.pop(token, None)


# ------------------ Callback handler ------------------

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if not call.from_user or call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "⛔ هذا البوت خاص بمالكه فقط.", show_alert=True)
        return

    data = call.data
    try:
        action, typ, token = data.split(":")
    except Exception:
        bot.answer_callback_query(call.id, "بيانات غير مفهومة.")
        return

    entry = pending.get(token)
    if not entry:
        bot.answer_callback_query(call.id, "انتهت صلاحية هذا الطلب أو تم حذفه.")
        return

    try:
        if action == "post" and typ == "video":
            if not entry.get("video") or not os.path.exists(entry["video"]):
                bot.answer_callback_query(call.id, "لا يوجد ملف فيديو صالح للنشر.")
                return
            # ✅ الإرسال الأول: إلى المستخدم في الخاص (يرفع الملف)
            sent = bot.send_video(
                call.message.chat.id,
                open(entry["video"], "rb"),
                caption=f"🎬 {entry.get('title')}",
                timeout=300,
            )
            # ✅ الإرسال الثاني: إلى القناة باستخدام file_id (بدون رفع)
            bot.send_video(
                CHANNEL_ID,
                sent.video.file_id,
                caption=f"🎬 {entry.get('title')}",
                timeout=300,
            )
            bot.edit_message_text("✅ تم نشر الفيديو المضغوط في الخاص والقناة.", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "تم النشر كفيديو.")

        elif action == "post" and typ == "audio":
            if not entry.get("audio") or not os.path.exists(entry["audio"]):
                bot.answer_callback_query(call.id, "لا يوجد ملف صوت صالح للنشر.")
                return
            # ✅ الإرسال الأول: إلى المستخدم في الخاص (يرفع الملف)
            sent = bot.send_audio(
                call.message.chat.id,
                open(entry["audio"], "rb"),
                caption=f"🔊 {entry.get('title')}",
                timeout=300,
            )
            # ✅ الإرسال الثاني: إلى القناة باستخدام file_id (بدون رفع)
            bot.send_audio(
                CHANNEL_ID,
                sent.audio.file_id,
                caption=f"🔊 {entry.get('title')}",
                timeout=300,
            )
            bot.edit_message_text("✅ تم نشر الملف كصوت مضغوط في الخاص والقناة.", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "تم النشر كصوت.")

        elif action == "cancel":
            bot.edit_message_text("🗑️ تم الإلغاء وحذف الملفات.", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "تم الإلغاء.")

        base_dir = os.path.dirname(entry.get("orig")) if entry.get("orig") else None
        if base_dir and os.path.exists(base_dir):
            shutil.rmtree(base_dir, ignore_errors=True)
        pending.pop(token, None)
    except Exception as e:
        print("Callback handling error:", e)
        bot.answer_callback_query(call.id, f"حدث خطأ: {e}")


# ------------------ Run (Polling) ------------------

if __name__ == "__main__":
    print("🚀 Starting bot in Polling mode...")
    try:
        bot.remove_webhook()
        print("✅ Old webhook removed (if any).")
    except Exception as e:
        print("⚠️ remove_webhook warning:", e)

    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=25)
