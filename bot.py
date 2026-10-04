import html
import json
import os
import threading
from datetime import datetime, timedelta

import telebot
from telebot import types

# ---------- Токен и ID владельца ----------
# На сервере (Railway) они лежат в переменных BOT_TOKEN и OWNER_ID.
# На твоём компьютере берутся из файла config.py.

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    from config import TOKEN

OWNER_ID = os.environ.get("OWNER_ID")
if not OWNER_ID:
    try:
        from config import OWNER_ID
    except ImportError:
        OWNER_ID = None
OWNER_ID = int(OWNER_ID) if OWNER_ID else None

bot = telebot.TeleBot(TOKEN)


# ---------- Настройки (меняй под любого заказчика) ----------

SALON_NAME = "Барбершоп «Борода»"
ADDRESS = "ул. Пушкина, 10"
PHONE = "+7 900 000-00-00"

SERVICES = [
    {"name": "Мужская стрижка", "price": 800},
    {"name": "Стрижка + борода", "price": 1200},
    {"name": "Оформление бороды", "price": 500},
    {"name": "Детская стрижка", "price": 600},
]

FIRST_HOUR = 10          # первая запись в 10:00
LAST_HOUR = 18           # последняя запись в 18:00
DAYS_AHEAD = 7           # на сколько дней вперёд можно записаться
DAYS_OFF = [6]           # выходные: 0 = понедельник ... 6 = воскресенье

ALL_SLOTS = [f"{h:02d}:00" for h in range(FIRST_HOUR, LAST_HOUR + 1)]
DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


# ---------- Хранилище записей (файл bookings.json) ----------

BOOKINGS_FILE = "bookings.json"
lock = threading.Lock()  # защита от двух одновременных записей на одно время


def load_bookings():
    if os.path.exists(BOOKINGS_FILE):
        with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_bookings(bookings):
    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(bookings, f, ensure_ascii=False, indent=2)


def add_booking(user_id, name, service_index, date_str, time_str):
    """Создаёт запись. Если время уже занято — возвращает None."""
    with lock:
        bookings = load_bookings()
        if any(b["date"] == date_str and b["time"] == time_str for b in bookings):
            return None
        booking = {
            "id": max([b["id"] for b in bookings], default=0) + 1,
            "user_id": user_id,
            "name": name,
            "service": SERVICES[service_index]["name"],
            "price": SERVICES[service_index]["price"],
            "date": date_str,
            "time": time_str,
        }
        bookings.append(booking)
        save_bookings(bookings)
        return booking


def cancel_booking(booking_id, user_id):
    """Отменяет запись, но только если она принадлежит этому пользователю."""
    with lock:
        bookings = load_bookings()
        for b in bookings:
            if b["id"] == booking_id and b["user_id"] == user_id:
                bookings.remove(b)
                save_bookings(bookings)
                return b
        return None


def user_bookings(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    mine = [b for b in load_bookings() if b["user_id"] == user_id and b["date"] >= today]
    return sorted(mine, key=lambda b: (b["date"], b["time"]))


# ---------- Свободные дни и время ----------

def get_free_slots(date_str):
    taken = {b["time"] for b in load_bookings() if b["date"] == date_str}
    slots = [s for s in ALL_SLOTS if s not in taken]
    now = datetime.now()
    if date_str == now.strftime("%Y-%m-%d"):
        slots = [s for s in slots if s > now.strftime("%H:%M")]
    return slots


def get_available_days():
    today = datetime.now().date()
    days = []
    for i in range(DAYS_AHEAD):
        day = today + timedelta(days=i)
        if day.weekday() in DAYS_OFF:
            continue
        if get_free_slots(day.strftime("%Y-%m-%d")):
            days.append(day)
    return days


def pretty_date(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{DAYS_RU[d.weekday()]} {d.strftime('%d.%m')}"


# ---------- Кнопки меню ----------

def main_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📅 Записаться", callback_data="book"))
    markup.add(types.InlineKeyboardButton("📋 Мои записи", callback_data="mine"))
    markup.add(types.InlineKeyboardButton("ℹ️ О нас и цены", callback_data="about"))
    return markup


def back_to_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🏠 Меню", callback_data="menu"))
    return markup


def show(call, text, markup):
    """Заменяет текст сообщения с кнопками на новый."""
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup,
        )
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e):
            raise


def notify_owner(text):
    if OWNER_ID:
        try:
            bot.send_message(OWNER_ID, text, parse_mode="HTML")
        except Exception as e:
            print("Не удалось отправить уведомление владельцу:", e)


# ---------- Команды ----------

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        f"Здравствуйте! 👋 Это бот записи — <b>{SALON_NAME}</b>.\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@bot.message_handler(commands=["id"])
def send_id(message):
    # Нужна, чтобы владелец узнал свой Telegram ID и вписал его в config.py
    bot.send_message(message.chat.id, f"Ваш Telegram ID: {message.from_user.id}")


@bot.message_handler(commands=["admin"])
def admin(message):
    if message.from_user.id != OWNER_ID:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = sorted(
        [b for b in load_bookings() if b["date"] >= today],
        key=lambda b: (b["date"], b["time"]),
    )
    if not upcoming:
        bot.send_message(message.chat.id, "Ближайших записей пока нет.")
        return
    lines = ["📋 <b>Ближайшие записи:</b>\n"]
    for b in upcoming[:40]:
        lines.append(
            f"{pretty_date(b['date'])} {b['time']} — {html.escape(b['name'])}, "
            f"{b['service']} ({b['price']} ₽)"
        )
    bot.send_message(message.chat.id, "\n".join(lines), parse_mode="HTML")


