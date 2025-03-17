import os
import time
import logging
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токены из переменных окружения
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")

if not TELEGRAM_TOKEN or not WEATHER_API_KEY:
    logger.error("Необходимо установить переменные окружения TELEGRAM_TOKEN и WEATHER_API_KEY")
    exit(1)

# Настройки кэширования
CACHE_TTL = 600  # 10 минут
weather_cache = {}  # { city_name: (timestamp, current_data, forecast_data) }

def get_weather(city: str):
    now = time.time()
    city_key = city.lower()
    if city_key in weather_cache:
        timestamp, cached_current, cached_forecast = weather_cache[city_key]
        if now - timestamp < CACHE_TTL:
            logger.info(f"Используем кэш для города: {city}")
            return cached_current, cached_forecast

    # Запрос текущей погоды
    url_current = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    response_current = requests.get(url_current)
    if response_current.status_code != 200:
        return None, None
    current_data = response_current.json()
    if current_data.get("cod") != 200:
        return None, None

    # Запрос прогноза
    url_forecast = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    response_forecast = requests.get(url_forecast)
    forecast_data = None
    if response_forecast.status_code == 200:
        forecast_data = response_forecast.json()

    weather_cache[city_key] = (now, current_data, forecast_data)
    return current_data, forecast_data

def generate_weather_image(weather: dict, forecast: dict, city_name: str):
    """
    Генерирует изображение, используя готовый фон в зависимости от типа погоды.
    На фон накладывается текст с информацией о погоде и прогнозом.
    """
    main_weather = weather["weather"][0]["main"]
    description = weather["weather"][0]["description"].capitalize()
    temp = weather["main"]["temp"]
    wind_speed = weather["wind"]["speed"]

    # Выбираем фон в зависимости от основного состояния погоды
    if main_weather == "Clear":
        bg_path = "assets/sunny.png"
    elif main_weather == "Rain":
        bg_path = "assets/rain.png"
    elif main_weather == "Snow":
        bg_path = "assets/snow.png"
    elif main_weather == "Clouds":
        bg_path = "assets/cloudy.png"
    else:
        bg_path = "assets/default.png"  # или можно выбрать один из вышеуказанных

    try:
        bg = Image.open(bg_path).convert("RGBA")
    except IOError:
        # Если фон не найден, создаем базовый фон
        bg = Image.new("RGBA", (800, 400), (200, 200, 200, 255))

    draw = ImageDraw.Draw(bg)

    # Подключаем шрифт с поддержкой кириллицы
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 36)
    except IOError:
        font = ImageFont.load_default()

    # Формируем текст для основного виджета
    weather_text = (
        f"{city_name}\n"
        f"Погода: {description}\n"
        f"Температура: {temp:.1f}°C\n"
        f"Ветер: {wind_speed:.1f} м/с"
    )
    draw.multiline_text((50, 50), weather_text, fill="black", font=font, spacing=8)

    # Анализируем прогноз
    forecast_message = ""
    if forecast and "list" in forecast and len(forecast["list"]) > 0:
        next_forecast = forecast["list"][0]
        forecast_weather = next_forecast["weather"][0]["main"]
        forecast_desc = next_forecast["weather"][0]["description"].capitalize()
        if forecast_weather != main_weather:
            if forecast_weather == "Rain":
                forecast_message = "В ближайшее время ожидается дождь. Не забудьте взять зонт!"
            else:
                forecast_message = f"В ближайшее время ожидается: {forecast_desc}"
        else:
            forecast_message = "В ближайшее время погода не изменится."
        draw.text((50, 200), forecast_message, fill="black", font=font)

    img_byte_arr = BytesIO()
    bg.convert("RGB").save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return img_byte_arr

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Напиши название города, чтобы узнать погоду.")

async def weather_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text.strip()
    logger.info(f"Запрос для города: {city}")
    current_data, forecast_data = get_weather(city)
    if current_data is None:
        await update.message.reply_text(
            "Проверьте правильность названия города! "
            "Например: Москва, Санкт-Петербург, Киев и т.д."
        )
        return

    image_bytes = generate_weather_image(current_data, forecast_data, city)

    # Формируем подпись для картинки
    description = current_data["weather"][0]["description"].capitalize()
    temp = current_data["main"]["temp"]
    wind_speed = current_data["wind"]["speed"]
    caption = (
        f"{city}\n"
        f"Погода: {description}\n"
        f"Температура: {temp:.1f}°C\n"
        f"Ветер: {wind_speed:.1f} м/с"
    )
    if forecast_data and "list" in forecast_data and len(forecast_data["list"]) > 0:
        next_forecast = forecast_data["list"][0]
        forecast_weather = next_forecast["weather"][0]["main"]
        forecast_desc = next_forecast["weather"][0]["description"].capitalize()
        if forecast_weather != current_data["weather"][0]["main"]:
            if forecast_weather == "Rain":
                caption += "\nВ ближайшее время ожидается дождь. Не забудьте взять зонт!"
            else:
                caption += f"\nВ ближайшее время ожидается: {forecast_desc}"
        else:
            caption += "\nВ ближайшее время погода не изменится."

    await update.message.reply_photo(photo=image_bytes, caption=caption)

def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, weather_handler))
    logger.info("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
