import os
import time
import re
import requests
import logging
import sys
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Если используется GitHub Actions, в workflow добавьте установку Chrome и экспортуйте CHROME_MAJOR
# Например: echo "CHROME_MAJOR=136" >> $GITHUB_ENV

# Чтение учётных данных из окружения
EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")  # Ваш chat_id или group id

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Настройка логгера: консоль + Telegram
class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id):
        super().__init__()
        self.api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
    def emit(self, record):
        try:
            requests.post(self.api_url, data={"chat_id": self.chat_id, "text": self.format(record)})
        except:
            pass

logger = logging.getLogger("okru_auth")
logger.setLevel(logging.INFO)
# Консольный логгер
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(ch)
# Telegram-логгер
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(tg)

# Инициализация WebDriver
def init_driver():
    opts = uc.ChromeOptions()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    # Подставляем мэйджор-версию ChromeDriver из переменной окружения (fallback=136)
    version_main = int(os.getenv("CHROME_MAJOR", "136"))
    return uc.Chrome(options=opts, version_main=version_main)

# Запуск драйвера
driver = init_driver()
wait = WebDriverWait(driver, 20)

# 1) Подтверждение "It's you"
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm'] | //button[contains(text(),'Yes, confirm')] | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 'It's you' подтверждено.")
        driver.save_screenshot("after_confirm_identity.png")
        time.sleep(1)
    except Exception:
        logger.info("ℹ️ Страница 'It's you' не показана.")

# 2) Получение SMS-кода из Telegram
def retrieve_sms_code(timeout=120, poll_interval=5):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last_update = None
    # сброс старых апдейтов
    try:
        init = requests.get(api_url, params={'timeout':0}).json()
        if init.get('ok'):
            ids = [u['update_id'] for u in init.get('result', [])]
            last_update = max(ids) + 1 if ids else None
    except:
        last_update = None

    deadline = time.time() + timeout
    logger.info(f"⏳ Ожидание SMS-кода, таймаут {timeout}s...")
    while time.time() < deadline:
        try:
            resp = requests.get(api_url, params={'timeout':0,'offset': last_update}).json()
        except Exception as e:
            logger.warning(f"Ошибка Telegram API: {e}")
            time.sleep(poll_interval)
            continue
        if not resp.get('ok'):
            time.sleep(poll_interval)
            continue
        for upd in resp.get('result', []):
            last_update = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            text = msg.get('text','').strip()
            logger.info(f"📨 Сообщение: {text!r}")
            m = re.match(r"^(?:#код\s*)?(\d{4,6})$", text, flags=re.IGNORECASE)
            if m:
                code = m.group(1)
                logger.info(f"✅ Код найден: {code}")
                return code
        time.sleep(poll_interval)

    logger.error("❌ Таймаут ожидания SMS-кода")
    raise TimeoutException("SMS-код не получен (таймаут)")

# 3) Проверка логина по data-l и SMS-верификация
def try_sms_verification():
    try:
        data_l = driver.find_element(By.TAG_NAME, 'body').get_attribute('data-l') or ''
        if 'userMain' in data_l and 'anonymMain' not in data_l:
            logger.info("✅ По data-l пользователь залогинен, SMS не требуется.")
            return
        else:
            logger.info("🔄 Пользователь аноним, начинаем SMS-верификацию.")

        driver.save_screenshot("sms_verification_page.png")
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@type='submit' and @value='Get code']"
        )))
        btn.click()
        logger.info("📲 'Get code' нажат, SMS-код запрошен.")
        driver.save_screenshot("sms_requested.png")

        time.sleep(1)
        body_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        if "you are performing this action too often" in body_text:
            logger.error("🛑 Ограничение: слишком частые запросы.")
            driver.save_screenshot("sms_rate_limit.png")
            sys.exit(1)

        inp = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.XPATH,
            "//input[@id='smsCode' or contains(@name,'smsCode')]"
        )))
        driver.save_screenshot("sms_input_field.png")
        code = retrieve_sms_code()
        inp.clear()
        inp.send_keys(code)
        logger.info(f"✍️ Код введён: {code}")
        driver.save_screenshot("sms_code_entered.png")

        next_btn = driver.find_element(By.XPATH,
            "//input[@type='submit' and @value='Next']"
        )
        next_btn.click()
        logger.info("✅ SMS-код подтверждён, нажата 'Next'.")
        driver.save_screenshot("sms_confirmed.png")

    except TimeoutException:
        logger.error("❌ Не дождались SMS-кода или форма не появилась.")
        driver.save_screenshot("sms_timeout.png")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Ошибка SMS-верификации: {e}")
        driver.save_screenshot("sms_error.png")
        sys.exit(1)

# Основной сценарий
if __name__=='__main__':
    try:
        logger.info("🚀 Открываю OK.RU...")
        driver.get("https://ok.ru/")
        driver.save_screenshot("login_page.png")

        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.save_screenshot("credentials_entered.png")

        logger.info("🔑 Отправляю форму логина...")
        driver.find_element(By.XPATH, "//input[@type='submit']").click()
        time.sleep(2)
        driver.save_screenshot("after_login_submit.png")

        try_confirm_identity()
        try_sms_verification()

        logger.info("🎉 Авторизация завершена.")
    except Exception as ex:
        logger.error(f"🔥 Критическая ошибка: {ex}")
        driver.save_screenshot("fatal_error.png")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Драйвер закрыт.")
