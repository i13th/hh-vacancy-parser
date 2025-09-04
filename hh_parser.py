#!/usr/bin/env python
# coding: utf-8

# In[1]:


# Установливаем пакет schedule.
# get_ipython().system('pip install schedule')


# In[2]:


# Установка библиотек.
import requests  # Работа с HTTP-запросами (например, к API).
import psycopg2  # Подключение к PostgreSQL (подключение, запросы).
import schedule  # Планировщик задач (например, запуск в 12:00 и 20:00).
import random    # Генерация случайных чисел (например, задержки между запросами).
import time      # Работа со временем и задержками (например, паузы в выполнении).
import logging   # Ведение логов(запись событий: INFO, ERROR и т.д.).
from dotenv import load_dotenv # Функция load_dotenv из библиотеки python-dotenv.
                               #Для загрузки переменных окружения из файла .env в программу.
import os        # Для взаимодействия с операционной системой.


# In[3]:


# Установка токена API HeadHunter.
hh_api_token = None # Токен для авторизации в API hh.ru. None — значит, не используем (достаточно для чтения вакансий).


# In[4]:


# Конфигурация базы данных.
load_dotenv()  # Загружает переменные из файла .env.

db_config = {
    'dbname': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'port': os.getenv('DB_PORT')
}


# In[5]:


# Настройка логирования.
# Уровень логирования: INFO и выше (WARNING, ERROR) и формат каждой записи: время, уровень, сообщение.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("parser.log", encoding="utf-8"),  # Логи в файл.
        logging.StreamHandler()                               # Логи в консоль/Jupyter.
    ]
)

# In[6]:


# Функция для создания таблицы.
def create_table(conn):
    cursor = conn.cursor() # Создаёт курсор для выполнения SQL-запросов.
    create_table_query = """
        CREATE TABLE IF NOT EXISTS vacancies (
            id SERIAL PRIMARY KEY,
            city VARCHAR(50),
            company VARCHAR(200),
            industry VARCHAR(200),
            title VARCHAR(200),
            keywords TEXT,
            skills TEXT,
            experience VARCHAR(50),
            salary VARCHAR(50),
            url VARCHAR(200) UNIQUE,
            work_format VARCHAR(50)
        )
    """
    # Создаёт таблицу 'vacancies', если её ещё нет.
    # Поля: id (уникальный), город, компания, отрасль, название вакансии, 
    # ключевые слова, навыки, опыт, зарплата, ссылка, формат работы.
    # url — уникальный (UNIQUE), чтобы избежать дубликатов.
    cursor.execute(create_table_query)
    conn.commit()  # Сохраняет изменения в базе данных.
    cursor.close() # Закрывает курсор.
    logging.info("Таблица 'vacancies' успешно создана или уже существует.")

# Функция для добавления колонки work_format, если её нет.
def add_work_format_column_if_missing(conn):
    cursor = conn.cursor() # Открывает курсор.
    try:                   # Пробует добавить колонку work_format (формат работы: удалённо, офис и т.п.).
        cursor.execute("""
            ALTER TABLE vacancies ADD COLUMN work_format VARCHAR(50);
        """)
        logging.info("Колонка 'work_format' добавлена в таблицу 'vacancies'.")
    except psycopg2.errors.DuplicateColumn: # Если колонка уже существует — пропускаем ошибку.
        pass
    except Exception as e: # Логирует любые другие ошибки.
        logging.error(f"Ошибка при добавлении колонки work_format: {e}")
    finally:
        conn.commit()      # Гарантирует сохранение изменений (или откат при ошибке).
        cursor.close()     # Закрывает курсор.


# In[7]:


# Функция для получения вакансий.
def get_vacancies(vacancy, city_id, page, schedule_type=None):
    url = 'https://api.hh.ru/vacancies' # Адрес API hh.ru для получения вакансий.
    params = {
        'text': vacancy, # Текст поискового запроса (например, "Аналитик").
        'area': city_id, # ID города (например, 1 — Москва).
        'per_page': 100, # Количество вакансий на одной странице (максимум 100).
        'page': page     # Номер страницы (0 — первая).
    }
    if schedule_type:    # Если указан тип графика (например, 'remote'), добавляем в параметры.
        params['schedule'] = schedule_type  # Только удалённые вакансии.

    headers = {
        'User-Agent': 'YourApp 1.0' # Обязательный заголовок: имитируем реальное приложение.
    }
    if hh_api_token:                # Если токен задан, добавляем его для авторизации.
        headers['Authorization'] = f'Bearer {hh_api_token}'

    try: # Отправляем GET-запрос к API hh.ru.
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status() # Проверяет, был ли ответ успешным.
        return response.json()      # Возвращает данные в формате JSON.
    except requests.exceptions.RequestException as e:
        # Если ошибка (сеть, таймаут, 404 и т.п.) — логируем и возвращаем пустой словарь.
        logging.error(f"Ошибка при запросе к API: {e}")
        return {}


