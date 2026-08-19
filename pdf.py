import os
import time
import logging
import zipfile
import urllib.request
from io import BytesIO
from xml.etree import ElementTree

import telebot
from telebot import types, apihelper

from PIL import Image, ImageDraw, ImageFont

# Katta fayllarni yuborishda ulanish uzilib qolmasligi uchun timeout'larni oshiramiz
apihelper.CONNECT_TIMEOUT = 30
apihelper.READ_TIMEOUT = 180

# ============================================================
# SOZLAMALAR
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8870505838:AAFaT8OMQGT8u-vXX7uOsMGwfdlG4Wiizng")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE_DIR, "fonts")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

MAX_PART_BYTES = 15 * 1024 * 1024  # 15 MB - tezroq va ishonchliroq yuborish uchun

SAMPLE_TEXT = "Bizning telegram kanalga obuna bo'ling: @Ajoyib_botlarr"

# Shriftlar birinchi ishga tushishda shu manzillardan avtomatik yuklab olinadi
# (Google Fonts rasmiy repolari). Alohida fayl joylashtirish shart emas.
# "joined": True — harflari bir-biriga ulangan, chinakam qo'lyozma uslubidagi shriftlar.
FONTS = {
    "Caveat": {
        "file": "Caveat.ttf",
        "url": "https://raw.githubusercontent.com/googlefonts/caveat/main/fonts/ttf/Caveat-Regular.ttf",
        "joined": False,
    },
    "Marck Script": {
        "file": "MarckScript.ttf",
        "url": "https://raw.githubusercontent.com/google/fonts/main/ofl/marckscript/MarckScript-Regular.ttf",
        "joined": True,
    },
    "Kalam": {
        "file": "Kalam.ttf",
        "url": "https://raw.githubusercontent.com/google/fonts/main/ofl/kalam/Kalam-Regular.ttf",
        "joined": False,
    },
    "Pacifico": {
        "file": "Pacifico.ttf",
        "url": "https://raw.githubusercontent.com/google/fonts/main/ofl/pacifico/Pacifico-Regular.ttf",
        "joined": False,
    },
    "Bad Script": {
        "file": "BadScript.ttf",
        "url": "https://raw.githubusercontent.com/google/fonts/main/ofl/badscript/BadScript-Regular.ttf",
        "joined": True,
    },
    "Comforter": {
        "file": "Comforter.ttf",
        "url": "https://raw.githubusercontent.com/google/fonts/main/ofl/comforter/Comforter-Regular.ttf",
        "joined": True,
    },
}

# Qog'oz turlari: "daftar" - chiziqli, "list" - toza oq varaq
PAPER_TYPES = {
    "daftar": {"label": "📓 Daftar (chiziqli)", "file": "notebook_page.jpg", "lines": True},
    "list": {"label": "📄 List (toza varaq)", "file": "plain_page.jpg", "lines": False},
}

MAIN_MENU_BUTTONS = ["🖋 Shrift tanlash", "📄 Qog'oz turi", "🖼 Namuna", "ℹ️ Yordam"]
BACK_BUTTON = "⬅️ Orqaga"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")

# Foydalanuvchi holati: {user_id: {"font": "Caveat", "paper": "daftar"}}
user_data: dict[int, dict] = {}


# .docx faylni tashqi kutubxonasiz (faqat stdlib bilan) o'qish
def read_docx_text(path: str) -> str:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as z:
        xml_content = z.read("word/document.xml")
    root = ElementTree.fromstring(xml_content)
    paragraphs = []
    for p in root.iter(f"{{{ns['w']}}}p"):
        texts = [node.text or "" for node in p.iter(f"{{{ns['w']}}}t")]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


def ensure_fonts():
    """Har bir shrift fayli mavjudligini tekshiradi, bo'lmasa internetdan yuklaydi."""
    os.makedirs(FONTS_DIR, exist_ok=True)
    for name, info in FONTS.items():
        path = os.path.join(FONTS_DIR, info["file"])
        if os.path.exists(path):
            continue
        try:
            logger.info(f"Yuklanmoqda: {name} ({info['url']})")
            urllib.request.urlretrieve(info["url"], path)
        except Exception as e:
            logger.warning(f"'{name}' shriftini yuklab bo'lmadi: {e}")


