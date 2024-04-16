#!/usr/bin/env python3

from datetime import datetime
import datetime as dt
import telebot
import psycopg2
from telebot import types


def get_token(token_filename):
    with open(token_filename, 'r') as file:
        content = file.read()
        return content


def get_db_connection(config_filename):
    dbname = ""
    options = ""
    with open(config_filename, 'r') as file:
        lines = file.readlines()
        for line in lines:
            # check if string present on a current line
            if line.find("dbname=") != -1:
                idx = line.find("=")
                dbname = line[idx + 1:]
            elif line.find("options=") != -1:
                idx = line.find("=")
                options = line[idx + 1:]
    if dbname == "":
        raise ConnectionError("Database name is unspecified.")
    return psycopg2.connect("dbname=" + dbname, options=options)


# Define the Telegram bot token
TELEGRAM_TOKEN = get_token("token.txt")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Set up the connection to the PostgreSQL database
connection = get_db_connection("dbconfig.txt")

class User:
    def __init__(self, db_id, name, role, tg_id):
        self.db_id = db_id
        self.name = name
        self.role = role
        self.tg_id = tg_id


class Drink:
    def __init__(self, db_id, name, price):
        self.db_id = db_id
        self.name = name
        self.price = price


class Order:
    def __init__(self, db_id, cust_id, timestamp, drink, price, status_id, pickup_time):
        cur = connection.cursor()
        self.db_id = db_id
        self.timestamp = timestamp
        self.cust_id = cust_id
        self.drink = drink
        self.price = price
        cur.execute("SELECT name FROM order_status WHERE id = " + str(status_id) + ";")
        self.status = cur.fetchone()[0]
        self.pickup_time = pickup_time


def get_barista_id():
    cur = connection.cursor()
    cur.execute("SELECT tg_id FROM users WHERE role_id = " + str(2) + ";")
    barista_id = cur.fetchone()[0]
    return barista_id


def round_to_nearest_minute(time_str):
    time = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    minutes = round(time.minute / 1.0) * 1.0
    rounded_time = time.replace(minute=int(minutes), second=0)
    return rounded_time.strftime('%Y-%m-%d %H:%M')


def get_customer_info(db_id):
    cur = connection.cursor()
    cur.execute("SELECT id,name,role_id,tg_id from users WHERE id = " + str(db_id) + ";")
    info = cur.fetchone()
    return User(info[0], info[1], info[2], info[3])


def get_user_info(object_id):
    cur = connection.cursor()
    user_id = str(object_id)
    cur.execute("SELECT id,name,role_id,tg_id FROM users WHERE tg_id = '" + user_id + "';")
    res = cur.fetchone()
    if res is None:
        return None
    else:
        cur.execute("SELECT name FROM roles WHERE id = '" + str(res[2]) + "';")
        role = cur.fetchone()
        if role is None:
            req = "DELETE FROM users WHERE tg_id = '" + user_id + "';"
            cur.execute(req)
            connection.commit()
            return None
        else:
            return User(res[0], res[1], role[0], res[3])


def show_barista_orders(barista):
    cur = connection.cursor()
    cur.execute("SELECT id,user_id,timestamp,drink,price,status_id,pickup_time FROM orders WHERE status_id < 4;")
    markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    markup.add("Обновить список заказов")
    order_db = cur.fetchone()
    if order_db is None:
        msg_text = "Нет актвиных заказов."
    else:
        msg_text = "Актвиные заказы:\n"

    while order_db is not None:
        order = Order(order_db[0], order_db[1], order_db[2], order_db[3], order_db[4], order_db[5], order_db[6])
        customer = get_customer_info(order.cust_id)
        order_dsc = "\nЗаказ №" + str(order.db_id) + "\n" \
                    "Время заказа: " + order.timestamp.strftime('%Y-%m-%d %H:%M') + "\n" \
                    "Время получения: " + str(order.pickup_time) + "\n" \
                    "Имя клиента: " + str(customer.name) + "\n" \
                    "Напиток: " + str(order.drink) + "\n" \
                    "Цена: " + str(order.price) + "₽\n" \
                    "Статус: " + str(order.status) + "\n"
        msg_text += order_dsc
        if order.status == "Принят":
            markup.add("Пометить готовым заказ №" + str(order.db_id))
        elif order.status == "Готов":
            markup.add("Пометить выданным заказ №" + str(order.db_id))
        markup.add("Отменить заказ №" + str(order.db_id))
        order_db = cur.fetchone()
    return bot.send_message(barista.tg_id, msg_text, reply_markup=markup)