# In[8]:


# Функция для получения отрасли компании.
def get_industry(company_id):
    if company_id is None:
        return 'Unknown'                              # Если ID компании нет — возвращаем "Неизвестно".
    url = f'https://api.hh.ru/employers/{company_id}' # API для получения данных о компании.
    try:
        response = requests.get(url, timeout=10)      # Получаем данные о компании.
        if response.status_code == 404:
            return 'Unknown'                          # Если компания не найдена — возвращаем "Неизвестно".
        response.raise_for_status()                   # Проверяем, успешен ли ответ.
        data = response.json()                        # Преобразуем в JSON.
        if 'industries' in data and len(data['industries']) > 0:
            # Берём название первой отрасли компании.
            return data['industries'][0].get('name', 'Unknown')
    except Exception as e:
            # При любой ошибке — логируем и возвращаем "Неизвестно".
        logging.warning(f"Ошибка при получении отрасли для компании {company_id}: {e}")
    return 'Unknown'


# In[9]:


# Функция для получения ключевых навыков (skills).
def get_vacancy_skills(vacancy_id):
    url = f'https://api.hh.ru/vacancies/{vacancy_id}' # API для получения деталей вакансии.
    try:
        response = requests.get(url, timeout=10)      # Запрос к API.
        response.raise_for_status()                   # Проверка успешности.
        data = response.json()                        # Данные вакансии.
        skills = [skill['name'] for skill in data.get('key_skills', [])]
        # Извлекаем список навыков. Если есть — объединяем в строку через запятую.
        return ', '.join(skills) if skills else 'Не указано'
    except Exception as e:
        # Извлекаем список навыков. Если есть — объединяем в строку через запятую.
        logging.warning(f"Ошибка при получении навыков для вакансии {vacancy_id}: {e}")
        return 'Ошибка получения'


# In[10]:


# Основная функция парсинга.
def parse_vacancies():
    # 🔁 Города и их ID на hh.ru (15 крупных городов).
    cities = {
        'Москва': 1,
        'Санкт-Петербург': 2,
        'Новосибирск': 3,
        'Екатеринбург': 4,
        'Казань': 87,
        'Нижний Новгород': 66,
        'Челябинск': 83,
        'Самара': 78,
        'Омск': 131,
        'Ростов-на-Дону': 80,
        'Уфа': 96,
        'Красноярск': 52,
        'Воронеж': 105,
        'Пермь': 53,
        'Волгоград': 23
    }

    # 🔑 Ключевые слова для поиска вакансий.
    vacancies = [
        'Аналитик',
        'Analyst'
    ]

    try:
                                                    # Подключаемся к PostgreSQL.
        with psycopg2.connect(**db_config) as conn:
            create_table(conn)                      # Создаём таблицу, если её нет.
            add_work_format_column_if_missing(conn) # Добавляем колонку work_format, если отсутствует.

            for city, city_id in cities.items():     # Цикл по всем городам.
                for vacancy in vacancies:            # Цикл по ключевым словам.
                    logging.info(f"Парсинг вакансий: '{vacancy}' в городе {city}") # Лог: начинаем парсинг.

                    # 🔹 Для всех городов кроме Москвы — ищем только удалённые вакансии.
                    schedule_filter = None          # По умолчанию — нет фильтра.
                    if city != 'Москва':
                        schedule_filter = 'remote'  # Только удалённая работа.

                    page = 0                        # Начинаем с первой страницы.
                    while True:                     # Цикл по страницам.
                        try:
                            # Запрашиваем вакансии с учётом фильтра по графику.
                            data = get_vacancies(vacancy, city_id, page, schedule_type=schedule_filter)

                            # Получаем список вакансий.
                            items = data.get('items', [])
                            if not items:           # Если вакансий нет — выходим из цикла.
                                break

                            with conn.cursor() as cursor: # Открываем курсор.
                                for item in items:        # Перебираем вакансии.
                                    # Фильтр: название вакансии должно содержать ключевое слово.
                                    if vacancy.lower() not in item['name'].lower():
                                        continue          # Пропускаем, если не подходит.
                                    # Формируем данные для сохранения.
                                    title = f"{item['name']} ({city})"                      # Название + город.
                                    keywords = item['snippet'].get('requirement', '') or '' # Требования из сниппета.
                                    skills = get_vacancy_skills(item['id'])                 # Получаем навыки.
                                    company = item['employer']['name']                      # Название компании.
                                    industry = get_industry(item['employer'].get('id'))     # Отрасль компании.
                                    experience = item['experience'].get('name', 'Не указано') # Опыт работы.
                                    salary = item['salary']                                 # Зарплата.
                                    if salary:                                              # Если указана.
                                        salary_from = salary.get('from')                    # Минимальная.
                                        salary_currency = salary.get('currency', '')        # Валюта.
                                        salary = f"{salary_from} {salary_currency}" if salary_from else "з/п не указана"
                                    else:
                                        salary = "з/п не указана"

                                    # Пытаемся получить поле 'work_format' из данных вакансии.
                                    # Формат работы (удалённо, полный день и т.п.).
                                    # Если поле отсутствует — возвращаем пустой список [], чтобы избежать ошибок.
                                    work_format_list = item.get('work_format', [])
                                    # Проверяем, есть ли хотя бы один элемент в списке work_format_list.
                                    # Если список не пуст — значит, формат работы указан в API.
                                    if work_format_list:
                                        # Берём первый элемент списка.
                                        # Из него извлекаем значение 'name', например: "Удалённо".
                                        # Если ключ 'name' отсутствует — подставляем значение по умолчанию.
                                        work_format = work_format_list[0].get('name', 'Не указано')
                                    else:
                                        # Если work_format отсутствует — пытаемся использовать резервное поле 'schedule'.
                                        # Например: {"id": "remote", "name": "Удаленная работа"}
                                        schedule_data = item.get('schedule')
                                        if schedule_data and isinstance(schedule_data, dict):
                                            # Извлекаем название графика работы, например: "Удаленная работа".
                                            # Если 'name' нет — используем значение по умолчанию.
                                            work_format = schedule_data.get('name', 'Не указано')
                                        else:
                                            # Если ни work_format, ни schedule недоступны — ставим нейтральное значение.
                                            work_format = 'Не указано'
                                    
                                    # 🔁 Гарантируем, что work_format — строка, не None.
                                    if not isinstance(work_format, str):
                                        work_format = 'Не указано'
                                        
                                    url = item['alternate_url'] # Ссылка на вакансию на сайте hh.ru.
                                    
                                    logging.debug(f"work_format для вакансии {item['id']}: '{work_format}'")
                                    
                                    # Вставляем данные (в колонку work_format).
                                    insert_query = """
                                        INSERT INTO vacancies 
                                        (city, 
                                        company, 
                                        industry, 
                                        title, 
                                        keywords, 
                                        skills, 
                                        experience, 
                                        salary, 
                                        url, 
                                        work_format) 
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                        ON CONFLICT (url) DO NOTHING
                                    """
                                    # Выполняем вставку.
                                    try:
                                        cursor.execute(insert_query, (
                                            city, 
                                            company, 
                                            industry, 
                                            title, 
                                            keywords, 
                                            skills, 
                                            experience, 
                                            salary, 
                                            url, 
                                            work_format
                                        ))
                                    except Exception as e:
                                        logging.error(f"Ошибка при вставке вакансии {item['id']}: {e}")
                                        continue  # Пропустить только эту вакансию.

                            # Сохраняем после каждой страницы.
                            conn.commit()
                            logging.info(f"✅ Страница {page} для '{vacancy}' в {city} сохранена.")
                            # Проверяем, есть ли ещё страницы.
                            if page >= data.get('pages', 1) - 1:
                                break                         # Выходим, если это последняя страница.

                            page += 1                         # Переходим к следующей странице.
                            time.sleep(random.uniform(3, 6))  # Анти-бан задержка.
                                                              # Задержка от 3 до 6 секунд, чтобы не перегружать API.

                        except Exception as e:
                            # При ошибке — логируем и переходим к следующей вакансии.
                            logging.error(f"Ошибка при обработке страницы {page} для '{vacancy}' в {city}: {e}")
                            break  # Переход к следующей вакансии.

            logging.info("✅ Парсинг завершён. Данные сохранены в PostgreSQL.") # Лог: парсинг завершён.

    except Exception as e:
        logging.error(f"Ошибка подключения к БД: {e}", exc_info=True) # Ошибка подключения к БД — логируем с деталями.


# In[11]:


# Задача по расписанию.
def run_parsing_job():
    logging.info("🔄 Запуск ежедневного парсинга...")
    parse_vacancies() # Вызывает основную функцию парсинга.


# In[12]:


# Планировщик.
schedule.every().day.at("12:00").do(run_parsing_job) # Назначает запуск функции run_parsing_job() каждый день в 12:00.
schedule.every().day.at("20:00").do(run_parsing_job) # И второй запуск — в 20:00.


# In[ ]:


# Запуск.
if __name__ == "__main__": # Лог: скрипт запущен.
    logging.info("Запуск парсера. Ожидание времени запуска...")
    # Бесконечный цикл: проверяет, не настало ли время запуска.
    while True:
        schedule.run_pending() # Проверяет, есть ли задачи на выполнение.
        time.sleep(1)          # Ждёт 1 секунду перед следующей проверкой.


# In[ ]:




