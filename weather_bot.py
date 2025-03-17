import os
import time
import logging
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from telegram.utils.request import Request  # Новый импорт для настройки таймаута

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
CACHE_TTL = 600  # время жизни кэша в секундах (10 минут)
weather_cache = {}  # словарь для хранения данных по городам: ключ - название города (нижний регистр), значение - (timestamp, current_data, forecast_data)

def get_weather(city: str):
    """
    Получает данные текущей погоды и прогноз по городу.
    Если данные уже есть в кэше и не устарели, возвращает их из кэша.
    """
    now = time.time()
    city_key = city.lower()
    if city_key in weather_cache:
        timestamp, cached_current, cached_forecast = weather_cache[city_key]
        if now - timestamp < CACHE_TTL:
            logger.info(f"Используем кэш для города: {city}")
            return cached_current, cached_forecast

    url_current = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    response_current = requests.get(url_current)
    if response_current.status_code != 200:
        return None, None
    current_data = response_current.json()

    # Проверяем корректность ответа API (например, если город не найден, OpenWeatherMap возвращает cod != 200)
    if current_data.get("cod") != 200:
        return None, None

    url_forecast = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    response_forecast = requests.get(url_forecast)
    forecast_data = None
    if response_forecast.status_code == 200:
        forecast_data = response_forecast.json()

    # Сохраняем данные в кэш
    weather_cache[city_key] = (now, current_data, forecast_data)
    return current_data, forecast_data

def generate_weather_image(weather: dict, forecast: dict):
    """
    Генерирует изображение с информацией о погоде.
    Цвет фона подбирается в зависимости от погодного состояния (Clear, Clouds, Rain, Snow и т.д.),
    накладывается текст с описанием погоды, температурой и скоростью ветра, а также уведомление,
    если прогноз меняется (например, дождь).
    """
    main_weather = weather["weather"][0]["main"]
    description = weather["weather"][0]["description"].capitalize()
    temp = weather["main"]["temp"]
    wind_speed = weather["wind"]["speed"]

    # Выбор цвета фона
    if main_weather == "Clear":
        bg_color = (135, 206, 235)  # светло-голубой для ясной погоды
    elif main_weather == "Clouds":
        bg_color = (192, 192, 192)  # серый для облачно
    elif main_weather == "Rain":
        bg_color = (100, 100, 100)  # темно-серый для дождя
    elif main_weather == "Snow":
        bg_color = (255, 250, 250)  # слегка голубоватый белый для снега
    else:
        bg_color = (200, 200, 200)  # универсальный серый оттенок

    # Создание изображения
    width, height = 800, 400
    image = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(image)

    # Попытка загрузить шрифт arial.ttf, иначе используется шрифт по умолчанию
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except IOError:
        font = ImageFont.load_default()

    # Формирование основного текста
    text = f"Погода: {description}\nТемпература: {temp}°C\nВетер: {wind_speed} м/с"
    draw.multiline_text((50, 50), text, fill=(0, 0, 0), font=font, spacing=10)

    # Анализируем прогноз: если ближайший прогноз (следующие 3 часа) отличается от текущего состояния,
    # добавляем уведомление (например, взять зонт при дожде)
    forecast_message = ""
    if forecast and "list" in forecast and len(forecast["list"]) > 0:
        next_forecast = forecast["list"][0]
        forecast_weather = next_forecast["weather"][0]["main"]
        forecast_description = next_forecast["weather"][0]["description"].capitalize()
        if forecast_weather != main_weather:
            if forecast_weather == "Rain":
                forecast_message = "В ближайшее время прогнозируется дождь. Не забудьте взять зонт!"
            else:
                forecast_message = f"В ближайшее время ожидается: {forecast_description}"
    if forecast_message:
        draw.text((50, 250), forecast_message, fill=(0, 0, 0), font=font)

    # Сохранение изображения в BytesIO для отправки в Telegram
    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

def start_handler(update: Update, context: CallbackContext):
    """
    Обработчик команды /start.
    """
    update.message.reply_text("Привет! Напиши название города, чтобы узнать погоду.")

def weather_handler(update: Update, context: CallbackContext):
    """
    Обработчик текстовых сообщений – ожидается название города.
    Если город введён с ошибкой или API не возвращает данные, выводится сообщение с просьбой проверить название.
    """
    city = update.message.text.strip()
    logger.info(f"Получен запрос для города: {city}")
    current_data, forecast_data = get_weather(city)
    if current_data is None:
        update.message.reply_text(
            "Проверьте правильность названия города! Используйте формат, например: Москва, Санкт-Петербург и т.д."
        )
        return

    # Генерация изображения с погодой
    image_bytes = generate_weather_image(current_data, forecast_data)

    # Формирование подписи к изображению
    description = current_data["weather"][0]["description"].capitalize()
    temp = current_data["main"]["temp"]
    wind_speed = current_data["wind"]["speed"]
    caption = f"Погода: {description}\nТемпература: {temp}°C\nВетер: {wind_speed} м/с"

    # Добавление прогнозного уведомления, если оно имеется
    forecast_message = ""
    if forecast_data and "list" in forecast_data and len(forecast_data["list"]) > 0:
        next_forecast = forecast_data["list"][0]
        forecast_weather = next_forecast["weather"][0]["main"]
        forecast_description = next_forecast["weather"][0]["description"].capitalize()
        if forecast_weather != current_data["weather"][0]["main"]:
            if forecast_weather == "Rain":
                forecast_message = "\nВ ближайшее время ожидается дождь. Не забудьте взять зонт!"
            else:
                forecast_message = f"\nВ ближайшее время ожидается: {forecast_description}"
    caption += forecast_message

    # Отправка изображения с подписью
    update.message.reply_photo(photo=image_bytes, caption=caption)

def main():
    # Создаем объект Request с увеличенными параметрами таймаута
    req = Request(connect_timeout=10, read_timeout=20)
    updater = Updater(token=TELEGRAM_TOKEN, request=req)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, weather_handler))

    logger.info("Бот запущен...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
