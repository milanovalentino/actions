import os
import time
import re
import requests
import logging
import sys
import tempfile
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Чтение учётных данных из окружения
EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Логгер: консоль + Telegram
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

logger = logging.getLogger("okru_bot")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fmt)
logger.addHandler(ch)
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(fmt)
logger.addHandler(tg)

# Инициализация WebDriver
def init_driver():
    opts = uc.ChromeOptions()
    
    # Используем headless, но не new (для совместимости с Xvfb)
    if os.getenv('DISPLAY'):
        # Если есть DISPLAY (Xvfb), не используем headless
        logger.info("🖥️ Обнаружен DISPLAY, работаем с Xvfb")
    else:
        opts.add_argument('--headless=new')
        logger.info("🔇 Работаем в headless режиме")
    
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--disable-extensions')
    opts.add_argument('--disable-plugins')
    opts.add_argument('--disable-web-security')
    opts.add_argument('--allow-running-insecure-content')
    opts.add_argument('--disable-popup-blocking')
    opts.add_argument('--disable-notifications')
    
    # Настройки для загрузки файлов
    temp_dir = os.getenv('TEMP_VIDEO_DIR', tempfile.gettempdir())
    prefs = {
        "download.default_directory": temp_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_settings.popups": 0,
        "profile.default_content_setting_values.automatic_downloads": 1
    }
    opts.add_experimental_option("prefs", prefs)
    
    version_main = int(os.getenv("CHROME_MAJOR", "136"))
    
    try:
        driver = uc.Chrome(options=opts, version_main=version_main)
        logger.info(f"✅ Chrome инициализирован с версией {version_main}")
        return driver
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации драйвера с версией {version_main}: {e}")
        try:
            # Пробуем без указания версии
            driver = uc.Chrome(options=opts)
            logger.info("✅ Chrome инициализирован без указания версии")
            return driver
        except Exception as e2:
            logger.error(f"❌ Критическая ошибка инициализации драйвера: {e2}")
            raise

driver = init_driver()
wait = WebDriverWait(driver, 20)

# Функция для создания скриншота при ошибках
def take_screenshot(name="error"):
    try:
        timestamp = int(time.time())
        filename = f"{name}_{timestamp}.png"
        driver.save_screenshot(filename)
        logger.info(f"📸 Скриншот сохранен: {filename}")
        return filename
    except Exception as e:
        logger.error(f"❌ Не удалось создать скриншот: {e}")
        return None

# Отправка ссылки на пост в Telegram
def send_post_link_to_telegram(post_link):
    try:
        full_url = f"https://ok.ru{post_link}" if post_link.startswith('/') else post_link
        message = f"✅ Пост опубликован: {full_url}"
        
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        response = requests.post(api_url, data={
            "chat_id": TELEGRAM_USER_ID, 
            "text": message
        })
        
        if response.json().get('ok'):
            logger.info(f"📤 Ссылка отправлена в Telegram: {full_url}")
        else:
            logger.error(f"❌ Ошибка отправки в Telegram: {response.text}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки ссылки в Telegram: {e}")

# Поиск ссылки на опубликованный пост
def wait_for_post_link(timeout=30):
    try:
        logger.info("⏳ Ищу ссылку на опубликованный пост...")
        
        # Ждем появления уведомления о публикации
        tip_selectors = [
            "#hook_Block_TipBlock .js-tip-block-url",
            ".tip-block_lk a.js-tip-block-url",
            ".action-tip a[href*='/topic/']",
            ".toast a[href*='/topic/']"
        ]
        
        for i in range(timeout):
            for selector in tip_selectors:
                try:
                    link_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for link_element in link_elements:
                        if link_element.is_displayed():
                            post_link = link_element.get_attribute("href")
                            if post_link and "/topic/" in post_link:
                                logger.info(f"✅ Найдена ссылка на пост: {post_link}")
                                return post_link
                except:
                    continue
            
            time.sleep(1)
            
            # Логируем прогресс каждые 10 секунд
            if i % 10 == 0 and i > 0:
                logger.info(f"⏳ Поиск ссылки на пост... ({i}/{timeout} сек)")
        
        logger.warning("⚠️ Ссылка на пост не найдена в течение таймаута")
        return None
        
    except Exception as e:
        logger.error(f"❌ Ошибка поиска ссылки на пост: {e}")
        return None