def barista_menu_handler(message):
    cur = connection.cursor()
    chat_id = message.chat.id
    barista = get_user_info(chat_id)
    opt = message.text
    try:
        if opt == "Обновить список заказов":
            msg = launch_menu(barista)
            bot.register_next_step_handler(msg, barista_menu_handler)
            return
        if "Отменить" in opt:
            pos = opt.find('№') + 1
            order_id = opt[pos:]

            cur.execute("SELECT users.tg_id,users.name FROM orders JOIN users ON orders.user_id = users.id "
                        "WHERE orders.id = " + str(order_id) + ";")
            user_data = cur.fetchone()
            user_tg_id, user_name = user_data[0], user_data[1]
            cur.execute("SELECT id,user_id,timestamp,drink,price,status_id,pickup_time FROM orders WHERE "
                        "id = " + str(order_id) + ";")
            order_db = cur.fetchone()

            if order_db is None:
                bot.send_message(barista.tg_id, "Детали заказа не найдены.")
                msg = launch_menu(barista)
                return msg

            order = Order(order_db[0], order_db[1], order_db[2], order_db[3], order_db[4], order_db[5], order_db[6])

            if order.status == "Отменен":
                bot.send_message(barista.tg_id, "Действие невозможно. Заказ уже отменён.")
                msg = launch_menu(barista)
                return msg

            cur.execute("UPDATE orders SET status_id = 5 WHERE id = " + str(order_id) + ";")
            connection.commit()

            order_dsc = "Время заказа: " + order.timestamp.strftime('%Y-%m-%d %H:%M') + "\n" \
                        "Время получения: " + str(order.pickup_time) + "\n" \
                        "Напиток: " + str(order.drink) + "\n" \
                        "Цена: " + str(order.price) + "₽\n" \
                        "Имя клиента: " + str(user_name)
            barista_msg = "Заказ №" + str(order_id) + " отменен.\n\nДетали заказа:\n" + order_dsc
            user_msg = "Заказ №" + str(order_id) + " отменен бариста.\n\nДетали заказа:\n" + order_dsc
            bot.send_message(chat_id, barista_msg)
            bot.send_message(user_tg_id, user_msg)
            msg = show_barista_orders(barista)
            bot.register_next_step_handler(msg, barista_menu_handler)
        elif "готов" in opt:
            pos = opt.find('№') + 1
            order_id = opt[pos:]
            cur.execute("SELECT id,user_id,timestamp,drink,price,status_id,pickup_time FROM orders WHERE "
                        "id = " + str(order_id) + ";")
            order_db = cur.fetchone()

            if order_db is None:
                bot.send_message(barista.tg_id, "Детали заказа не найдены.")
                msg = launch_menu(barista)
                return msg

            order = Order(order_db[0], order_db[1], order_db[2], order_db[3], order_db[4], order_db[5], order_db[6])

            if order.status == "Отменен":
                bot.send_message(barista.tg_id, "Действие невозможно. Заказ уже отменён.")
                msg = launch_menu(barista)
                return msg

            elif order.status == "Готов":
                bot.send_message(barista.tg_id, "Действие невозможно. Заказ уже помечен готовым.")
                msg = launch_menu(barista)
                return msg

            elif order.status == "Получен":
                bot.send_message(barista.tg_id, "Действие невозможно. Заказ уже выдан клиенту.")
                msg = launch_menu(barista)
                return msg

            cur.execute("UPDATE orders SET status_id = 3 WHERE id = " + str(order_id) + ";")
            connection.commit()
            cur.execute("SELECT users.tg_id FROM orders JOIN users ON orders.user_id = users.id "
                        "WHERE orders.id = " + str(order_id) + ";")
            user_data = cur.fetchone()
            user_tg_id = user_data[0]
            bot.send_message(user_tg_id, "Заказ №" + str(order_id) + " готов к выдаче.")
            bot.send_message(chat_id, "Заказ №" + str(order_id) + " готов к выдаче.")
            msg = show_barista_orders(barista)
            bot.register_next_step_handler(msg, barista_menu_handler)
        elif "выдан" in opt:
            pos = opt.find('№') + 1
            order_id = opt[pos:]
            cur.execute("SELECT id,user_id,timestamp,drink,price,status_id,pickup_time FROM orders WHERE "
                        "id = " + str(order_id) + ";")
            order_db = cur.fetchone()

            if order_db is None:
                bot.send_message(barista.tg_id, "Детали заказа не найдены.")
                msg = launch_menu(barista)
                return msg

            order = Order(order_db[0], order_db[1], order_db[2], order_db[3], order_db[4], order_db[5], order_db[6])

            if order.status == "Отменен":
                bot.send_message(barista.tg_id, "Действие невозможно. Заказ уже отменён.")
                msg = launch_menu(barista)
                return msg

            elif order.status == "Получен":
                bot.send_message(barista.tg_id, "Действие невозможно. Заказ уже выдан клиенту.")
                msg = launch_menu(barista)
                return msg

            cur.execute("UPDATE orders SET status_id = 4 WHERE id = " + str(order_id) + ";")
            connection.commit()
            cur.execute("SELECT users.tg_id FROM orders JOIN users ON orders.user_id = users.id "
                        "WHERE orders.id = " + str(order_id) + ";")
            user_data = cur.fetchone()
            user_tg_id = user_data[0]
            bot.send_message(user_tg_id, "Заказ №" + str(order_id) + " выдан клиенту.")
            bot.send_message(chat_id, "Заказ №" + str(order_id) + " выдан клиенту.")
            msg = show_barista_orders(barista)
            bot.register_next_step_handler(msg, barista_menu_handler)
        else:
            bot.send_message(barista.tg_id, "Нет такой команды. Попробуйте еще раз.")
            msg = launch_menu(barista)
            bot.register_next_step_handler(msg, barista_menu_handler)
    except Exception as e:
        bot.send_message(barista.tg_id, 'Что-то пошло не так. Попробуйте ещё раз.')
        print(e)
        msg = launch_menu(barista)
        bot.register_next_step_handler(msg, barista_menu_handler)


