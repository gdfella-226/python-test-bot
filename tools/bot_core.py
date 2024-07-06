import hashlib
import requests
import re
import sqlite3
import telebot
import gspread
import uuid
from oauth2client.service_account import ServiceAccountCredentials
from yookassa import Configuration, Payment
from telebot.types import ReplyKeyboardRemove
from telebot import types
from loguru import logger
from time import sleep
from sys import exit
from os import listdir
from os.path import isfile, join
from json import load


class Bot:
    def __init__(self, ext_data: dict) -> None:
        """Create entity of Bot class with parameters passed from json-config
            - load google table
            - generate payment URL
            - upload language dictionaries
            - run TG-listeners
        Args:
            ext_data (dict): json-config parameters for TG-bot & Yoomoney
        """
        self.data = ext_data
        self.bot = telebot.TeleBot(self.data["token"])
        self.vocabularies = {}
        self.table_sheet = Bot.get_table(self.data["table"]) 
        self.pay_url =self.generate_payment_url()

        self.load_languages()
        self.message_handler()
        self.callback_handler()
        self.photo_handler()

    def load_languages(self) -> None:
        """Uplaod prepared .json dictionaries from '/data/lang'
           Currently available:
            - English
            - Russian
        """
        logger.info('Loading vocabularies')
        vocs = [join('./', 'data', 'lang', f) for f in listdir(join('./', 'data', 'lang', ))
                if isfile(join('./', 'data', 'lang', f))]
        for voc in vocs:
            with open(voc, encoding='utf-8', mode='r') as json_file:
                self.vocabularies[voc[voc.find('_') + 1:voc.rfind('.')]] = load(json_file)
                logger.success(f"Loaded {voc[voc.find('_') + 1:voc.rfind('.')]}")

    @staticmethod
    def get_table(url:str):
        """Connect to google-docs table by constat url
        Args:
            url (str): google table's URL
        Returns:
            sheet (gspread.models.Spreadsheet): first sheet from table
        """
        logger.info("Loading table")
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name("./data/pythontestbot-google-config.json", scope)
            client = gspread.authorize(creds)
            spreadsheet = client.open_by_url(url)
            sheet = spreadsheet.sheet1
            logger.success("Table loaded")
            return sheet
        except Exception as err:
            logger.error(f"Can't load table due to: {err}")
            exit(1)  
    
    @staticmethod
    def read_from_table(sheet) -> str:
        """Get value from 'A1' cell in sheet
        Args:
            sheet (gspread.models.Spreadsheet): google table's sheet
        Returns:
            str: cell value
        """
        try:
            cell_value = sheet.acell('A1').value
            return cell_value
        except Exception as err:
            logger.error(f"Can't write to table due to: {err}")
            return "Oups..."
    
    @staticmethod
    def write_to_table(sheet, value: str) -> bool:
        """Update value in A2 cell
        Args:
            sheet (gspread.models.Spreadsheet): _description_
            value (str): new value
        Returns:
            bool: success indication
        """
        try:
            sheet.update_acell('A2', value)
            logger.success('Write to table')
            return True
        except Exception as err:
            logger.error(f"Can't write to table due to: {err}")
            return False

    @staticmethod
    def add_user(new_user_data: dict) -> None:
        """Add new user to SQLite database
        Args:
            new_user_data (dict): user data ('id', 'plan', 'language', 'counter')
        """
        try:
            conn = sqlite3.connect('./data/users.sqlite')
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO users (id, plan, counter, language) VALUES (?, ?, ?, ?)',
                        (new_user_data['id'], new_user_data['plan'],
                            new_user_data['counter'], new_user_data['language']))
            conn.commit()
            conn.close()
        except Exception as err:
            logger.error("Add user error: {err}")
            exit(3)

    @staticmethod
    def update_user(user_id: int, field: str, new_val: str) -> None:
        """Update user data
        Args:
            user_id (int): user id in database (TG id) 
            field (str): field to update
            new_val (str): new val
        """
        try:
            conn = sqlite3.connect('./data/users.sqlite')
            cursor = conn.cursor()
            cursor.execute(f"UPDATE users SET {field} = '{new_val}' WHERE id = '{user_id}'")
            conn.commit()
            conn.close()
        except Exception as err:
            logger.error("Update user error: {err}")
            exit(3)

    @staticmethod
    def get_user(user_id: int) -> list:
        """Get data about user from data
        Args:
            user_id (int): user id in database (TG id) 
        Returns:
            list: user data
        """
        try:
            conn = sqlite3.connect('./data/users.sqlite')
            cursor = conn.cursor()
            cursor.execute(f'SELECT * FROM users WHERE id = {user_id}')
            data = cursor.fetchall()
            conn.commit()
            conn.close()
            return data
        except Exception as err:
            logger.error("Can't get user data due to: {err}")
            exit(3)

    def generate_payment_url(self) -> str:
        """Generate payment URL for Yoomoney
        Returns:
            str: URL (empty string in case of errors)
        """
        logger.info("Generating payment URL")
        try:
            Configuration.account_id = self.data["ym_data"]["client_id"]
            Configuration.secret_key = self.data["ym_data"]["client_secret"]
            self.payment = Payment.create(self.data["ym_data"]["payload"], uuid.uuid4())
            logger.success(f"Get URL: {self.payment.confirmation.confirmation_url}")
            return self.payment.confirmation.confirmation_url
        except Exception as err:
            logger.error(f"Can't generate URL due to: {err}")
            return ""

    def message_handler(self):
        """Proccess text messages from user:
            - '/start' (command) -> starts bot workflow, add user to database
            - 'dd.mm.yyyy' (text message) -> update value in google table with passed date
        """
        @self.bot.message_handler(commands=['start'])
        def send_welcome(message):
            Bot.add_user({'id': message.chat.id, 'plan': 'free', 'counter': 1, 'language': 'ru'})
            message_text = f"{self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['terms_message']}({self.data['terms']})"
            agree_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            agree_markup.add(
                '\N{white heavy check mark} ' + self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['agree_options'][
                    0],
                '\N{negative squared cross mark} ' +
                self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['agree_options'][1])
            self.bot.send_message(message.chat.id, message_text, parse_mode='Markdown', reply_markup=agree_markup)

        @self.bot.message_handler(func=lambda message: message.text and '\N{white heavy check mark}' in message.text)
        def user_agreed(message):
            self.bot.send_message(message.chat.id,
                                  self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['hello_message'],
                                  reply_markup=ReplyKeyboardRemove())
            base_markup = types.InlineKeyboardMarkup()
            base_markup.add(types.InlineKeyboardButton('\N{clockwise downwards and upwards open circle arrows} ' +
                                                       self.vocabularies[Bot.get_user(message.chat.id)[0][3]][
                                                           'buttons'][0],
                                                       callback_data="choose_language"),
                            types.InlineKeyboardButton(
                                '\N{clipboard} ' + self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['buttons'][
                                    1],
                                callback_data="menu"))
            self.bot.send_message(message.chat.id,
                                  self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['headers'][2],
                                  reply_markup=base_markup)
        
        @self.bot.message_handler(func=lambda message: message.text and re.search(r'\d\d\.\d\d\.\d\d\d\d', message.text))
        def process_date(message):
            Bot.write_to_table(self.table_sheet, message.text)

    def callback_handler(self):
        """Process pressed buttons:
            - Confirm/deny terms of usage
            - Chose language (from uploaded dictionaries)
            - Read from google table
            - Photo echo-message
            - Navigation in bot menu
        """
        @self.bot.callback_query_handler(func=lambda call: True)
        def callback_query(call):
            if call.data == "choose_language":
                language_markup = types.InlineKeyboardMarkup()
                for lang in self.vocabularies.keys():
                    language_markup.add(types.InlineKeyboardButton(lang, callback_data=f"lang_{lang}"))
                language_markup.add(
                    types.InlineKeyboardButton('\N{leftwards arrow with hook} ' +
                        f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][-1]}",
                        callback_data="back"))
                self.bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                           text=f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['headers'][0]}:",
                                           reply_markup=language_markup)
            elif call.data.startswith("lang_"):
                Bot.update_user(call.message.chat.id, 'language', call.data.split("_")[1])
                self.bot.answer_callback_query(call.id, f"{call.data.split('_')[1]}")
            elif call.data == "menu":
                menu_markup = types.InlineKeyboardMarkup()
                menu_markup.add(
                    types.InlineKeyboardButton(
                        f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][2]}",
                        callback_data="photo"),
                    types.InlineKeyboardButton(
                        f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][3]}",
                        url=self.data['maps']),
                    types.InlineKeyboardButton(
                        f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][4]}", url= self.pay_url,
                        callback_data="pay"),
                    types.InlineKeyboardButton(
                        f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][5]}",
                        callback_data="table"),
                    types.InlineKeyboardButton('\N{leftwards arrow with hook} ' +
                                               f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][-1]}",
                                               callback_data="back"))
                self.bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                           text=f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['headers'][1]}:",
                                           reply_markup=menu_markup)
            elif call.data == "back":
                base_markup = types.InlineKeyboardMarkup()
                base_markup.add(types.InlineKeyboardButton('\N{clockwise downwards and upwards open circle arrows} ' +
                                                           self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]][
                                                               'buttons'][0],
                                                           callback_data="choose_language"),
                                types.InlineKeyboardButton(
                                    '\N{clipboard} ' +
                                    self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][
                                        1],
                                    callback_data="menu"))
                self.bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                           text=self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]][
                                               'headers'][2],
                                           reply_markup=base_markup)
            elif call.data == "table":
                table_data = Bot.read_from_table(self.table_sheet)
                menu_markup = types.InlineKeyboardMarkup()
                menu_markup.add(
                    types.InlineKeyboardButton(
                        f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][2]}",
                        callback_data="photo"),
                    types.InlineKeyboardButton(
                        f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][3]}",
                        url=self.data['maps']),
                    types.InlineKeyboardButton(
                        f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][4]}", url= self.pay_url,
                        callback_data="pay"),
                    types.InlineKeyboardButton(
                            f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][5]}",
                            callback_data="table"),
                    types.InlineKeyboardButton('\N{leftwards arrow with hook} ' +
                                            f"{self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]]['buttons'][-1]}",
                                            callback_data="back"))
                self.bot.send_message(chat_id=call.message.chat.id,
                                       text=table_data,
                                       reply_markup=menu_markup)

            elif call.data == "photo":
                self.bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                    text=self.vocabularies[Bot.get_user(call.message.chat.id)[0][3]][
                                    'photo_message'])

    def photo_handler(self):
        """Get user's sent photo, store it in '/data/img/' and send it back
        """
        @self.bot.message_handler(content_types=['photo'])
        def handle_photo(message):
            file_id = message.photo[-1].file_id
            Bot.update_user(message.from_user.id, 'counter', Bot.get_user(message.from_user.id)[0][2] - 1)
            menu_markup = types.InlineKeyboardMarkup()
            menu_markup.add(
                types.InlineKeyboardButton(
                    f"{self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['buttons'][2]}",
                    callback_data="photo"),
                types.InlineKeyboardButton(
                    f"{self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['buttons'][3]}",
                    url=self.data['maps']),
                types.InlineKeyboardButton(
                    f"{self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['buttons'][4]}", url= self.pay_url,
                    callback_data="pay"),
                types.InlineKeyboardButton(
                        f"{self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['buttons'][5]}",
                        callback_data="table"),
                types.InlineKeyboardButton('\N{leftwards arrow with hook} ' +
                                           f"{self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['buttons'][-1]}",
                                           callback_data="back"))
            self.bot.send_photo(message.chat.id, file_id,
                                caption=self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['result_message'])
            self.bot.send_message(chat_id=message.chat.id,
                                       text=f"{self.vocabularies[Bot.get_user(message.chat.id)[0][3]]['headers'][1]}:",
                                       reply_markup=menu_markup)
            file_info = self.bot.get_file(file_id)
            file_url = f"https://api.telegram.org/file/bot{self.data['token']}/{file_info.file_path}"
            response = requests.get(file_url)
            if response.status_code == 200:
                with open("./data/img/received_photo.jpg", "wb") as photo:
                    photo.write(response.content)

    def run(self):
        """Run and 5-sec healthcheck bot
        """
        try:
            self.bot.polling(none_stop=True)
        except requests.exceptions.ConnectionError as err:
            logger.error(err)
            sleep(5)
            self.run()
