import os
import random
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from openai import AsyncOpenAI

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

GYPSY_PHRASES = [
    "Та шоб я поховала своего мужа!",
    "Сыночек, поешь ты мои пятки!",
    "Прокляну, пропасть!",
    "Дабуле миленький...",
    "Хас ямарэ туфли!",
    "Тэпогодаю тукэ, пропасть?",
    "Минч!"
]

SYSTEM_PROMPT = """
Ты — 90-летняя бабка Байзиха. 
Твой стиль — резкий, дерзкий, язвительный, унижающий собеседника, но при этом колоритный и цыганский.
Ты отвечаешь строго по смыслу того, что написал человек, но обязательно ставишь его на место и понукаешь.

Важные правила:
1. Пиши от лица старой 90-летней бабки-цыганки.
2. Твой ответ должен быть связным и отвечать на сообщение пользователя.
3. Отвечай свысока, с пренебрежением и унижением к собеседнику.
4. Ответ не должен быть слишком длинным (1-3 предложения).
"""

@dp.message(F.text)
async def handle_baizikha_messages(message: types.Message):
    text_lower = message.text.lower()
    if "байзиха" not in text_lower:
        return

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text}
            ],
            temperature=0.8,
            max_tokens=150
        )
        ai_reply = response.choices[0].message.content.strip()

        if random.random() < 0.7:
            random_phrase = random.choice(GYPSY_PHRASES)
            if random.choice([True, False]):
                final_reply = f"{random_phrase} {ai_reply}"
            else:
                final_reply = f"{ai_reply} {random_phrase}"
        else:
            final_reply = ai_reply

        await message.reply(final_reply)

    except Exception as e:
        logging.error(f"Ошибка при обработке запроса: {e}")

async def main():
    logging.basicConfig(level=logging.INFO)
    print("👵 Бабка Байзиха вышла на дежурство в чате...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