def launch_menu(user):
    msg = None
    if user.role == "admin":
        msg = bot.send_message(user.tg_id, "Добро пожаловать в бот In-Time Coffee!\nЭтот функционал пока в разработке.")
    elif user.role == "barista":
        msg = show_barista_orders(user)
    elif user.role == "customer":
        markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True)
        markup.add('Заказать напиток', 'Активные заказы', "Связь с бариста")
        msg = bot.send_message(user.tg_id, "Главное меню", reply_markup=markup)
    else:
        raise Exception("Invalid user role")
    return msg


def register_name_handler(message):
    try:
        cur = connection.cursor()
        chat_id = message.chat.id
        name = message.text

        cur.execute("INSERT INTO users (name,tg_id,role_id) "
                    "VALUES ('" + str(name) + "', '"
                    + str(chat_id) + "', 3);")

        msg = bot.reply_to(message, "Спасибо! Теперь введите Ваш номер телефона или нажмите /skip, "
                                    "чтобы пропустить этот шаг.")
        bot.register_next_step_handler(msg, register_loyalty_handler)

    except Exception as e:
        bot.reply_to(message, 'Что-то пошло не так. Попробуйте ещё раз: /register.')


def register_loyalty_handler(message):
    try:
        cur = connection.cursor()
        chat_id = message.chat.id
        loyalty = message.text
        if not loyalty == '/skip':
            if loyalty.isdigit():
                cur.execute("UPDATE users "
                            "SET phone_num = '" + str(loyalty) + "' "
                                                               "WHERE tg_id = '" + str(chat_id) + "';")
            else:
                msg = bot.reply_to(message, "Неверный номер телефона. Попробуйте ещё раз.")
                bot.register_next_step_handler(msg, register_loyalty_handler)

        cur.execute("SELECT name,phone_num FROM users WHERE tg_id = '" + str(chat_id) + "';")
        res = cur.fetchone()
        markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True)
        markup.add('Верно', 'Неверно')
        msg = bot.reply_to(message, "Спасибо! Пожалуйста подтвердите Ваши данные.\n"
                                    "Имя: " + str(res[0]) + "\n"
                                                            "Номер телефона: " + str(res[1]),
                           reply_markup=markup)
        bot.register_next_step_handler(msg, register_confirmaion_handler)

    except Exception as e:
        bot.reply_to(message, 'Что-то пошло не так. Попробуйте ещё раз: /register.')
        print(e)