# ---------- Нажатия на кнопки ----------

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    data = call.data
    user = call.from_user

    if data == "menu":
        show(call, "Выберите действие:", main_menu())

    elif data == "about":
        lines = [f"<b>{SALON_NAME}</b>", f"📍 {ADDRESS}", f"📞 {PHONE}",
                 f"🕙 Ежедневно {FIRST_HOUR}:00–{LAST_HOUR + 1}:00, воскресенье — выходной\n",
                 "<b>Цены:</b>"]
        for s in SERVICES:
            lines.append(f"• {s['name']} — {s['price']} ₽")
        show(call, "\n".join(lines), back_to_menu())

    # Шаг 1: выбор услуги
    elif data == "book":
        markup = types.InlineKeyboardMarkup()
        for i, s in enumerate(SERVICES):
            markup.add(types.InlineKeyboardButton(
                f"{s['name']} — {s['price']} ₽", callback_data=f"svc|{i}"))
        markup.add(types.InlineKeyboardButton("🏠 Меню", callback_data="menu"))
        show(call, "Шаг 1 из 3. Выберите услугу:", markup)

    # Шаг 2: выбор дня
    elif data.startswith("svc|"):
        service_index = int(data.split("|")[1])
        days = get_available_days()
        if not days:
            show(call, "К сожалению, свободных дат на ближайшую неделю нет 😔", back_to_menu())
        else:
            markup = types.InlineKeyboardMarkup(row_width=2)
            buttons = [
                types.InlineKeyboardButton(
                    pretty_date(d.strftime("%Y-%m-%d")),
                    callback_data=f"day|{service_index}|{d.strftime('%Y-%m-%d')}")
                for d in days
            ]
            markup.add(*buttons)
            markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="book"))
            show(call, "Шаг 2 из 3. Выберите день:", markup)

    # Шаг 3: выбор времени
    elif data.startswith("day|"):
        _, service_index, date_str = data.split("|")
        slots = get_free_slots(date_str)
        if not slots:
            show(call, "На этот день всё занято 😔 Выберите другой.", back_to_menu())
        else:
            markup = types.InlineKeyboardMarkup(row_width=3)
            buttons = [
                types.InlineKeyboardButton(
                    t, callback_data=f"slot|{service_index}|{date_str}|{t}")
                for t in slots
            ]
            markup.add(*buttons)
            markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"svc|{service_index}"))
            show(call, f"Шаг 3 из 3. Выберите время на {pretty_date(date_str)}:", markup)

    # Подтверждение
    elif data.startswith("slot|"):
        _, service_index, date_str, time_str = data.split("|")
        s = SERVICES[int(service_index)]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "✅ Подтвердить", callback_data=f"ok|{service_index}|{date_str}|{time_str}"))
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"day|{service_index}|{date_str}"))
        text = (f"Проверьте запись:\n\n✂️ {s['name']}\n"
                f"📅 {pretty_date(date_str)}, {time_str}\n💰 {s['price']} ₽")
        show(call, text, markup)

    # Создание записи
    elif data.startswith("ok|"):
        _, service_index, date_str, time_str = data.split("|")
        booking = add_booking(user.id, user.first_name, int(service_index), date_str, time_str)
        if booking is None:
            show(call, "Это время только что заняли 😔 Выберите другое.", back_to_menu())
            return
        show(call,
             f"✅ <b>Вы записаны!</b>\n\n✂️ {booking['service']}\n"
             f"📅 {pretty_date(date_str)}, {time_str}\n📍 {ADDRESS}\n\n"
             "Если планы изменятся — отмените запись в разделе «Мои записи».",
             back_to_menu())
        notify_owner(
            f"🔔 <b>Новая запись!</b>\n{html.escape(booking['name'])} — {booking['service']}\n"
            f"{pretty_date(date_str)}, {time_str}")

    # Мои записи
    elif data == "mine":
        mine = user_bookings(user.id)
        markup = types.InlineKeyboardMarkup()
        if not mine:
            text = "У вас пока нет активных записей."
        else:
            text = "📋 <b>Ваши записи</b> (нажмите, чтобы отменить):"
            for b in mine:
                markup.add(types.InlineKeyboardButton(
                    f"❌ {pretty_date(b['date'])} {b['time']} — {b['service']}",
                    callback_data=f"cancel|{b['id']}"))
        markup.add(types.InlineKeyboardButton("🏠 Меню", callback_data="menu"))
        show(call, text, markup)

    # Отмена записи
    elif data.startswith("cancel|"):
        booking = cancel_booking(int(data.split("|")[1]), user.id)
        if booking:
            bot.answer_callback_query(call.id, "Запись отменена")
            notify_owner(
                f"❌ <b>Отмена записи</b>\n{html.escape(booking['name'])} — {booking['service']}\n"
                f"{pretty_date(booking['date'])}, {booking['time']}")
        call.data = "mine"
        callback_handler(call)
        return

    bot.answer_callback_query(call.id)


# ---------- Запуск ----------

if __name__ == "__main__":
    print("Бот записи запущен. Нажми Ctrl+C, чтобы остановить.")
    bot.infinity_polling()