def send_with_retry(func, *args, attempts: int = 3, **kwargs):
    """Tarmoq uzilib qolsa, bir necha marta qayta urinib ko'radi."""
    last_error = None
    for i in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            logger.warning(f"Yuborishda xatolik (urinish {i}/{attempts}): {e}")
            time.sleep(3 * i)
    raise last_error


# ============================================================
# QOG'OZ FONI (chiziqli daftar yoki toza list) - dasturiy chiziladi
# ============================================================
def ensure_background(paper_kind: str) -> str:
    info = PAPER_TYPES[paper_kind]
    path = os.path.join(TEMPLATES_DIR, info["file"])
    if os.path.exists(path):
        return path

    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    width, height = 1000, 1414  # A4 ~120dpi
    bg_color = (255, 253, 245) if info["lines"] else (255, 255, 255)
    img = Image.new("RGB", (width, height), bg_color)

    if info["lines"]:
        draw = ImageDraw.Draw(img)
        y = 130
        while y < height - 50:
            draw.line([(70, y), (width - 50, y)], fill=(190, 200, 230), width=1)
            y += 38
        draw.line([(105, 0), (105, height)], fill=(230, 150, 150), width=2)

    img.save(path, quality=90)
    return path


# ============================================================
# ASOSIY FUNKSIYA: MATNNI "QO'LYOZMA" SAHIFALARGA AYLANTIRISH
# ============================================================
def render_pages(
    text: str,
    font_path: str,
    paper_kind: str,
    font_size: int = 34,
    text_color: tuple = (25, 25, 112),
) -> list[Image.Image]:
    background_path = ensure_background(paper_kind)
    base_img = Image.open(background_path).convert("RGB")

    x_start = 115
    y_start = 130
    right_margin = 50
    max_width = base_img.width - right_margin
    line_height = 38
    bottom_margin = 50

    font = ImageFont.truetype(font_path, font_size)

    pages = []
    img = base_img.copy()
    draw = ImageDraw.Draw(img)
    current_x, current_y = x_start, y_start

    for paragraph in text.split("\n"):
        words = paragraph.split(" ") if paragraph else [""]
        for word in words:
            piece = word + " "
            bbox = font.getbbox(piece)
            piece_width = bbox[2] - bbox[0]

            if current_x + piece_width > max_width:
                current_x = x_start
                current_y += line_height

            if current_y + line_height > base_img.height - bottom_margin:
                pages.append(img)
                img = base_img.copy()
                draw = ImageDraw.Draw(img)
                current_x, current_y = x_start, y_start

            draw.text((current_x, current_y), piece, font=font, fill=text_color)
            current_x += piece_width

        current_x = x_start
        current_y += line_height

    pages.append(img)
    return pages


def make_sample_image(font_path: str, paper_kind: str) -> BytesIO:
    pages = render_pages(SAMPLE_TEXT, font_path, paper_kind, font_size=42)
    buf = BytesIO()
    pages[0].save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf


