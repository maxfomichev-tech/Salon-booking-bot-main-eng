from __future__ import annotations

import os
import sys
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode, ChatAction
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from src.calendar_client import Booking, GoogleCalendarClient
from src.config import load_config
from src.clients import ClientsManager
from src.groq_chat import GroqConsultant
from src.services import load_services, format_services, Service
from src.sheets_client import SheetsClient

logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)
logger = logging.getLogger("aaron-salon-bot")


class BookingFlow(StatesGroup):
    category = State()
    service = State()
    dt = State()
    name = State()
    phone = State()
    confirm = State()


MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_datetime_en(text: str, tz: str) -> datetime | None:
    text = text.strip()
    now = datetime.now(ZoneInfo(tz))

    try:
        dt = datetime.strptime(text, "%d.%m")
        return dt.replace(year=now.year, tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    try:
        dt = datetime.strptime(text, "%d.%m.%Y")
        return dt.replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    try:
        dt = datetime.strptime(text, "%Y-%m-%d")
        return dt.replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    try:
        dt = datetime.strptime(text, "%d.%m %H:%M")
        return dt.replace(year=now.year, tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    try:
        dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
        return dt.replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    lower = text.lower()
    for name, month in MONTH_MAP.items():
        if name in lower:
            parts = lower.replace(name, str(month)).split()
            try:
                day = int(parts[0])
                year = now.year
                if len(parts) >= 3:
                    year = int(parts[2])
                hour, minute = 12, 0
                if len(parts) >= 2 and ":" in parts[1]:
                    h, m = parts[1].split(":")
                    hour, minute = int(h), int(m)
                dt = datetime(year, month, day, hour, minute)
                return dt.replace(tzinfo=ZoneInfo(tz))
            except (ValueError, IndexError):
                continue

    return None


def _is_weekend(dt: datetime) -> bool:
    return dt.weekday() == 5


def _is_outside_work_hours(dt: datetime, work_start: int, work_end: int) -> bool:
    return dt.hour < work_start or dt.hour >= work_end


def _format_work_hours(work_start: int, work_end: int) -> str:
    return f"{work_start:02d}:00–{work_end:02d}:00"


def _categories_keyboard(services: list[Service]) -> InlineKeyboardMarkup:
    cats = sorted({s.category for s in services})
    kb = [[InlineKeyboardButton(text=cat, callback_data=f"cat:{cat}")] for cat in cats]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _services_keyboard(services: list[Service], category: str, page: int = 0) -> InlineKeyboardMarkup:
    cat_svcs = [(i, s) for i, s in enumerate(services) if s.category == category]
    PER_PAGE = 8
    total = (len(cat_svcs) + PER_PAGE - 1) // PER_PAGE
    start = page * PER_PAGE
    items = cat_svcs[start:start + PER_PAGE]

    kb = [[InlineKeyboardButton(text=s.label, callback_data=f"svc:{orig_i}")] for orig_i, s in items]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="← Back", callback_data=f"page:{page - 1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="More →", callback_data=f"page:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="← To categories", callback_data="back:cat")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _time_slots_keyboard(work_start: int, work_end: int) -> InlineKeyboardMarkup:
    slots = list(range(work_start, work_end, 2))
    kb = []
    row = []
    for h in slots:
        row.append(InlineKeyboardButton(text=f"{h:02d}:00", callback_data=f"time:{h:02d}:00"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="⌨️ Other time", callback_data="time:other")])
    kb.append([InlineKeyboardButton(text="← Back", callback_data="back:dt")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yes, book", callback_data="confirm:yes")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="confirm:no")],
    ])


@dataclass(frozen=True)
class AppState:
    cfg: object
    services: list[Service]
    consultant: GroqConsultant
    calendar: GoogleCalendarClient
    clients: ClientsManager


def _match_service(services: list[Service], user_text: str) -> Service | None:
    t = (user_text or "").strip().lower()
    if not t:
        return None
    for s in services:
        if t in s.service.lower() or s.service.lower() in t:
            return s
    return None


async def send_typing_and_reply(message: Message, text: str, parse_mode=None):
    await message.bot.send_chat_action(
        chat_id=message.chat.id, action=ChatAction.TYPING
    )
    await asyncio.sleep(0.5)
    await message.answer(text, parse_mode=parse_mode)