# Подтверждение личности, если требуется
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm']"
            " | //button[contains(text(),'Yes, confirm')]"
            " | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 Подтверждена личность")
        time.sleep(1)
    except Exception:
        logger.info("ℹ️ Страница подтверждения личности не показана")

# Получение SMS-кода из Telegram
def retrieve_sms_code(timeout=120, poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        ids = [u['update_id'] for u in init.get('result', [])]
        last = max(ids)+1 if ids else None
    except:
        pass
    deadline = time.time() + timeout
    logger.info("⏳ Ожидаю SMS-код")
    while time.time() < deadline:
        try:
            resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        except:
            time.sleep(poll)
            continue
        if not resp.get('ok'):
            time.sleep(poll)
            continue
        for upd in resp['result']:
            last = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            txt = msg.get('text','').strip()
            m = re.match(r"^(?:#код\s*)?(\d{4,6})$", txt, re.IGNORECASE)
            if m:
                code = m.group(1)
                logger.info("✅ Код получен")
                return code
        time.sleep(poll)
    logger.error("❌ Таймаут SMS-кода")
    raise TimeoutException("SMS-код не получен")

# SMS-верификация
def try_sms_verification():
    data_l = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
    if 'userMain' in data_l and 'anonymMain' not in data_l:
        logger.info("✅ Уже залогинен")
        return
    logger.info("🔄 Запрашиваю SMS-код")
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//input[@type='submit' and @value='Get code']"
    )))
    btn.click()
    time.sleep(1)
    if 'too often' in driver.find_element(By.TAG_NAME,'body').text.lower():
        logger.error("🛑 Rate limit")
        sys.exit(1)
    inp = wait.until(EC.presence_of_element_located((By.XPATH,
        "//input[@id='smsCode' or contains(@name,'smsCode')]"
    )))
    code = retrieve_sms_code()
    inp.clear()
    inp.send_keys(code)
    logger.info("✍️ Ввёл SMS-код")
    next_btn = driver.find_element(By.XPATH,
        "//input[@type='submit' and @value='Next']"
    )
    next_btn.click()
    logger.info("✅ SMS-верификация успешна")

# Скачивание файла из Telegram
def download_file_from_telegram(file_id):
    try:
        # Получаем информацию о файле
        file_info_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile"
        response = requests.get(file_info_url, params={'file_id': file_id})
        file_info = response.json()
        
        if not file_info.get('ok'):
            logger.error(f"❌ Ошибка получения информации о файле: {file_info}")
            return None
        
        file_size = file_info['result'].get('file_size', 0)
        # Проверяем размер файла (лимит Telegram Bot API - 20MB)
        if file_size > 20 * 1024 * 1024:
            logger.error(f"❌ Файл слишком большой: {file_size} байт (лимит 20MB)")
            return None
            
        file_path = file_info['result']['file_path']
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        
        logger.info(f"📥 Скачиваю файл размером {file_size} байт")
        
        # Скачиваем файл с таймаутом
        file_response = requests.get(file_url, timeout=60)
        if file_response.status_code == 200:
            # Используем кастомную папку для GitHub Actions
            temp_dir = os.getenv('TEMP_VIDEO_DIR', tempfile.gettempdir())
            os.makedirs(temp_dir, exist_ok=True)
            
            # Создаем временный файл
            temp_file = tempfile.NamedTemporaryFile(
                delete=False, 
                suffix=os.path.splitext(file_path)[1],
                dir=temp_dir
            )
            temp_file.write(file_response.content)
            temp_file.close()
            
            # Проверяем, что файл действительно записался
            if os.path.exists(temp_file.name):
                actual_size = os.path.getsize(temp_file.name)
                logger.info(f"✅ Файл скачан: {temp_file.name} ({actual_size} байт)")
                return temp_file.name
            else:
                logger.error("❌ Файл не был сохранен")
                return None
        else:
            logger.error(f"❌ Ошибка скачивания файла: {file_response.status_code}")
            return None
    except Exception as e:
        logger.error(f"❌ Ошибка при скачивании файла: {e}")
        return None