# ============================================================
# SAHIFALARNI HAJMGA QARAB QISMLARGA BO'LIB, PDF QILIB TAYYORLASH
# ============================================================
def export_parts(pages: list[Image.Image]) -> list[tuple[BytesIO, str, str]]:
    if len(pages) == 1:
        buf = BytesIO()
        pages[0].save(buf, format="JPEG", quality=90)
        buf.seek(0)
        return [(buf, "jpg", "")]

    sample_buf = BytesIO()
    pages[0].save(sample_buf, format="JPEG", quality=90)
    per_page_bytes = max(sample_buf.tell(), 1)

    pages_per_part = max(1, int((MAX_PART_BYTES * 0.85) // per_page_bytes))
    chunks = [pages[i:i + pages_per_part] for i in range(0, len(pages), pages_per_part)]

    results = []
    total_parts = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        buf = BytesIO()
        chunk[0].save(buf, format="PDF", save_all=True, append_images=chunk[1:])
        buf.seek(0)
        label = f" ({idx}/{total_parts}-qism)" if total_parts > 1 else ""
        results.append((buf, "pdf", label))
    return results


# ============================================================
# PASTKI MENYU (Reply Keyboard) - telefon va kompyuterda ham ko'rinadi
# ============================================================
def main_menu_keyboard() -> types.ReplyKeyboardMarkup:
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(MAIN_MENU_BUTTONS[0], MAIN_MENU_BUTTONS[1])
    markup.row(MAIN_MENU_BUTTONS[2], MAIN_MENU_BUTTONS[3])
    return markup


def font_menu_keyboard() -> types.ReplyKeyboardMarkup:
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    names = list(FONTS.keys())
    for i in range(0, len(names), 2):
        markup.row(*names[i:i + 2])
    markup.row(BACK_BUTTON)
    return markup


def paper_menu_keyboard() -> types.ReplyKeyboardMarkup:
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for info in PAPER_TYPES.values():
        markup.row(info["label"])
    markup.row(BACK_BUTTON)
    return markup


PAPER_LABEL_TO_KEY = {info["label"]: key for key, info in PAPER_TYPES.items()}


# ============================================================
# HANDLERLAR — Menyu tugmalari (aniq matn ustida ishlaydi)
# ============================================================
@bot.message_handler(commands=["start"])
def cmd_start(message: types.Message):
    user_data[message.from_user.id] = {"font": list(FONTS.keys())[0], "paper": "daftar"}
    bot.send_message(
        message.chat.id,
        "👋 Salom! Men matningizni qo'lda yozilgandek qilib rasmga aylantiraman.\n\n"
        "Pastdagi tugmalardan shrift va qog'oz turini tanlang, so'ng menga matn "
        "yoki .docx fayl yuboring.",
        reply_markup=main_menu_keyboard(),
    )


@bot.message_handler(func=lambda m: m.text == "🖋 Shrift tanlash")
def open_font_menu(message: types.Message):
    bot.send_message(message.chat.id, "Shriftni tanlang:", reply_markup=font_menu_keyboard())


@bot.message_handler(func=lambda m: m.text in FONTS)
def set_font(message: types.Message):
    user_data.setdefault(message.from_user.id, {})["font"] = message.text
    note = " (harflari bir-biriga ulangan)" if FONTS[message.text]["joined"] else ""
    bot.send_message(
        message.chat.id,
        f"✅ Shrift tanlandi: <b>{message.text}</b>{note}",
        reply_markup=main_menu_keyboard(),
    )


@bot.message_handler(func=lambda m: m.text == "📄 Qog'oz turi")
def open_paper_menu(message: types.Message):
    bot.send_message(message.chat.id, "Qog'oz turini tanlang:", reply_markup=paper_menu_keyboard())


@bot.message_handler(func=lambda m: m.text in PAPER_LABEL_TO_KEY)
def set_paper(message: types.Message):
    key = PAPER_LABEL_TO_KEY[message.text]
    user_data.setdefault(message.from_user.id, {})["paper"] = key
    bot.send_message(
        message.chat.id,
        f"✅ Qog'oz turi: <b>{message.text}</b>",
        reply_markup=main_menu_keyboard(),
    )


@bot.message_handler(func=lambda m: m.text == BACK_BUTTON)
def go_back(message: types.Message):
    bot.send_message(message.chat.id, "Asosiy menyu:", reply_markup=main_menu_keyboard())


@bot.message_handler(func=lambda m: m.text == "ℹ️ Yordam")
def help_menu(message: types.Message):
    bot.send_message(
        message.chat.id,
        "Menga matn yoki .docx fayl yuboring — men uni qo'lyozma ko'rinishidagi "
        "rasm/PDF ga aylantirib beraman.\n\n"
        "🖋 <b>Shrift tanlash</b> — yozuv uslubi\n"
        "📄 <b>Qog'oz turi</b> — Daftar (chiziqli) yoki List (toza varaq)\n"
        "🖼 <b>Namuna</b> — barcha shriftlarning ko'rinishini ko'rish",
        reply_markup=main_menu_keyboard(),
    )


@bot.message_handler(func=lambda m: m.text == "🖼 Namuna")
def send_samples(message: types.Message):
    ensure_fonts()
    bot.send_message(message.chat.id, "🖼 Namunalar tayyorlanmoqda, biroz kuting...")
    for font_name, info in FONTS.items():
        font_path = os.path.join(FONTS_DIR, info["file"])
        if not os.path.exists(font_path):
            continue
        try:
            daftar_buf = make_sample_image(font_path, "daftar")
            list_buf = make_sample_image(font_path, "list")
            join_note = " 🔗 ulangan harflar" if info["joined"] else ""
            media = [
                types.InputMediaPhoto(daftar_buf, caption=f"🖋 {font_name}{join_note} — Daftar"),
                types.InputMediaPhoto(list_buf, caption=f"🖋 {font_name}{join_note} — List"),
            ]
            send_with_retry(bot.send_media_group, message.chat.id, media)
        except Exception as e:
            logger.warning(f"Namuna yaratishda xato ({font_name}): {e}")
    bot.send_message(
        message.chat.id,
        "Yoqqan shriftni tanlang 👇",
        reply_markup=main_menu_keyboard(),
    )


# ============================================================
# HANDLERLAR — matn / .docx qabul qilish
# ============================================================
@bot.message_handler(content_types=["document"])
def handle_docx(message: types.Message):
    doc = message.document
    if not doc.file_name.lower().endswith(".docx"):
        bot.reply_to(message, "❗ Faqat .docx fayl qabul qilinadi.")
        return

    file_info = bot.get_file(doc.file_id)
    file_bytes = bot.download_file(file_info.file_path)

    tmp_path = os.path.join(BASE_DIR, f"tmp_{message.from_user.id}.docx")
    with open(tmp_path, "wb") as f:
        f.write(file_bytes)

    try:
        text = read_docx_text(tmp_path)
    finally:
        os.remove(tmp_path)

    if not text.strip():
        bot.reply_to(message, "❗ Fayl ichida matn topilmadi.")
        return

    process_and_send(message, text)


@bot.message_handler(content_types=["text"])
def handle_text(message: types.Message):
    if message.text.startswith("/"):
        return
    process_and_send(message, message.text)


def process_and_send(message: types.Message, text: str):
    settings = user_data.setdefault(message.from_user.id, {})
    font_name = settings.get("font", list(FONTS.keys())[0])
    paper_kind = settings.get("paper", "daftar")

    font_file = FONTS[font_name]["file"]
    font_path = os.path.join(FONTS_DIR, font_file)

    if not os.path.exists(font_path):
        ensure_fonts()

    if not os.path.exists(font_path):
        bot.reply_to(
            message,
            f"❗ '{font_file}' shriftini internetdan yuklab bo'lmadi.\n"
            f"Iltimos, birozdan so'ng qayta urinib ko'ring yoki boshqa shrift tanlang.",
        )
        return

    processing_msg = bot.send_message(message.chat.id, "✍️ Yozilyapti...")

    try:
        pages = render_pages(text=text, font_path=font_path, paper_kind=paper_kind)
        parts = export_parts(pages)
        total = len(parts)

        for i, (buf, ext, label) in enumerate(parts, start=1):
            buf.name = f"handwriting_{i}.{ext}" if total > 1 else f"handwriting.{ext}"
            caption = f"Shrift: {font_name}{label}"
            buf.seek(0)
            if ext == "jpg":
                send_with_retry(bot.send_photo, message.chat.id, buf, caption=caption)
            else:
                send_with_retry(bot.send_document, message.chat.id, buf, caption=caption)
    except Exception as e:
        logger.exception("Xatolik yuz berdi")
        bot.reply_to(message, f"❌ Xatolik: {e}")
    finally:
        bot.delete_message(message.chat.id, processing_msg.message_id)


# ============================================================
# ISHGA TUSHIRISH
# ============================================================
if __name__ == "__main__":
    os.makedirs(FONTS_DIR, exist_ok=True)
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    ensure_fonts()
    logger.info("Bot ishga tushdi...")
    bot.infinity_polling()