async def cmd_start(message: Message, state: FSMContext, app: AppState) -> None:
    await state.clear()
    await message.answer(
        f"✨ Hello! I'm Aaron, your personal consultant at <b>{app.cfg.salon_name}</b> beauty salon\n\n"
        "I can:\n"
        "- help you with services and prices 📋\n"
        "- book an appointment for you 📅\n\n"
        "Commands:\n"
        "/price — price list\n"
        "/book — book appointment\n"
        "/help — help\n",
        parse_mode=ParseMode.HTML,
    )
    await message.answer(format_services(app.services, limit=12))


async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("📝 Send me a message or use /book to schedule an appointment.")


async def cmd_price(message: Message, app: AppState) -> None:
    await message.answer(format_services(app.services, limit=30))


async def cmd_book(message: Message, state: FSMContext, app: AppState) -> None:
    await state.set_state(BookingFlow.category)
    await state.update_data(draft={})
    await message.answer(
        "📝 Great! Let's book your appointment. Choose a category or type a service name:",
        reply_markup=_categories_keyboard(app.services),
    )


async def book_service(message: Message, state: FSMContext, app: AppState) -> None:
    category = None
    for cat in sorted({s.category for s in app.services}):
        if cat.lower() in (message.text or "").lower():
            category = cat
            break
    if category and not _match_service(app.services, message.text or ""):
        await state.update_data(category=category)
        await state.set_state(BookingFlow.service)
        await message.answer(
            f"📌 {category}. Choose a service:",
            reply_markup=_services_keyboard(app.services, category),
        )
        return

    svc = _match_service(app.services, message.text or "")
    if not svc:
        await message.answer(
            "Service not found. Choose a category:\n"
            "or press /help to continue the consultation",
            reply_markup=_categories_keyboard(app.services),
        )
        return

    await state.update_data(
        service=svc.service,
        duration_minutes=svc.duration_minutes,
        price_usd=svc.price_usd,
    )
    await state.set_state(BookingFlow.dt)
    await message.answer(
        "✅ Great! Enter the date. For example: <code>20.06</code>\n"
        f"Timezone: {app.cfg.salon_timezone}",
        parse_mode=ParseMode.HTML,
    )


async def book_dt(message: Message, state: FSMContext, app: AppState) -> None:
    dt = _parse_datetime_en(message.text or "", app.cfg.salon_timezone)
    if not dt:
        await message.answer(
            "Couldn't understand the date. Use format <code>20.06</code> (day.month) or <code>20.06 15:30</code>\n"
            "or press /help to continue the consultation",
            parse_mode=ParseMode.HTML,
        )
        return

    time_specified = any(c.isdigit() for c in message.text.split()[-1]) if len(message.text.split()) >= 2 else False
    has_time = len(message.text.split()) >= 2 and (":" in message.text.split()[-1] or time_specified)

    if not has_time:
        dt_midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        await state.update_data(selected_date_iso=dt_midnight.isoformat())
        await message.answer(
            f"📅 {dt.strftime('%d.%m.%Y')}. Choose a time:",
            reply_markup=_time_slots_keyboard(app.cfg.work_start_hour, app.cfg.work_end_hour),
        )
        return

    if _is_weekend(dt):
        await message.answer(
            "⚠️ You selected a weekend.\n"
            "The salon is open Sunday through Friday.\n"
            "Please choose another date or press /help to exit."
        )
        return

    if _is_outside_work_hours(dt, app.cfg.work_start_hour, app.cfg.work_end_hour):
        await message.answer(
            f"⚠️ Working hours: {_format_work_hours(app.cfg.work_start_hour, app.cfg.work_end_hour)}.\n"
            f"You selected {dt.strftime('%H:%M')}. Please choose a time within working hours\n"
            "or press /help to exit."
        )
        return

    data = await state.get_data()
    duration = int(data.get("duration_minutes", 60))
    end = dt + timedelta(minutes=duration)

    try:
        if not app.calendar.is_time_available(dt, end):
            await message.answer(
                f"⚠️ Sorry, {dt.strftime('%H:%M')} is already booked.\n"
                "Please choose another time\n"
                "or press /help to exit."
            )
            return
    except Exception as e:
        logger.error("Error checking availability: %s", e)

    await state.update_data(start_iso=dt.isoformat())
    await state.set_state(BookingFlow.name)
    await message.answer("😊 What is your name?")


async def book_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(
            "Name is too short. Please try again\n"
            "or press /help to exit."
        )
        return
    await state.update_data(client_name=name)
    await state.set_state(BookingFlow.phone)
    await message.answer("📱 Your phone number (e.g. +972 50 123 4567)?")


async def book_phone(message: Message, state: FSMContext) -> None:
    phone = (message.text or "").strip()
    if len(phone) < 6:
        await message.answer(
            "That looks like a short number. Please enter your phone again\n"
            "or press /help to exit."
        )
        return
    await state.update_data(phone=phone)
    await state.set_state(BookingFlow.confirm)

    data = await state.get_data()
    start = datetime.fromisoformat(data["start_iso"])
    formatted_date = start.strftime("%d.%m.%Y %H:%M")

    await message.answer(
        "Confirm your booking:\n"
        f"- Service: {data['service']} ({data['duration_minutes']} min, ${data['price_usd']})\n"
        f"- When: {formatted_date}\n"
        f"- Name: {data['client_name']}\n"
        f"- Phone: {data['phone']}",
        reply_markup=_confirm_keyboard(),
    )


async def confirm_booking(msg: Message, state: FSMContext, app: AppState, user_id: str | None = None) -> None:
    data = await state.get_data()
    start = datetime.fromisoformat(data["start_iso"])
    booking = Booking(
        service_name=data["service"],
        client_name=data["client_name"],
        phone=data["phone"],
        start=start,
        duration_minutes=int(data["duration_minutes"]),
        timezone=app.cfg.salon_timezone,
        salon_name=app.cfg.salon_name,
    )

    try:
        link = app.calendar.create_booking_event(booking)
        logger.info("Calendar event created: %s", link)
    except Exception as e:
        logger.error("Error creating calendar event: %s", e)
        link = ""

    await state.clear()
    await msg.answer("✅ Done! You're booked! See you soon 💖")

    try:
        app.clients.add_or_update(
            client_id=user_id or str(msg.from_user.id),
            name=data["client_name"],
            phone=str(data["phone"]),
            service_name=data["service"],
            service_dt_iso=start.isoformat(),
        )
        logger.info("Client saved: %s", msg.from_user.id)
    except Exception as e:
        logger.error("Error saving client: %s", e)

    try:
        ics_content = app.calendar.generate_ics(booking)
        await msg.answer_document(
            document=types.BufferedInputFile(
                file=ics_content.encode("utf-8"),
                filename=f"booking_{booking.start.strftime('%d%m%Y')}.ics",
            ),
            caption="Add this booking to your calendar 📅",
        )
    except Exception as e:
        logger.error("Error sending ics: %s", e)


async def book_confirm_text(message: Message, state: FSMContext, app: AppState) -> None:
    answer = (message.text or "").strip().lower()
    if answer not in {"yes", "no", "да", "нет"}:
        await message.answer("Please reply \"yes\" or \"no\".", reply_markup=_confirm_keyboard())
        return
    if answer in {"no", "нет"}:
        await state.clear()
        await message.answer("❌ Cancelled. Whenever you're ready — /book")
        return
    await confirm_booking(message, state, app)


async def handle_category_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    cat = cq.data.split(":", 1)[1]
    await state.update_data(category=cat)
    await state.set_state(BookingFlow.service)
    await cq.message.edit_text(
        f"📌 {cat}. Choose a service:",
        reply_markup=_services_keyboard(app.services, cat),
    )
    await cq.answer()


async def handle_service_page_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    page = int(cq.data.split(":", 1)[1])
    data = await state.get_data()
    cat = data.get("category", "")
    await cq.message.edit_reply_markup(reply_markup=_services_keyboard(app.services, cat, page))
    await cq.answer()


async def handle_service_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    idx = int(cq.data.split(":", 1)[1])
    svc = app.services[idx]
    await state.update_data(
        service=svc.service,
        duration_minutes=svc.duration_minutes,
        price_usd=svc.price_usd,
    )
    await state.set_state(BookingFlow.dt)
    await cq.message.edit_text(
        "✅ Great! Enter the date. For example: <code>20.06</code>\n"
        f"Timezone: {app.cfg.salon_timezone}",
        parse_mode=ParseMode.HTML,
    )
    await cq.answer()