# Ожидание команды #группы и извлечение URL групп
def retrieve_groups(poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        ids = [u['update_id'] for u in init.get('result', [])]
        last = max(ids)+1 if ids else None
    except:
        pass
    logger.info("⏳ Жду команду #группы")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                txt = msg.get('text','').strip()
                m = re.match(r"#группы\s+(.+)", txt, re.IGNORECASE)
                if m:
                    urls = re.findall(r"https?://ok\.ru/group/\d+/?", m.group(1))
                    if urls:
                        logger.info("✅ Группы получены")
                        return urls
        time.sleep(poll)

# Ожидание команды #пост и извлечение видео/текста
def retrieve_post_info(poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        ids = [u['update_id'] for u in init.get('result', [])]
        last = max(ids)+1 if ids else None
    except:
        pass
    logger.info("⏳ Жду команду #пост")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                
                # Проверяем, есть ли команда #пост в тексте
                txt = msg.get('text', '').strip()
                caption = msg.get('caption', '').strip()
                
                # Ищем команду в тексте или подписи
                post_match = None
                if txt:
                    post_match = re.match(r"#пост\s*(.*)", txt, re.IGNORECASE)
                elif caption:
                    post_match = re.match(r"#пост\s*(.*)", caption, re.IGNORECASE)
                
                if post_match:
                    post_text = post_match.group(1).strip() if post_match.group(1) else ""
                    
                    # Проверяем, есть ли видео или ссылка на видео
                    video_file = None
                    video_url = None
                    
                    # Сначала проверяем, есть ли видеофайл
                    if 'video' in msg:
                        video_info = msg['video']
                        file_id = video_info['file_id']
                        logger.info("📹 Найдено видео в сообщении")
                        video_file = download_file_from_telegram(file_id)
                    
                    # Если видеофайла нет, ищем ссылку в тексте
                    if not video_file:
                        full_text = (txt + " " + caption + " " + post_text).strip()
                        url_match = re.search(r"https?://\S+", full_text)
                        if url_match:
                            video_url = url_match.group(0)
                            post_text = full_text.replace(video_url, "").replace("#пост", "").strip()
                            logger.info("🔗 Найдена ссылка на видео")
                    
                    if video_file or video_url:
                        logger.info("✅ Пост-инфо получено")
                        return video_file, video_url, post_text
                    else:
                        logger.warning("⚠️ Не найдено видео или ссылки в команде #пост")
        
        time.sleep(poll)

# Постинг в группу (с улучшенной проверкой загрузки через активность кнопки Share)
def post_to_group(group_url, video_file=None, video_url=None, text=""):
    post_url = group_url.rstrip('/') + '/post'
    logger.info("🚀 Открываю страницу постинга")
    
    try:
        driver.get(post_url)
        time.sleep(3)  # Даем время загрузиться
        
        # Ждем загрузки страницы
        box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
            "div[contenteditable='true']"
        )))
        box.click()
        logger.info("✅ Поле для ввода найдено")
        
        # Если есть видеофайл, загружаем его
        if video_file and os.path.exists(video_file):
            try:
                logger.info(f"📤 Начинаю загрузку видеофайла: {video_file}")
                file_size = os.path.getsize(video_file)
                logger.info(f"📁 Размер файла: {file_size} байт")
                
                # Проверяем начальное состояние кнопки Share (должна быть неактивна)
                share_button = driver.find_element(By.CSS_SELECTOR, "button.js-pf-submit-btn[data-action='submit']")
                initial_disabled = share_button.get_attribute("disabled") is not None
                logger.info(f"🔘 Начальное состояние кнопки Share: {'отключена' if initial_disabled else 'активна'}")
                
                # Шаг 1: Находим и кликаем кнопку "Video"
                video_button_selectors = [
                    "div[data-l='t,button.video'] .posting_ac_i",
                    "div[data-l*='button.video']",
                    ".js-video-btn",
                    "div[title='Add video']",
                    "div[aria-label='Add video']"
                ]
                
                video_button = None
                for selector in video_button_selectors:
                    try:
                        video_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                        if video_button.is_displayed():
                            logger.info(f"🎬 Найдена кнопка Video: {selector}")
                            break
                    except:
                        continue
                
                if not video_button:
                    logger.error("❌ Не найдена кнопка Video")
                    take_screenshot("no_video_button")
                    return
                
                # Кликаем на кнопку Video
                video_button.click()
                logger.info("🎬 Кликнул на кнопку Video")
                time.sleep(3)  # Ждем загрузки модального окна
                
                # Шаг 2: Ждем появления модального окна и ищем input для загрузки
                upload_input = None
                upload_input_selectors = [
                    ".js-fileapi-input.video-upload-input",
                    "input.video-upload-input",
                    ".video-upload-wrapper input[type='file']",
                    ".js-upload-button input[type='file']",
                    "input[type='file'][accept*='video']"
                ]
                
                for selector in upload_input_selectors:
                    try:
                        upload_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                        if upload_input:
                            logger.info(f"📤 Найден input для загрузки: {selector}")
                            break
                    except:
                        continue
                
                if not upload_input:
                    logger.error("❌ Не найден input для загрузки файла")
                    take_screenshot("no_upload_input")
                    return
                
                # Шаг 3: Загружаем файл
                logger.info("📤 Загружаю видеофайл через input")
                upload_input.send_keys(video_file)
                
                # Увеличиваем время ожидания для больших файлов
                wait_time = min(120, max(30, file_size // (512 * 1024)))  # 1 сек на 512KB, мин 30, макс 120
                logger.info(f"⏳ Жду активации кнопки Share ({wait_time} сек)...")
                
                # Основная проверка: ждем когда кнопка Share станет активной
                upload_success = False
                for i in range(wait_time):
                    try:
                        # Обновляем ссылку на кнопку Share
                        share_button = driver.find_element(By.CSS_SELECTOR, "button.js-pf-submit-btn[data-action='submit']")
                        is_disabled = share_button.get_attribute("disabled") is not None
                        
                        # Если кнопка стала активной (нет атрибута disabled)
                        if not is_disabled:
                            upload_success = True
                            logger.info("✅ Кнопка Share активирована - видео загружено!")
                            break
                        
                        # Дополнительно проверяем на ошибки загрузки
                        error_selectors = [
                            ".upload-error",
                            ".error-message",
                            "div[data-state='error']",
                            ".js-upload-error"
                        ]
                        
                        for selector in error_selectors:
                            error_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            if error_elements:
                                error_text = error_elements[0].text
                                logger.error(f"❌ Ошибка загрузки: {error_text}")
                                take_screenshot("upload_error")
                                return
                        
                        time.sleep(1)
                        
                        # Логируем прогресс каждые 15 секунд
                        if i % 15 == 0 and i > 0:
                            logger.info(f"⏳ Ожидание активации кнопки Share... ({i}/{wait_time} сек)")
                            
                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка при проверке кнопки Share: {e}")
                        time.sleep(1)
                        continue
                
                if upload_success:
                    logger.info("✅ Видеофайл успешно загружен (кнопка Share активна)")
                    
                    # Пытаемся закрыть модальное окно если оно есть
                    modal_close_selectors = [
                        "button[data-action='close']",
                        "button[data-action='submit']",
                        ".button-pro[data-action='submit']",
                        ".modal-footer button",
                        "button.js-submit",
                        ".modal-close"
                    ]
                    
                    for selector in modal_close_selectors:
                        try:
                            close_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            for close_button in close_elements:
                                if close_button.is_displayed() and close_button.is_enabled():
                                    # Проверяем, что это не кнопка Share
                                    if "js-pf-submit-btn" not in close_button.get_attribute("class"):
                                        close_button.click()
                                        logger.info("✅ Модальное окно закрыто")
                                        time.sleep(2)
                                        break
                        except:
                            continue
                else:
                    logger.error("❌ Кнопка Share не активировалась - загрузка видео не завершена")
                    take_screenshot("share_button_not_activated")
                    return
                    
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки видеофайла: {e}")
                take_screenshot("video_upload_error")
                return
        
        # Если есть ссылка на видео, вставляем её
        elif video_url:
            box.clear()
            box.send_keys(video_url)
            box.send_keys(Keys.SPACE)
            logger.info("✍️ Ссылка на видео вставлена")
            
            # Ждём когда кнопка Share станет активной (это означает что превью загрузилось)
            logger.info("⏳ Жду активации кнопки Share для ссылки на видео...")
            link_processed = False
            for i in range(15):  # 15 секунд для ссылки должно хватить
                try:
                    share_button = driver.find_element(By.CSS_SELECTOR, "button.js-pf-submit-btn[data-action='submit']")
                    is_disabled = share_button.get_attribute("disabled") is not None
                    
                    if not is_disabled:
                        link_processed = True
                        logger.info("✅ Кнопка Share активирована - ссылка обработана!")
                        break
                    
                    time.sleep(1)
                except:
                    time.sleep(1)
                    continue
                
            if not link_processed:
                logger.warning("⚠️ Кнопка Share не активировалась для ссылки")
                take_screenshot("link_not_processed")

        # Добавляем текст
        if text:
            # Находим поле для ввода текста снова (может измениться после загрузки видео)
            try:
                text_box = driver.find_element(By.CSS_SELECTOR, "div[contenteditable='true']")
                text_box.click()
                
                # Если уже есть контент в поле, добавляем текст
                if video_url:
                    text_box.send_keys(" " + text)
                else:
                    text_box.send_keys(text)
                logger.info("✍️ Текст добавлен")
            except Exception as e:
                logger.error(f"❌ Ошибка добавления текста: {e}")

        # Финальная проверка активности кнопки Share перед публикацией
        try:
            share_button = driver.find_element(By.CSS_SELECTOR, "button.js-pf-submit-btn[data-action='submit']")
            is_disabled = share_button.get_attribute("disabled") is not None
            
            if is_disabled:
                logger.error("❌ Кнопка Share неактивна - не могу опубликовать")
                take_screenshot("share_button_disabled_before_publish")
                return
            
            # Публикуем
            share_button.click()
            logger.info("✅ Опубликовано")
            
            # Ищем ссылку на опубликованный пост
            post_link = wait_for_post_link(timeout=30)
            if post_link:
                send_post_link_to_telegram(post_link)
            else:
                logger.warning("⚠️ Не удалось получить ссылку на пост")
            
            time.sleep(5)  # Даем время на публикацию
                
        except Exception as e:
            logger.error(f"❌ Ошибка публикации: {e}")
            take_screenshot("publish_error")
            
    except Exception as e:
        logger.error(f"❌ Общая ошибка постинга в группу {group_url}: {e}")
        take_screenshot("post_general_error")
        
# Основной поток
def main():
    try:
        logger.info("🚀 Начинаю работу")
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        logger.info("🔑 Логин")
        driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
        time.sleep(2)
        try_confirm_identity()
        try_sms_verification()
        logger.info("🎉 Вход выполнен")

        groups = retrieve_groups()
        video_file, video_url, post_text = retrieve_post_info()
        
        for i, g in enumerate(groups, 1):
            logger.info(f"📝 Публикую в группу {i}/{len(groups)}: {g}")
            post_to_group(g, video_file, video_url, post_text)
    
    # Небольшая пауза между публикациями в разные группы
    if i < len(groups):
        time.sleep(3)
        
        # Удаляем временный файл, если он был создан
        if video_file and os.path.exists(video_file):
            try:
                os.unlink(video_file)
                logger.info("🗑️ Временный файл удален")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось удалить временный файл: {e}")

        # Дополнительная очистка временных файлов
        temp_dir = os.getenv('TEMP_VIDEO_DIR', tempfile.gettempdir())
        if temp_dir != tempfile.gettempdir():  # Только если используем кастомную папку
            try:
                import shutil
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.info("🗑️ Временная папка очищена")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось очистить временную папку: {e}")

        logger.info("🎉 Все задачи выполнены")
    except Exception as e:
        logger.error(f"🔥 Ошибка: {e}")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Завершено")

if __name__ == '__main__':
    main()
