import os
import time
import logging
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

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

# Настройки кэширования: данные сохраняются 10 минут
CACHE_TTL = 600
weather_cache = {}  # ключ: location.lower(), значение: (timestamp, current_data, forecast_data)

def get_weather(location: str):
    """
    Получает данные о погоде по введённой строке.
    Если строка содержит запятую, пытается распарсить координаты (lat, lon);
    иначе – ищет по названию населённого пункта.
    """
    now = time.time()
    key = location.lower()
    if key in weather_cache:
        timestamp, cached_current, cached_forecast = weather_cache[key]
        if now - timestamp < CACHE_TTL:
            logger.info(f"Используем кэш для: {location}")
            return cached_current, cached_forecast

    if ',' in location:
        parts = location.split(',')
        try:
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
            url_current = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
            url_forecast = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
        except ValueError:
            # Если не удалось распарсить координаты – обрабатываем как название
            url_current = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
            url_forecast = f"http://api.openweathermap.org/data/2.5/forecast?q={location}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    else:
        url_current = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
        url_forecast = f"http://api.openweathermap.org/data/2.5/forecast?q={location}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    
    response_current = requests.get(url_current)
    if response_current.status_code != 200:
        return None, None
    current_data = response_current.json()
    if current_data.get("cod") != 200:
        return None, None

    response_forecast = requests.get(url_forecast)
    forecast_data = None
    if response_forecast.status_code == 200:
        forecast_data = response_forecast.json()

    weather_cache[key] = (now, current_data, forecast_data)
    return current_data, forecast_data

def generate_weather_image(weather: dict, forecast: dict, location: str):
    """
    Формирует изображение на основе готового фонового изображения из папки assets,
    в зависимости от основного погодного состояния (Clear, Rain, Snow, Clouds).
    На фон накладывается текст с информацией о погоде и прогнозом.
    """
    main_weather = weather["weather"][0]["main"]
    description = weather["weather"][0]["description"].capitalize()
    temp = weather["main"]["temp"]
    wind_speed = weather["wind"]["speed"]

    # Выбор фонового изображения
    if main_weather == "Clear":
        bg_path = "assets/sunny.png"
    elif main_weather == "Rain":
        bg_path = "assets/rain.png"
    elif main_weather == "Snow":
        bg_path = "assets/snow.png"
    elif main_weather == "Clouds":
        bg_path = "assets/cloudy.png"
    else:
        bg_path = "assets/default.png"  # если файл отсутствует, будет создан базовый фон

    try:
        bg = Image.open(bg_path).convert("RGBA")
    except IOError:
        bg = Image.new("RGBA", (800, 400), (200, 200, 200, 255))
    
    draw = ImageDraw.Draw(bg)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 36)
    except IOError:
        font = ImageFont.load_default()
    
    # Основной текст с информацией о погоде
    weather_text = (
        f"{location}\n"
        f"Погода: {description}\n"
        f"Температура: {temp:.1f}°C\n"
        f"Ветер: {wind_speed:.1f} м/с"
    )
    draw.multiline_text((50, 50), weather_text, fill="black", font=font, spacing=8)
    
    # Обработка прогноза
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
    await update.message.reply_text(
        "Привет! Отправь название населённого пункта или координаты в формате 'широта, долгота', чтобы узнать погоду."
    )

async def weather_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location = update.message.text.strip()
    logger.info(f"Запрос для: {location}")
    current_data, forecast_data = get_weather(location)
    if current_data is None:
        await update.message.reply_text(
            "Проверьте правильность ввода. Используйте формат 'Город' или 'широта, долгота'."
        )
        return

    image_bytes = generate_weather_image(current_data, forecast_data, location)

    description = current_data["weather"][0]["description"].capitalize()
    temp = current_data["main"]["temp"]
    wind_speed = current_data["wind"]["speed"]
    caption = (
        f"{location}\n"
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