async def handle_time_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    data = await state.get_data()
    selected_date_iso = data.get("selected_date_iso")
    if not selected_date_iso:
        await cq.message.answer("Enter the date first.")
        await cq.answer()
        return

    time_part = cq.data.split(":", 1)[1]
    if time_part == "other":
        await cq.message.edit_text(
            "Enter the full date and time. For example: <code>20.06 15:30</code>",
            parse_mode=ParseMode.HTML,
        )
        await cq.answer()
        return

    hour, minute = map(int, time_part.split(":"))
    dt = datetime.fromisoformat(selected_date_iso).replace(hour=hour, minute=minute)

    if _is_weekend(dt):
        await cq.message.answer(
            "⚠️ You selected a weekend.\n"
            "The salon is open Sunday through Friday. Choose another date\n"
            "or press /help to exit.",
            reply_markup=_time_slots_keyboard(app.cfg.work_start_hour, app.cfg.work_end_hour),
        )
        await cq.answer()
        return

    if _is_outside_work_hours(dt, app.cfg.work_start_hour, app.cfg.work_end_hour):
        await cq.message.answer(
            f"⚠️ Working hours: {_format_work_hours(app.cfg.work_start_hour, app.cfg.work_end_hour)}.\n"
            f"You selected {dt.strftime('%H:%M')}. Please choose a time within working hours\n"
            "or press /help to exit.",
            reply_markup=_time_slots_keyboard(app.cfg.work_start_hour, app.cfg.work_end_hour),
        )
        await cq.answer()
        return

    duration = int(data.get("duration_minutes", 60))
    end = dt + timedelta(minutes=duration)

    try:
        if not app.calendar.is_time_available(dt, end):
            await cq.message.answer(
                f"⚠️ Sorry, {dt.strftime('%H:%M')} is already booked. Choose another\n"
                "or press /help to exit:",
                reply_markup=_time_slots_keyboard(app.cfg.work_start_hour, app.cfg.work_end_hour),
            )
            await cq.answer()
            return
    except Exception as e:
        logger.error("Error checking availability: %s", e)

    await state.update_data(start_iso=dt.isoformat())
    await state.set_state(BookingFlow.name)
    await cq.message.edit_text("😊 What is your name?")
    await cq.answer()


async def handle_back_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    target = cq.data.split(":", 1)[1]
    if target == "cat":
        await state.set_state(BookingFlow.category)
        await cq.message.edit_text(
            "Choose a category or type a service name:",
            reply_markup=_categories_keyboard(app.services),
        )
    elif target == "dt":
        await state.set_state(BookingFlow.dt)
        await cq.message.edit_text(
            "Enter the date. For example: <code>20.06</code>",
            parse_mode=ParseMode.HTML,
        )
    await cq.answer()


async def handle_confirm_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    answer = cq.data.split(":", 1)[1]
    if answer == "no":
        await state.clear()
        await cq.message.edit_text("❌ Cancelled. Whenever you're ready — /book")
        await cq.answer()
        return

    await confirm_booking(cq.message, state, app, user_id=str(cq.from_user.id))
    await cq.answer()


async def consult(message: Message, state: FSMContext, app: AppState) -> None:
    if await state.get_state() is not None:
        return
    try:
        reply = app.consultant.reply(message.text or "")
    except Exception as e:
        logger.exception("Groq error")
        await send_typing_and_reply(
            message, f"Consultation error. Please try again.\n\n{e}"
        )
        return
    await send_typing_and_reply(message, reply)


async def maybe_start_booking(
    message: Message, state: FSMContext, app: AppState
) -> None:
    text = (message.text or "").strip().lower()

    booking_triggers = [
        "book",
        "book appointment",
        "i want to book",
        "schedule",
        "appointment",
        "reserve",
        "запиши",
        "записаться",
        "хочу записаться",
        "хочу на",
        "запись",
    ]

    for trigger in booking_triggers:
        if trigger in text:
            await cmd_book(message, state, app)
            return

    await consult(message, state, app)


