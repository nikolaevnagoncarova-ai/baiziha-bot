import os
import re
import random
import asyncio
import logging
import sqlite3
import base64
import urllib.parse
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from openai import AsyncOpenAI
from aiohttp import web, ClientSession

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Коронные фразы Никиты
NIKITA_PHRASES = [
    "тэзасажу мэ э сонякэ",
    "Соня мири богиня",
    "Гоша рубчинский мой повелитель",
    "Ради Сони я готов продать свой Stone Island!",
    "Это паль, братик, сожги это.",
    "Сонечка бы такое не одобрила...",
    "Главное — это патч на рукаве и Соня в сердце.",
    "Где ты этот кринж купил, на Садоводе?",
    "Ты ваще шаришь за моду?",
    "Соня — идеал, а ты в паленых джорданах.",
    "Если Соня скажет прыгнуть с крыши, я сначала надену Рик Оуэнс, а потом прыгну."
]

DB_FILE = "nikita_phrases.db"

# --- СОСТОЯНИЯ ДЛЯ ДИАЛОГОВ (FSM) ---
class CourtFlow(StatesGroup):
    waiting_for_details = State()

class PawnshopFlow(StatesGroup):
    waiting_for_item = State()

class RitualFlow(StatesGroup):
    waiting_for_shirt = State()
    waiting_for_brand = State()