def register_confirmaion_handler(message):
    chat_id = message.chat.id
    conf = message.text
    if conf == "Верно":
        connection.commit()
        bot.send_message(chat_id, "Спасибо! Регистрация завершена."
                                  "\nНажмите /menu для перехода в главное меню.")

    else:
        connection.rollback()
        bot.send_message(chat_id, "Данные сброшены. Попробуйте ещё раз: /register.")


def show_drinks(chat_id):
    cur = connection.cursor()
    markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    cur.execute("SELECT id,name,price FROM drinks;")
    option = cur.fetchone()
    while option is not None:
        drink = Drink(option[0], option[1], option[2])
        markup.add(str(drink.name) + ' - ' + str(drink.price) + '₽')
        option = cur.fetchone()
    return bot.send_message(chat_id, "Выберете напиток", reply_markup=markup)


def get_order_handler(message):
    timestamp = datetime.now()
    cur = connection.cursor()
    chat_id = message.chat.id
    user = get_user_info(chat_id)
    order = message.text
    hif_ind = order.find('-')
    if hif_ind == -1:
        bot.send_message(chat_id, "Некорректный заказ. Попробуйте ещё раз.")
        menu_msg = launch_menu(user)
        bot.register_next_step_handler(menu_msg, customer_menu_handler)
        return
    hif_ind -= 1
    order = order[:hif_ind]
    cur.execute("SELECT id,name,price FROM drinks WHERE name = '" + str(order) + "';")
    drink_db = cur.fetchone()
    if drink_db is None:
        bot.send_message("Некорректный заказ")
        menu_msg = launch_menu(user)
        bot.register_next_step_handler(menu_msg, customer_menu_handler)
        return
    drink = Drink(drink_db[0], drink_db[1], drink_db[2])
    markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    markup.add('Сейчас', 'Через 15 минут', 'Через 30 минут', 'Через час')
    msg = bot.send_message(chat_id,
                           "Введите время, когда вы хотите забрать заказ, или выберите один из предложенных вариантов.",
                           reply_markup=markup)
    bot.register_next_step_handler(msg, order_time_handler, user, timestamp, drink)


def order_time_handler(message, user, timestamp, drink):
    cur = connection.cursor()
    chat_id = message.chat.id
    user_time = message.text
    if user_time == 'Сейчас':
        pickup_time = timestamp.strftime('%Y-%m-%d %H:%M')
    elif user_time == 'Через 15 минут':
        pickup_time = (timestamp + dt.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M')
    elif user_time == 'Через 30 минут':
        pickup_time = (timestamp + dt.timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M')
    elif user_time == 'Через час':
        pickup_time = (timestamp + dt.timedelta(minutes=60)).strftime('%Y-%m-%d %H:%M')
    else:
        pickup_time = user_time

    cur.execute("INSERT INTO orders "
                "(user_id,timestamp,drink,price,status_id,pickup_time)"
                "VALUES (" + str(user.db_id) + ",'" + str(timestamp) +
                "','" + str(drink.name) + "'," + str(drink.price) + ",1,'"
                + pickup_time + "');")
    markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True)
    markup.add('Подтвердить', 'Отменить')
    drink_dsc = "Напиток: " + str(drink.name) + "\n" + "Цена: " + str(drink.price) + "₽\n" + "Время получения: " + pickup_time
    msg = bot.send_message(chat_id, "Спасибо! Пожалуста, подтвердите Ваш заказ:\n" + drink_dsc, reply_markup=markup)
    bot.register_next_step_handler(msg, order_conf_handler, drink_dsc, user)


def order_conf_handler(message, drink_dsc, user):
    chat_id = message.chat.id
    barista_id = get_barista_id()
    conf = message.text
    if conf == "Подтвердить":
        connection.commit()
        bot.send_message(chat_id, "Спасибо! Ваш заказ принят.")
        bot.send_message(barista_id, "Получен новый заказ:\n" + drink_dsc + "\nИмя клиента: " + user.name)
    else:
        connection.rollback()
        bot.send_message(chat_id, "Данные сброшены.")
    msg = launch_menu(get_user_info(chat_id))
    bot.register_next_step_handler(msg, customer_menu_handler)


def show_active_orders(user):
    cur = connection.cursor()
    cur.execute("SELECT id,user_id,timestamp,drink,price,status_id,pickup_time FROM orders WHERE "
                "user_id = " + str(user.db_id) + " AND status_id < 4;")
    order_db = cur.fetchone()
    if order_db is None:
        bot.send_message(user.tg_id, "У Вас нет активных заказов.")
        msg = launch_menu(user)
        return msg

    markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    markup.add("Назад в меню")
    msg_text = "Ваши активные заказы:\n"

    while order_db is not None:
        order = Order(order_db[0], order_db[1], order_db[2], order_db[3], order_db[4], order_db[5], order_db[6])
        order_dsc = "\nЗаказ №" + str(order.db_id) + "\n" \
                    "Время заказа: " + order.timestamp.strftime('%Y-%m-%d %H:%M') + "\n" \
                    "Время получения: " + str(order.pickup_time) + "\n" \
                    "Напиток: " + str(order.drink) + "\n" \
                    "Цена: " + str(order.price) + "₽\n" \
                    "Статус: " + str(order.status) + "\n"
        msg_text += order_dsc
        markup.add("Отменить заказ №" + str(order.db_id))
        order_db = cur.fetchone()
    msg = bot.send_message(user.tg_id, msg_text, reply_markup=markup)
    return msg


def order_list_reply_handler(message):
    cur = connection.cursor()
    chat_id = message.chat.id
    user = get_user_info(chat_id)
    barista_id = get_barista_id()
    opt = message.text
    if opt == "Назад в меню":
        msg = launch_menu(user)
        bot.register_next_step_handler(msg, customer_menu_handler)
        return
    if "Отменить" in opt:
        pos = opt.find('№') + 1
        order_id = opt[pos:]

        cur.execute("SELECT id,user_id,timestamp,drink,price,status_id,pickup_time FROM orders WHERE "
                    "id = " + str(order_id) + ";")
        order_db = cur.fetchone()
        if order_db is None:
            bot.send_message(user.tg_id, "Детали заказа не найдены.")
            msg = launch_menu(user)
            return msg
        order = Order(order_db[0], order_db[1], order_db[2], order_db[3], order_db[4], order_db[5], order_db[6])

        if order.status == "Отменен":
            bot.send_message(chat_id, "Действие невозможно. Заказ уже отменён.")
            msg = show_active_orders(user)
            if "Главное меню" in msg.text:
                bot.register_next_step_handler(msg, customer_menu_handler)
            else:
                bot.register_next_step_handler(msg, order_list_reply_handler)
            return

        elif order.status == "Получен":
            bot.send_message(chat_id, "Действие невозможно. Заказ уже выдан клиенту.")
            msg = show_active_orders(user)
            if "Главное меню" in msg.text:
                bot.register_next_step_handler(msg, customer_menu_handler)
            else:
                bot.register_next_step_handler(msg, order_list_reply_handler)
            return

        cur.execute("UPDATE orders SET status_id = 5 WHERE id = " + str(order_id) + ";")
        connection.commit()

        order_dsc = "Время заказа: " + order.timestamp.strftime('%Y-%m-%d %H:%M') + "\n" \
                    "Время получения: " + str(order.pickup_time) + "\n" \
                    "Напиток: " + str(order.drink) + "\n" \
                    "Цена: " + str(order.price) + "₽\n" \
                    "Имя клиента: " + str(user.name)
        info_msg = "Заказ №" + str(order_id) + " отменен.\n\nДетали заказа:\n" + order_dsc
        bot.send_message(chat_id, info_msg)
        bot.send_message(barista_id, info_msg)
        msg = show_active_orders(user)
        if "Главное меню" in msg.text:
            bot.register_next_step_handler(msg, customer_menu_handler)
        else:
            bot.register_next_step_handler(msg, order_list_reply_handler)
    else:
        bot.send_message(chat_id, "Некорректная команда.")
        msg = show_active_orders(user)
        if "Главное меню" in msg.text:
            bot.register_next_step_handler(msg, customer_menu_handler)
        else:
            bot.register_next_step_handler(msg, order_list_reply_handler)


def customer_menu_handler(message):
    chat_id = message.chat.id
    opt = message.text
    user = get_user_info(chat_id)
    if opt == "Заказать напиток":
        msg = show_drinks(chat_id)
        bot.register_next_step_handler(msg, get_order_handler)
    elif opt == "Активные заказы":
        msg = show_active_orders(user)
        if "Главное меню" in msg.text:
            bot.register_next_step_handler(msg, customer_menu_handler)
        else:
            bot.register_next_step_handler(msg, order_list_reply_handler)
    elif opt == "Связь с бариста":
        info_message = "Вы можете связаться с нами по телефону 88888888888 или через Telegram @CoffeeTestTg."
        bot.send_message(chat_id, info_message)
        msg = launch_menu(user)
        bot.register_next_step_handler(msg, customer_menu_handler)
    else:
        bot.send_message(chat_id, "Нет такой функции")
        msg = launch_menu(user)
        bot.register_next_step_handler(msg, customer_menu_handler)


@bot.message_handler(commands=['menu'])
def send_menu_message(message):
    chat_id = message.chat.id
    user = get_user_info(chat_id)
    msg = launch_menu(user)
    if user.role == "customer":
        bot.register_next_step_handler(msg, customer_menu_handler)
    elif user.role == "barista":
        bot.register_next_step_handler(msg, barista_menu_handler)


@bot.message_handler(commands=['help'])
def send_info_message(message):
    bot.send_message(message.chat.id,
                     "С нашим ботом Вы сможете заказывать Ваши любимые напитки заранее и не тратить время на ожидание.\n"
                     "Чтобы начать пользоваться ботом, нажмите /start.\n"
                     "Телефон для связи с кофейней: 888888888888.")


@bot.message_handler(commands=['register'])
def register_user(message):
    chat_id = message.chat.id
    user = get_user_info(chat_id)
    if user is not None:
        bot.send_message(chat_id, "Вы уже зарегистрированы. Перейдите в /menu, чтобы начать пользоваться ботом.")
        return

    msg = bot.send_message(chat_id,
                           "Как мы можем к Вам обращаться?")
    bot.register_next_step_handler(msg, register_name_handler)


@bot.message_handler(func=lambda m: True)
def start_messaging(message):
    chat_id = message.chat.id
    user = get_user_info(chat_id)
    if user is None:
        bot.send_message(chat_id, "Добро пожаловать в бот In-Time Coffee!"
                                  "\nНажмите /register, чтобы зарегистрироваться и оформить заказ."
                                  "\nНажмите /help, чтобы узнать больше о возможностях бота.")
    else:
        if message.text != "/start":
            bot.send_message(chat_id, "Не удалось обработать запрос. Попрбуйте ещё раз.")
        else:
            bot.send_message(chat_id, "Рады видеть Вас снова, " + user.name)
        msg = launch_menu(user)
        if user.role == "customer":
            bot.register_next_step_handler(msg, customer_menu_handler)
        elif user.role == "barista":
            bot.register_next_step_handler(msg, barista_menu_handler)


if __name__ == '__main__':
    print("Bot started")
    bot.infinity_polling()