def main() -> None:
    cfg = load_config()
    services = load_services(cfg.services_csv)
    credentials_json = cfg.google_service_account_json_content
    if not credentials_json and cfg.google_service_account_json_path:
        credentials_json = cfg.google_service_account_json_path.read_text(encoding="utf-8")

    if cfg.google_sheets_id and credentials_json:
        clients_manager = SheetsClient(
            spreadsheet_id=cfg.google_sheets_id,
            credentials_json=credentials_json,
        )
    else:
        clients_manager = ClientsManager()

    consultant = GroqConsultant(
        api_key=cfg.groq_api_key,
        model=cfg.groq_model,
        salon_name=cfg.salon_name,
        services_text=format_services(services, limit=60),
        address=cfg.address,
        timezone=cfg.salon_timezone,
        work_start_hour=cfg.work_start_hour,
        work_end_hour=cfg.work_end_hour,
    )
    calendar = GoogleCalendarClient(
        calendar_id=cfg.google_calendar_id,
        service_account_json_path=(
            str(cfg.google_service_account_json_path)
            if cfg.google_service_account_json_path
            else None
        ),
        service_account_json_content=cfg.google_service_account_json_content,
    )
    
    app_state = AppState(
        cfg=cfg,
        services=services,
        consultant=consultant,
        calendar=calendar,
        clients=clients_manager,
    )

    async def _run() -> None:
        print("BOT_STARTING", flush=True)
        bot = Bot(token=cfg.telegram_bot_token)
        dp = Dispatcher(storage=MemoryStorage())

        @dp.callback_query.middleware()
        async def log_callback_query(handler, event, data):
            print(f"CALLBACK_MW: data={event.data}", flush=True)
            return await handler(event, data)

        async def _cmd_start(message: Message, state: FSMContext) -> None:
            await cmd_start(message, state, app_state)

        async def _cmd_price(message: Message) -> None:
            await cmd_price(message, app_state)

        async def _cmd_book(message: Message, state: FSMContext) -> None:
            await cmd_book(message, state, app_state)

        async def _book_service(message: Message, state: FSMContext) -> None:
            await book_service(message, state, app_state)

        async def _book_dt(message: Message, state: FSMContext) -> None:
            await book_dt(message, state, app_state)

        async def _book_confirm_text(message: Message, state: FSMContext) -> None:
            await book_confirm_text(message, state, app_state)

        async def _maybe_start_booking(message: Message, state: FSMContext) -> None:
            await maybe_start_booking(message, state, app_state)

        async def _handle_callback(cq: CallbackQuery, state: FSMContext) -> None:
            if not cq.data:
                await cq.answer()
                return
            try:
                data = cq.data
                st = await state.get_state()
                logger.info("Callback: data=%s state=%s", data, st)

                if data.startswith("cat:"):
                    if st == BookingFlow.category.state:
                        await handle_category_cb(cq, state, app_state)
                        return
                elif data.startswith("svc:"):
                    if st == BookingFlow.service.state:
                        await handle_service_cb(cq, state, app_state)
                        return
                elif data.startswith("page:"):
                    if st == BookingFlow.service.state:
                        await handle_service_page_cb(cq, state, app_state)
                        return
                elif data.startswith("back:"):
                    if st in (BookingFlow.service.state, BookingFlow.dt.state):
                        await handle_back_cb(cq, state, app_state)
                        return
                elif data.startswith("time:"):
                    if st == BookingFlow.dt.state:
                        await handle_time_cb(cq, state, app_state)
                        return
                elif data.startswith("confirm:"):
                    if st == BookingFlow.confirm.state:
                        await handle_confirm_cb(cq, state, app_state)
                        return

                logger.warning("Unhandled callback: %s (state: %s)", data, st)
                await cq.answer("⚠️ Button expired. Start with /book again.")
            except Exception as e:
                logger.exception("Callback error: data=%s", cq.data)
                await cq.answer("⚠️ Error. Try /book again.")

        dp.message.register(_cmd_start, Command("start"))
        dp.message.register(cmd_help, Command("help"))
        dp.message.register(_cmd_price, Command("price"))
        dp.message.register(_cmd_book, Command("book"))

        dp.message.register(_book_service, BookingFlow.category, F.text)
        dp.message.register(_book_service, BookingFlow.service, F.text)
        dp.message.register(_book_dt, BookingFlow.dt, F.text)
        dp.message.register(book_name, BookingFlow.name, F.text)
        dp.message.register(book_phone, BookingFlow.phone, F.text)
        dp.message.register(_book_confirm_text, BookingFlow.confirm, F.text)

        dp.callback_query.register(_handle_callback)

        dp.message.register(_maybe_start_booking, F.text)

        webhook_url = (os.getenv("WEBHOOK_URL") or "").strip()
        render_external_url = (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
        port = int(os.getenv("PORT", "10000"))

        if not webhook_url and render_external_url:
            webhook_url = f"{render_external_url.rstrip('/')}/webhook"

        if webhook_url:
            await bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message", "callback_query"],
            )
            wh_info = await bot.get_webhook_info()
            logger.info("Webhook set: url=%s allowed_updates=%s", wh_info.url, wh_info.allowed_updates)
            logger.info("Bot starting in webhook mode on port %s", port)

            app = web.Application()
            app.router.add_get("/", lambda _: web.Response(text="ok"))
            app.router.add_get("/health", lambda _: web.Response(text="ok"))
            SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
            setup_application(app, dp, bot=bot)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host="0.0.0.0", port=port)
            await site.start()

            await asyncio.Event().wait()
        else:
            logger.info("Bot starting in polling mode...")
            if (os.getenv("RENDER_EXTERNAL_URL") or "").strip():
                raise RuntimeError(
                    "Refusing to start polling on Render. Set WEBHOOK_URL or ensure "
                    "RENDER_EXTERNAL_URL is available so the bot can run in webhook mode."
                )
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