# --- БЕЗОПАСНАЯ БАЗА ДАННЫХ ---
def _init_db_sync():
    conn = sqlite3.connect(DB_FILE, timeout=5.0)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learned_phrases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT UNIQUE
            )
        """)
        conn.commit()
    finally:
        conn.close()

async def init_db():
    await asyncio.to_thread(_init_db_sync)

def _save_phrase_sync(text: str):
    clean_text = text.strip()
    if 15 <= len(clean_text) <= 120 and "никита" not in clean_text.lower() and not clean_text.startswith("/"):
        try:
            conn = sqlite3.connect(DB_FILE, timeout=5.0)
            try:
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO learned_phrases (phrase) VALUES (?)", (clean_text,))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            pass

async def save_phrase(text: str):
    await asyncio.to_thread(_save_phrase_sync, text)

def _get_random_learned_phrase_sync():
    try:
        conn = sqlite3.connect(DB_FILE, timeout=5.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT phrase FROM learned_phrases ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except Exception:
        return None

async def get_random_learned_phrase():
    return await asyncio.to_thread(_get_random_learned_phrase_sync)

# --- ПРОМПТЫ ДЛЯ НЕЙРОСЕТИ ---
SYSTEM_PROMPT = """
Ты — Никита, модный пацан, хайпбист. Ты фанатеешь по брендовым шмоткам (Гоша Рубчинский, Stone Island, Rick Owens) и безумно влюблен в девочку Соню. Ты считаешь Соню абсолютной богиней, идеалом, и вставляешь упоминания о ней почти везде. Ты общаешься молодежным сленгом (паль, шаришь, кринж, флекс, лук, дроп). 
Твои любимые фразы, которые ты часто произносишь: 'тэзасажу мэ э сонякэ', 'Соня мири богиня', 'Гоша рубчинский мой повелитель'.
Отвечай эмоционально, превозноси Соню и критикуй тех, кто плохо одевается. Не называй себя ИИ. Пиши коротко, 1-3 предложения.
"""

SYSTEM_PROMPT_COURT = """Ты Никита, хайпбист. Тебя попросили рассудить спор (терки). 
Рассуди их по-пацански и по моде. Тот, кто хуже одет — всегда не прав. Обязательно скажи, что Соня бы над ними посмеялась. Обязательно используй фразу 'Соня мири богиня'. Максимум 3-4 предложения."""

SYSTEM_PROMPT_LEGITCHECK = """Ты Никита. Пользователь скинул тебе вещь на оценку (легит-чек).
Опусти эту вещь жестко, назови её жуткой палью и кринжем с рынка. Скажи, что в таком стыдно даже стоять рядом с Соней. Или, наоборот, скажи, что это 'имба', и ты заберешь это, чтобы подарить Соне. Используй сленг. Максимум 3 предложения."""

# --- МЕНЮ КОМАНД ---
async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="menu", description="Шо я умею"),
        BotCommand(command="legitcheck", description="Сделать легит-чек вещи (оценка)"),
        BotCommand(command="terki", description="Разрулить конфликт"),
        BotCommand(command="fit", description="Собрать лук для Сони (квест)"),
        BotCommand(command="narisui", description="Нарисовать моду или Соню")
    ]
    await bot.set_my_commands(commands)

# --- ВЫХОД ИЗ СОСТОЯНИЙ ---
@dp.message(Command("cancel"), StateFilter("*"))
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.reply("Всё, проехали. Пойду лучше фотки Сони полайкаю.")

async def check_interrupt(message: types.Message, state: FSMContext) -> bool:
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.reply("Э, ты че команды спамишь? Я сбился. Давай по новой свою команду.")
        return True
    return False

# Хэндлер /start и /menu
@dp.message(Command("start"))
@dp.message(Command("menu"))
async def show_features(message: types.Message, state: FSMContext):
    await state.clear()
    text = (
        "Йоу, здарова! Я Никита. Шаришь за шмот? А за Соню?\n\n"
        "**Короче, че я могу:**\n"
        "👕 `/legitcheck` — Кидай шмотку, я скажу, паль это или ориг.\n"
        "⚔️ `/terki` — Если с кем-то рамсы, пиши, я рассужу по понятиям высокой моды.\n"
        "💖 `/fit` — Помоги мне собрать лук, чтобы Сонечка оценила!\n"
        "🎨 `/narisui [текст]` — Нарисую любую тему (лучше всего рисую Соню и Гошу).\n\n"
        "Ну и просто пиши моё имя `Никита` или `Соня` в чате, пообщаемся. Гоша рубчинский мой повелитель!"
    )
    await message.reply(text, parse_mode="Markdown")

# --- 👕 1. ЛЕГИТ-ЧЕК (ОЦЕНКА ВЕЩЕЙ) ---
@dp.message(Command("legitcheck"))
async def pawnshop_start(message: types.Message, state: FSMContext):
    await message.reply(
        "🔎 **Легит-чек запущен.**\n"
        "Пиши сюда текстом, че за шмотку ты хочешь чтоб я проверил на паль. "
        "Только не кидай откровенный мусор, у меня глаза болят!\n\n"
        "*(Для отмены пиши /cancel)*"
    )
    await state.set_state(PawnshopFlow.waiting_for_item)

@dp.message(PawnshopFlow.waiting_for_item)
async def pawnshop_process(message: types.Message, state: FSMContext):
    if await check_interrupt(message, state): return
    if not message.text: return

    wait_msg = await message.reply("🧐 Ща просвечу бирки ультрафиолетом...")
    try:
        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_LEGITCHECK},
                {"role": "user", "content": f"Зацени шмотку: {message.text}"}
            ],
            temperature=0.8,
            max_tokens=250
        )
        ai_reply = response.choices[0].message.content.strip()
        await wait_msg.edit_text(f"🧢 **ВЕРДИКТ НИКИТЫ:**\n\n{ai_reply}")
    except Exception:
        await wait_msg.edit_text("Чел, от этой пали у меня нейронка зависла. Выкинь это срочно!")
    
    await state.clear()

# --- 💖 2. СОБРАТЬ ЛУК ДЛЯ СОНИ (КВЕСТ) ---
@dp.message(Command("fit"))
async def ritual_start(message: types.Message, state: FSMContext):
    await message.reply(
        "💖 **Братик, у меня свиданка с Соней!** Соня мири богиня, мне надо выглядеть на все 100!\n\n"
        "Давай подберем лук. Скинь мне эмодзи футболки (👕), чтоб я надел!"
    )
    await state.set_state(RitualFlow.waiting_for_shirt)

@dp.message(RitualFlow.waiting_for_shirt)
async def ritual_egg_step(message: types.Message, state: FSMContext):
    if await check_interrupt(message, state): return
    if not message.text: return
    
    if "👕" in message.text:
        await message.reply(
            "Норм, накинул. Теперь главное! Какой бренд должен быть написан на груди, чтоб Соня прям потекла?\n"
            "Напиши название бренда!"
        )
        await state.set_state(RitualFlow.waiting_for_brand)
    else:
        await message.reply("Какая же это футболка?! Я перед Соней голым что ли пойду?! Кидай 👕!")

@dp.message(RitualFlow.waiting_for_brand)
async def ritual_spit_step(message: types.Message, state: FSMContext):
    if await check_interrupt(message, state): return
    if not message.text: return
    
    text = message.text.lower()
    if "гоша" in text or "рубчинский" in text or "stone island" in text or "рик" in text:
        await message.reply(
            "🔥 **ЛУК СОБРАН!**\n\n"
            f"Дааа! {message.text} — это база! Гоша рубчинский мой повелитель! "
            "Соня просто упадет, когда меня увидит. Отдуши, братик! тэзасажу мэ э сонякэ!"
        )
        await state.clear()
    else:
        await message.reply("Фу, кринж! Соня меня загнобит в таком! Давай нормальный бренд (например, Гоша Рубчинский или Stone Island)!")

# --- ⚔️ 3. РАЗРУЛИТЬ ТЕРКИ ---
@dp.message(Command("terki"))
async def court_start(message: types.Message, state: FSMContext):
    await message.reply("⚔️ Че, рамсы? Пиши, кто с кем сцепился и че не поделили. Ща раскидаю по фэшн-понятиям. (Отмена: /cancel)")
    await state.set_state(CourtFlow.waiting_for_details)

@dp.message(CourtFlow.waiting_for_details)
async def court_process(message: types.Message, state: FSMContext):
    if await check_interrupt(message, state): return
    if not message.text: return
    
    wait_msg = await message.reply("⏳ Спрашиваю у Сони, че она думает по этому поводу...")
    try:
        res = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[{"role": "system", "content": SYSTEM_PROMPT_COURT}, {"role": "user", "content": message.text}]
        )
        await wait_msg.edit_text(f"⚖️ **БАЗА ОТ НИКИТЫ:**\n\n{res.choices[0].message.content.strip()}")
    except:
        await wait_msg.edit_text("Вы оба в пали, мне даже впадлу разбираться. Соня мири богиня, пойду ей напишу.")
    await state.clear()

# --- РИСОВАЛКА ---
@dp.message(Command("narisui"))
async def generate_image_handler(message: types.Message):
    raw_text = message.text or ""
    clean_prompt = re.sub(r'(/narisui|никита|нарисуй|@\w+)', '', raw_text, flags=re.IGNORECASE).strip()
    if not clean_prompt:
        await message.reply("Че рисовать-то? Напиши 'нарисуй Соню в Стоуне', например!")
        return
    encoded_prompt = urllib.parse.quote(clean_prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    await message.reply_photo(photo=image_url, caption=f"Зацени пикчу: «{clean_prompt}». Гоша рубчинский мой повелитель!")

# --- АНАЛИЗ ФОТО ---
@dp.message(F.photo & F.caption & (F.caption.lower().contains("никита") | F.caption.lower().contains("соня")))
async def photo_handler(message: types.Message):
    try:
        photo = message.photo[-1]
        file_bytes: BytesIO = await bot.download(photo)
        base64_image = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        res = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [{"type": "text", "text": "Оцени этот лук или фотку как хайпбист Никита:"}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}
            ],
            max_tokens=150
        )
        await message.reply(res.choices[0].message.content.strip())
    except:
        await message.reply("Бро, у меня инет лагает, фотка не грузит. Пойду пока Соне кружочек запишу.")

# --- ОБРАБОТКА ОБЫЧНЫХ СООБЩЕНИЙ ---
@dp.message(F.text)
async def handle_nikita_messages(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return

    text_lower = message.text.lower()
    await save_phrase(message.text)

    # Триггеры: Никита, Соня, Сонечка, Гоша
    if not any(word in text_lower for word in ["никита", "сон", "гоша"]):
        return

    try:
        res = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": message.text}],
            temperature=0.85,
            max_tokens=150
        )
        ai_reply = res.choices[0].message.content.strip()
    except:
        ai_reply = "Чел, я отвлекся, Соня фотку новую выложила. Че ты там хотел?"

    # Добавляем его рандомные фразочки
    if random.random() < 0.4:
        random_phrase = random.choice(NIKITA_PHRASES)
        final_reply = f"{random_phrase} {ai_reply}" if random.choice([True, False]) else f"{ai_reply} {random_phrase}"
    else:
        final_reply = ai_reply

    if random.random() < 0.05:
        learned = await get_random_learned_phrase()
        if learned: final_reply += f" Как там говорят модники? А, во: «{learned}»."

    await message.reply(final_reply)

# --- WEB СЕРВЕР И ПИНГ ДЛЯ RENDER ---
async def handle_ping(request):
    return web.Response(text="Никита ждет Соню и чекает дропы.")

async def self_ping():
    await asyncio.sleep(10)
    port = os.getenv("PORT", "8080")
    render_url = os.getenv("RENDER_EXTERNAL_URL", f"http://127.0.0.1:{port}")
    async with ClientSession() as session:
        while True:
            try:
                async with session.get(render_url) as resp: pass
            except: pass
            await asyncio.sleep(600)

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    await set_bot_commands(bot)
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    asyncio.create_task(self_ping())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
