# app.py - главный файл приложения Firo SmartCalendar
# Система для удобного бронирования кабинетов
# Цветовая схема: оранжевый (#FF6B35) - основной цвет
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta
import calendar
from functools import wraps
import json
import os

# Импортируем расширения
from extensions import db, login_manager, csrf

# Импортируем модели
from models import User, Room, Booking, Reminder, Notification

# Создаем приложение Flask
app = Flask(__name__)

# === НАСТРОЙКИ ПРИЛОЖЕНИЯ ===
# ИСПРАВЛЕНО: секретный ключ больше не хранится в коде в открытом виде.
# Для продакшена задайте переменную окружения FIRO_SECRET_KEY.
# Ключ по умолчанию используется только для локальной разработки.
app.config['SECRET_KEY'] = os.environ.get('FIRO_SECRET_KEY', 'dev-only-change-me-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'FIRO_DATABASE_URI', 'sqlite:///firo_calendar.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['FIRO_ORANGE'] = '#FF6B35'

# Рабочие часы календаря (используются в недельном виде и на главной)
WORK_HOUR_START = 8
WORK_HOUR_END = 20

# Инициализируем расширения с приложением
db.init_app(app)
login_manager.init_app(app)
csrf.init_app(app)  # ИСПРАВЛЕНО: включена CSRF-защита для всех форм с методом POST
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите в систему Firo SmartCalendar'
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    """Загружает пользователя по ID для Flask-Login"""
    return User.query.get(int(user_id))


@app.context_processor
def inject_pending_count():
    """
    НОВОЕ: для администратора в навигации показываем, сколько заявок на регистрацию
    ждут решения - чтобы не забыть про них.
    """
    if current_user.is_authenticated and current_user.is_admin:
        count = User.query.filter_by(approval_status='pending').count()
        return {'pending_registrations_count': count}
    return {'pending_registrations_count': 0}


@app.context_processor
def inject_notifications():
    """
    НОВОЕ: колокольчик в навигации - непрочитанные уведомления текущего пользователя
    (например, "вас упомянули в напоминании"), плюс несколько последних для выпадающего списка.
    """
    if current_user.is_authenticated:
        unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        recent = Notification.query.filter_by(user_id=current_user.id) \
            .order_by(Notification.created_at.desc()).limit(5).all()
        return {'unread_notifications_count': unread_count, 'recent_notifications': recent}
    return {'unread_notifications_count': 0, 'recent_notifications': []}


def admin_required(f):
    """Проверяет, является ли текущий пользователь администратором"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Для доступа к этой странице нужно войти в систему', 'warning')
            return redirect(url_for('login'))
        if not current_user.is_admin:
            flash('Эта страница доступна только администраторам Firo', 'danger')
            return redirect(url_for('calendar_view'))
        return f(*args, **kwargs)
    return decorated_function


def parse_datetime_local(value):
    """Безопасно парсит значение поля datetime-local, возвращает None при ошибке"""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M')
    except ValueError:
        return None


# === МАРШРУТЫ ДЛЯ АВТОРИЗАЦИИ ===

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация нового пользователя в системе Firo"""
    if current_user.is_authenticated:
        return redirect(url_for('calendar_view'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()  # ИСПРАВЛЕНО: email нормализуется
        password = request.form.get('password', '')

        if not username or not email or not password:
            flash('Заполните все обязательные поля', 'danger')
            return redirect(url_for('register'))

        # ИСПРАВЛЕНО: минимальная длина пароля теперь проверяется и на сервере, а не только в подсказке
        if len(password) < 6:
            flash('Пароль должен содержать минимум 6 символов', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Это имя пользователя уже занято. Придумайте другое!', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Этот email уже зарегистрирован в системе', 'danger')
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.set_password(password)

        # НОВОЕ: первый пользователь становится администратором и одобряется автоматически,
        # все последующие регистрации ждут решения администратора
        if User.query.count() == 0:
            user.is_admin = True
            user.approval_status = 'approved'
            db.session.add(user)
            db.session.commit()
            flash('Поздравляем! Вы стали первым администратором Firo SmartCalendar. Теперь можно войти', 'success')
            return redirect(url_for('login'))

        user.approval_status = 'pending'
        db.session.add(user)
        db.session.commit()

        flash(
            'Заявка на регистрацию отправлена! Вход будет доступен после того, '
            'как администратор подтвердит вашу учётную запись', 'info'
        )
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Вход в систему Firo SmartCalendar"""
    if current_user.is_authenticated:
        return redirect(url_for('calendar_view'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            flash('Неверный логин или пароль. Попробуйте снова', 'danger')
            return redirect(url_for('login'))

        # НОВОЕ: пользователи, которых ещё не одобрил (или отклонил) администратор,
        # не могут войти в систему, даже зная верный пароль
        if user.is_pending():
            flash(
                'Ваша заявка на регистрацию ещё не рассмотрена администратором. '
                'Попробуйте зайти немного позже', 'warning'
            )
            return redirect(url_for('login'))

        if user.is_rejected():
            flash('Ваша учётная запись заблокирована администратором', 'danger')
            return redirect(url_for('login'))

        login_user(user, remember=remember)

        next_page = request.args.get('next')
        flash(f'С возвращением, {user.username}! Добро пожаловать в Firo SmartCalendar', 'success')
        return redirect(next_page) if next_page else redirect(url_for('calendar_view'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    """Выход из системы"""
    logout_user()
    flash('Вы вышли из системы Firo SmartCalendar', 'info')
    return redirect(url_for('login'))


# === ОСНОВНЫЕ МАРШРУТЫ КАЛЕНДАРЯ ===

@app.route('/')
def index():
    """Главная страница - перенаправляем на календарь"""
    return redirect(url_for('calendar_view'))


@app.route('/calendar')
@login_required
def calendar_view():
    """Отображает календарь в месячном или недельном формате"""
    view = request.args.get('view', 'month')
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

    try:
        current_date = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        current_date = datetime.now()

    rooms = Room.query.filter_by(is_active=True).all()

    if view == 'week':
        return show_week_calendar(current_date, rooms)
    else:
        return show_month_calendar(current_date, rooms)


def _free_rooms_right_now(rooms):
    """НОВОЕ: считает сколько кабинетов свободно прямо сейчас - используется в виджете календаря"""
    now = datetime.now()
    free = 0
    for room in rooms:
        if room.is_available(now, now + timedelta(minutes=1)):
            free += 1
    return free


def show_month_calendar(current_date, rooms):
    """Показывает календарь на месяц"""
    cal = calendar.Calendar(firstweekday=0)  # неделя начинается с понедельника
    month_weeks = cal.monthdayscalendar(current_date.year, current_date.month)

    start_of_month = datetime(current_date.year, current_date.month, 1)
    if current_date.month == 12:
        end_of_month = datetime(current_date.year + 1, 1, 1) - timedelta(seconds=1)
    else:
        end_of_month = datetime(current_date.year, current_date.month + 1, 1) - timedelta(seconds=1)

    month_bookings = Booking.query.filter(
        Booking.start_time <= end_of_month,
        Booking.end_time >= start_of_month
    ).order_by(Booking.start_time).all()

    # НОВОЕ: напоминания за месяц - показываем на календаре вместе с бронями,
    # но отдельным значком (колокольчик), так как это не бронирование кабинета
    month_reminders = Reminder.query.filter(
        Reminder.start_time >= start_of_month,
        Reminder.start_time <= end_of_month
    ).order_by(Reminder.start_time).all()

    # Объединяем брони и напоминания в единый список событий по дням, отсортированный по времени
    day_items = {}
    for booking in month_bookings:
        day_key = booking.start_time.day
        day_items.setdefault(day_key, []).append({'kind': 'booking', 'obj': booking, 'time': booking.start_time})
    for reminder in month_reminders:
        day_key = reminder.start_time.day
        day_items.setdefault(day_key, []).append({'kind': 'reminder', 'obj': reminder, 'time': reminder.start_time})
    for day_key in day_items:
        day_items[day_key].sort(key=lambda item: item['time'])

    # Навигация по месяцам вперед/назад
    prev_month_date = (start_of_month - timedelta(days=1)).replace(day=1)
    next_month_date = (end_of_month + timedelta(seconds=1))

    russian_months = [
        '', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
        'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
    ]

    return render_template('calendar/month.html',
                            month_weeks=month_weeks,
                            current_date=current_date,
                            month_name=russian_months[current_date.month],
                            year=current_date.year,
                            rooms=rooms,
                            day_items=day_items,
                            prev_month_date=prev_month_date,
                            next_month_date=next_month_date,
                            free_rooms_now=_free_rooms_right_now(rooms),
                            now=datetime.now())


def _booking_layout(booking, day, work_start, work_end):
    """
    НОВОЕ: считает вертикальное положение блока (брони или напоминания) в сетке недели
    (в процентах от рабочего диапазона часов), обрезая его границами дня и рабочих часов.
    """
    day_start_hour = work_start
    day_end_hour = work_end
    total = day_end_hour - day_start_hour

    start_hour = booking.start_time.hour + booking.start_time.minute / 60
    end_hour = booking.end_time.hour + booking.end_time.minute / 60

    # если бронь начинается до полуночи текущего дня или заканчивается после - обрезаем визуально
    if booking.start_time.date() < day:
        start_hour = day_start_hour
    if booking.end_time.date() > day:
        end_hour = day_end_hour

    start_hour = max(day_start_hour, min(start_hour, day_end_hour))
    end_hour = max(day_start_hour, min(end_hour, day_end_hour))

    top_pct = ((start_hour - day_start_hour) / total) * 100 if total else 0
    height_pct = max(((end_hour - start_hour) / total) * 100, 2) if total else 0

    return {'booking': booking, 'top_pct': round(top_pct, 1), 'height_pct': round(height_pct, 1)}


def _reminder_layout(reminder, day, work_start, work_end):
    """НОВОЕ: то же самое, что _booking_layout, но для напоминаний - у них нет времени окончания,
    поэтому визуально отображаем их как короткий 30-минутный блок."""

    class _FakeSpan:
        """Обёртка, чтобы напоминание можно было передать в _booking_layout как если бы у него было end_time"""
        def __init__(self, start_time, end_time):
            self.start_time = start_time
            self.end_time = end_time

    span = _FakeSpan(reminder.start_time, reminder.start_time + timedelta(minutes=30))
    layout = _booking_layout(span, day, work_start, work_end)
    layout['reminder'] = reminder
    del layout['booking']
    return layout


def show_week_calendar(current_date, rooms):
    """Показывает календарь на неделю"""
    start_of_week = current_date - timedelta(days=current_date.weekday())

    week_days = []
    for i in range(7):
        day = start_of_week + timedelta(days=i)

        day_start = datetime(day.year, day.month, day.day, 0, 0)
        day_end = datetime(day.year, day.month, day.day, 23, 59, 59)

        day_bookings = Booking.query.filter(
            Booking.start_time <= day_end,
            Booking.end_time >= day_start
        ).order_by(Booking.start_time).all()

        # НОВОЕ: напоминания за этот день недели
        day_reminders = Reminder.query.filter(
            Reminder.start_time >= day_start,
            Reminder.start_time <= day_end
        ).order_by(Reminder.start_time).all()

        booking_layouts = [_booking_layout(b, day.date(), WORK_HOUR_START, WORK_HOUR_END) for b in day_bookings]
        reminder_layouts = [_reminder_layout(r, day.date(), WORK_HOUR_START, WORK_HOUR_END) for r in day_reminders]

        week_days.append({
            'date': day,
            'bookings': day_bookings,
            'booking_layouts': booking_layouts,
            'reminder_layouts': reminder_layouts,
            'is_today': day.date() == datetime.now().date()
        })

    time_slots = [f"{hour:02d}:00" for hour in range(WORK_HOUR_START, WORK_HOUR_END + 1)]

    return render_template('calendar/week.html',
                            week_days=week_days,
                            current_date=current_date,
                            rooms=rooms,
                            time_slots=time_slots,
                            work_hour_start=WORK_HOUR_START,
                            work_hour_end=WORK_HOUR_END,
                            prev_week_date=start_of_week - timedelta(days=7),
                            next_week_date=start_of_week + timedelta(days=7),
                            free_rooms_now=_free_rooms_right_now(rooms),
                            now=datetime.now())


@app.route('/rooms')
@login_required
def rooms_directory():
    """
    НОВОЕ: публичный каталог кабинетов, доступный всем пользователям (не только админам) -
    вместимость, оборудование и кнопка быстрого бронирования конкретного кабинета.
    """
    rooms = Room.query.filter_by(is_active=True).order_by(Room.name).all()
    return render_template('rooms_directory.html', rooms=rooms, free_rooms_now=_free_rooms_right_now(rooms))


@app.route('/booking/<int:booking_id>/export.ics')
@login_required
def export_booking_ics(booking_id):
    """
    НОВОЕ: скачивание бронирования в формате .ics, чтобы добавить встречу
    в Outlook, Google Calendar, Apple Calendar и т.д.
    """
    booking = Booking.query.get_or_404(booking_id)

    if booking.user_id != current_user.id and not current_user.is_admin:
        flash('Вы можете скачать только свои бронирования', 'danger')
        return redirect(url_for('bookings_list'))

    def fmt(dt):
        return dt.strftime('%Y%m%dT%H%M%S')

    def escape_ics(text):
        return (text or '').replace('\\', '\\\\').replace(',', '\\,').replace(';', '\\;').replace('\n', '\\n')

    ics_lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Firo SmartCalendar//RU',
        'CALSCALE:GREGORIAN',
        'BEGIN:VEVENT',
        f'UID:firo-booking-{booking.id}@smartcalendar',
        f'DTSTAMP:{fmt(datetime.utcnow())}Z',
        f'DTSTART:{fmt(booking.start_time)}',
        f'DTEND:{fmt(booking.end_time)}',
        f'SUMMARY:{escape_ics(booking.title)}',
        f'LOCATION:{escape_ics(booking.room.name)}',
        f'DESCRIPTION:{escape_ics(booking.description or "")}',
        'END:VEVENT',
        'END:VCALENDAR',
    ]
    ics_content = '\r\n'.join(ics_lines)

    response = app.response_class(ics_content, mimetype='text/calendar')
    response.headers['Content-Disposition'] = f'attachment; filename=booking-{booking.id}.ics'
    return response


# === МАРШРУТЫ ДЛЯ БРОНИРОВАНИЯ ===

@app.route('/bookings')
@login_required
def bookings_list():
    """Список всех бронирований"""
    if current_user.is_admin:
        bookings = Booking.query.order_by(Booking.start_time.desc()).all()
    else:
        bookings = Booking.query.filter_by(user_id=current_user.id) \
            .order_by(Booking.start_time.desc()).all()

    return render_template('bookings/list.html', bookings=bookings)


@app.route('/booking/new', methods=['GET', 'POST'])
@login_required
def new_booking():
    """Создание нового бронирования"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        room_id = request.form.get('room_id')
        start_time = parse_datetime_local(request.form.get('start_time'))
        end_time = parse_datetime_local(request.form.get('end_time'))
        description = request.form.get('description', '').strip()
        participants = [p for p in request.form.getlist('participants[]') if p]

        # ИСПРАВЛЕНО: проверка обязательных полей до обращения к БД,
        # чтобы не получить необработанное исключение при пустой форме
        if not title or not room_id or not start_time or not end_time:
            flash('Заполните все обязательные поля бронирования', 'danger')
            return redirect(url_for('new_booking'))

        # ИСПРАВЛЕНО: проверка порядка времени выполняется ПЕРЕД проверкой занятости
        # (раньше сначала шёл дорогой запрос на конфликт, и только потом валидация времени)
        if end_time <= start_time:
            flash('Время окончания должно быть позже времени начала', 'danger')
            return redirect(url_for('new_booking'))

        room = Room.query.get(room_id)
        if not room or not room.is_active:
            flash('Выбранный кабинет недоступен для бронирования', 'danger')
            return redirect(url_for('new_booking'))

        # Проверяем, не занято ли это время
        conflict = Booking.query.filter(
            Booking.room_id == room_id,
            Booking.start_time < end_time,
            Booking.end_time > start_time
        ).first()

        if conflict:
            flash('Извините, это время уже занято. Выберите другое время', 'warning')
            return redirect(url_for('new_booking'))

        try:
            booking = Booking(
                title=title,
                room_id=room_id,
                user_id=current_user.id,
                start_time=start_time,
                end_time=end_time,
                participants=json.dumps(participants, ensure_ascii=False),
                description=description
            )

            db.session.add(booking)
            db.session.commit()

            # НОВОЕ: предупреждаем, если участников больше, чем вместимость кабинета
            if booking.overcapacity():
                flash(
                    f'Внимание: участников больше вместимости кабинета '
                    f'({len(participants)} чел. в кабинете на {room.capacity})', 'warning'
                )

            flash(f'Отлично! Кабинет забронирован на {start_time.strftime("%d.%m.%Y %H:%M")}', 'success')
            return redirect(url_for('calendar_view'))

        except Exception as e:
            db.session.rollback()
            flash(f'Что-то пошло не так: {str(e)}', 'danger')
            return redirect(url_for('new_booking'))

    # GET запрос - показываем форму
    rooms = Room.query.filter_by(is_active=True).all()
    users = User.query.order_by(User.username).all()

    now = datetime.now()
    # НОВОЕ: если переход был из календаря по конкретному дню, подставляем эту дату
    date_param = request.args.get('date')
    preset_date = None
    if date_param:
        try:
            preset_date = datetime.strptime(date_param, '%Y-%m-%d')
        except ValueError:
            preset_date = None

    if preset_date:
        start_default = preset_date.replace(hour=9, minute=0, second=0, microsecond=0)
    elif now.hour < WORK_HOUR_END:
        start_default = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        tomorrow = now + timedelta(days=1)
        start_default = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 9, 0)

    end_default = start_default + timedelta(hours=1)

    return render_template('bookings/new.html',
                            rooms=rooms,
                            users=users,
                            start_default=start_default.strftime('%Y-%m-%dT%H:%M'),
                            end_default=end_default.strftime('%Y-%m-%dT%H:%M'))


@app.route('/booking/<int:booking_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_booking(booking_id):
    """Редактирование существующего бронирования"""
    booking = Booking.query.get_or_404(booking_id)

    if booking.user_id != current_user.id and not current_user.is_admin:
        flash('Это бронирование может редактировать только его создатель или администратор', 'danger')
        return redirect(url_for('calendar_view'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        room_id = request.form.get('room_id')
        start_time = parse_datetime_local(request.form.get('start_time'))
        end_time = parse_datetime_local(request.form.get('end_time'))
        description = request.form.get('description', '').strip()
        participants = [p for p in request.form.getlist('participants[]') if p]

        if not title or not room_id or not start_time or not end_time:
            flash('Заполните все обязательные поля бронирования', 'danger')
            return redirect(url_for('edit_booking', booking_id=booking_id))

        if end_time <= start_time:
            flash('Время окончания должно быть позже времени начала', 'danger')
            return redirect(url_for('edit_booking', booking_id=booking_id))

        conflict = Booking.query.filter(
            Booking.room_id == room_id,
            Booking.id != booking_id,
            Booking.start_time < end_time,
            Booking.end_time > start_time
        ).first()

        if conflict:
            flash('Это время уже занято другим мероприятием', 'warning')
            return redirect(url_for('edit_booking', booking_id=booking_id))

        try:
            booking.title = title
            booking.room_id = room_id
            booking.start_time = start_time
            booking.end_time = end_time
            booking.participants = json.dumps(participants, ensure_ascii=False)
            booking.description = description

            db.session.commit()

            if booking.overcapacity():
                flash('Внимание: участников больше, чем вместимость выбранного кабинета', 'warning')

            flash('Бронирование успешно обновлено!', 'success')
            return redirect(url_for('calendar_view'))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при обновлении: {str(e)}', 'danger')

    rooms = Room.query.filter_by(is_active=True).all()
    users = User.query.order_by(User.username).all()
    participants_list = booking.get_participants_list()

    return render_template('bookings/edit.html',
                            booking=booking,
                            rooms=rooms,
                            users=users,
                            participants_list=participants_list)


@app.route('/booking/<int:booking_id>/delete', methods=['POST'])
@login_required
def delete_booking(booking_id):
    """Удаление бронирования"""
    booking = Booking.query.get_or_404(booking_id)

    if booking.user_id != current_user.id and not current_user.is_admin:
        flash('У вас нет прав на удаление этого бронирования', 'danger')
        return redirect(url_for('calendar_view'))

    try:
        room_name = booking.room.name
        booking_time = booking.start_time.strftime('%d.%m.%Y %H:%M')

        db.session.delete(booking)
        db.session.commit()

        flash(f'Бронирование кабинета "{room_name}" на {booking_time} удалено', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('bookings_list'))


# === НАПОМИНАНИЯ (не бронирование кабинета, просто пометка на календаре) ===

@app.route('/reminders')
@login_required
def reminders_list():
    """Список напоминаний: свои созданные + те, где тебя упомянули (админ видит все)"""
    if current_user.is_admin:
        reminders = Reminder.query.order_by(Reminder.start_time.desc()).all()
    else:
        all_reminders = Reminder.query.order_by(Reminder.start_time.desc()).all()
        # Показываем те, что создал сам пользователь, или где он в участниках
        reminders = [
            r for r in all_reminders
            if r.user_id == current_user.id or str(current_user.id) in r.get_participants_list()
        ]

    return render_template('reminders/list.html', reminders=reminders)


@app.route('/reminder/new', methods=['GET', 'POST'])
@login_required
def new_reminder():
    """Создание напоминания - кабинет указывать не обязательно"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        room_id = request.form.get('room_id') or None  # НОВОЕ: кабинет необязателен
        start_time = parse_datetime_local(request.form.get('start_time'))
        participants = [p for p in request.form.getlist('participants[]') if p]

        if not title or not start_time:
            flash('Укажите название и время напоминания', 'danger')
            return redirect(url_for('new_reminder'))

        if room_id:
            room = Room.query.get(room_id)
            if not room or not room.is_active:
                flash('Выбранный кабинет недоступен', 'danger')
                return redirect(url_for('new_reminder'))

        try:
            reminder = Reminder(
                title=title,
                description=description,
                room_id=room_id,
                user_id=current_user.id,
                start_time=start_time,
                participants=json.dumps(participants, ensure_ascii=False)
            )
            db.session.add(reminder)
            db.session.commit()

            # НОВОЕ: упомянутым участникам приходит внутреннее уведомление (колокольчик в навигации)
            _notify_participants(reminder, participants)

            flash(f'Напоминание «{title}» создано на {start_time.strftime("%d.%m.%Y %H:%M")}', 'success')
            return redirect(url_for('reminders_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Что-то пошло не так: {str(e)}', 'danger')
            return redirect(url_for('new_reminder'))

    rooms = Room.query.filter_by(is_active=True).all()
    users = User.query.filter_by(approval_status='approved').order_by(User.username).all()
    now = datetime.now()
    start_default = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))

    return render_template('reminders/new.html', rooms=rooms, users=users,
                            start_default=start_default.strftime('%Y-%m-%dT%H:%M'))


@app.route('/reminder/<int:reminder_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_reminder(reminder_id):
    """Редактирование напоминания"""
    reminder = Reminder.query.get_or_404(reminder_id)

    if reminder.user_id != current_user.id and not current_user.is_admin:
        flash('Редактировать напоминание может только его автор или администратор', 'danger')
        return redirect(url_for('reminders_list'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        room_id = request.form.get('room_id') or None
        start_time = parse_datetime_local(request.form.get('start_time'))
        new_participants = [p for p in request.form.getlist('participants[]') if p]

        if not title or not start_time:
            flash('Укажите название и время напоминания', 'danger')
            return redirect(url_for('edit_reminder', reminder_id=reminder_id))

        old_participants = set(reminder.get_participants_list())

        try:
            reminder.title = title
            reminder.description = description
            reminder.room_id = room_id
            reminder.start_time = start_time
            reminder.participants = json.dumps(new_participants, ensure_ascii=False)
            db.session.commit()

            # НОВОЕ: уведомляем только тех, кого добавили заново - чтобы не спамить остальных при каждом сохранении
            newly_added = [p for p in new_participants if p not in old_participants]
            _notify_participants(reminder, newly_added)

            flash('Напоминание обновлено', 'success')
            return redirect(url_for('reminders_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при обновлении: {str(e)}', 'danger')

    rooms = Room.query.filter_by(is_active=True).all()
    users = User.query.filter_by(approval_status='approved').order_by(User.username).all()
    participants_list = reminder.get_participants_list()

    return render_template('reminders/edit.html', reminder=reminder, rooms=rooms, users=users,
                            participants_list=participants_list)


@app.route('/reminder/<int:reminder_id>/delete', methods=['POST'])
@login_required
def delete_reminder(reminder_id):
    """Удаление напоминания"""
    reminder = Reminder.query.get_or_404(reminder_id)

    if reminder.user_id != current_user.id and not current_user.is_admin:
        flash('У вас нет прав на удаление этого напоминания', 'danger')
        return redirect(url_for('reminders_list'))

    try:
        title = reminder.title
        db.session.delete(reminder)
        db.session.commit()
        flash(f'Напоминание «{title}» удалено', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('reminders_list'))


def _notify_participants(reminder, participant_ids):
    """НОВОЕ: создаёт внутренние уведомления для упомянутых в напоминании пользователей"""
    if not participant_ids:
        return
    try:
        int_ids = [int(p) for p in participant_ids]
    except (TypeError, ValueError):
        return

    for uid in int_ids:
        if uid == reminder.user_id:
            continue  # не уведомляем автора о его собственном напоминании
        notification = Notification(
            user_id=uid,
            message=f'{reminder.creator.username} упомянул(а) вас в напоминании «{reminder.title}» '
                     f'на {reminder.start_time.strftime("%d.%m.%Y %H:%M")}',
            link_reminder_id=reminder.id
        )
        db.session.add(notification)
    db.session.commit()


# === УВЕДОМЛЕНИЯ ===

@app.route('/notifications')
@login_required
def notifications_list():
    """Список уведомлений текущего пользователя"""
    notifications = Notification.query.filter_by(user_id=current_user.id) \
        .order_by(Notification.created_at.desc()).all()
    return render_template('notifications.html', notifications=notifications)


@app.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """Отмечает одно уведомление как прочитанное"""
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id != current_user.id:
        flash('Это не ваше уведомление', 'danger')
        return redirect(url_for('notifications_list'))

    notification.is_read = True
    db.session.commit()
    return redirect(request.referrer or url_for('notifications_list'))


@app.route('/notifications/mark_all_read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    """Отмечает все уведомления пользователя как прочитанные"""
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    flash('Все уведомления отмечены как прочитанные', 'success')
    return redirect(request.referrer or url_for('notifications_list'))


@app.route('/api/notifications/unread_count')
@login_required
def api_unread_notifications_count():
    """
    НОВОЕ: лёгкий API-эндпоинт для колокольчика в навигации - JS опрашивает его раз в 30 секунд,
    чтобы счётчик непрочитанных обновлялся без перезагрузки страницы.
    """
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'unread_count': count})


# === АДМИНИСТРАТИВНЫЕ МАРШРУТЫ ===

@app.route('/admin/rooms')
@login_required
@admin_required
def admin_rooms():
    """Управление кабинетами (только для админов)"""
    rooms = Room.query.order_by(Room.name).all()
    # ИСПРАВЛЕНО: считаем вместимость здесь, а не через rooms|sum(attribute='capacity') в шаблоне -
    # у кабинетов без ограничений capacity = None, и стандартный фильтр sum упал бы с ошибкой
    total_capacity = sum(r.capacity for r in rooms if r.capacity)
    unlimited_rooms_count = sum(1 for r in rooms if not r.capacity)
    return render_template('admin/rooms.html', rooms=rooms, total_capacity=total_capacity,
                            unlimited_rooms_count=unlimited_rooms_count)


@app.route('/admin/rooms/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_room():
    """Добавление нового кабинета"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        unlimited = 'unlimited_capacity' in request.form
        capacity_raw = request.form.get('capacity', '').strip()
        color = request.form.get('color', '#FF6B35')

        if not name:
            flash('Укажите название кабинета', 'danger')
            return redirect(url_for('new_room'))

        # НОВОЕ: вместимость можно не ограничивать (актовые залы и т.п.),
        # а для обычных кабинетов допускается до 9999 человек
        capacity = None
        if not unlimited:
            try:
                capacity = int(capacity_raw)
                if capacity < 1 or capacity > 9999:
                    raise ValueError
            except (ValueError, TypeError):
                flash('Вместимость должна быть числом от 1 до 9999 (или отметьте "без ограничений")', 'danger')
                return redirect(url_for('new_room'))

        room = Room(
            name=name,
            capacity=capacity,
            description=request.form.get('description', '').strip(),
            equipment=request.form.get('equipment', '').strip(),
            color=color,
            is_active=True
        )

        db.session.add(room)
        db.session.commit()

        flash(f'Кабинет "{room.name}" успешно добавлен в систему!', 'success')
        return redirect(url_for('admin_rooms'))

    return render_template('admin/new_room.html')


@app.route('/admin/rooms/<int:room_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_room(room_id):
    """Редактирование кабинета"""
    room = Room.query.get_or_404(room_id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        unlimited = 'unlimited_capacity' in request.form
        capacity_raw = request.form.get('capacity', '').strip()

        if not name:
            flash('Укажите название кабинета', 'danger')
            return redirect(url_for('edit_room', room_id=room_id))

        capacity = None
        if not unlimited:
            try:
                capacity = int(capacity_raw)
                if capacity < 1 or capacity > 9999:
                    raise ValueError
            except (ValueError, TypeError):
                flash('Вместимость должна быть числом от 1 до 9999 (или отметьте "без ограничений")', 'danger')
                return redirect(url_for('edit_room', room_id=room_id))

        room.name = name
        room.capacity = capacity
        room.description = request.form.get('description', '').strip()
        room.equipment = request.form.get('equipment', '').strip()
        room.color = request.form.get('color', room.color)
        room.is_active = 'is_active' in request.form

        db.session.commit()

        flash(f'Информация о кабинете "{room.name}" обновлена', 'success')
        return redirect(url_for('admin_rooms'))

    # ИСПРАВЛЕНО: раньше в шаблон не передавалась переменная `now`,
    # хотя edit_room.html использует её для поиска ближайшего будущего бронирования -
    # это приводило к ошибке при открытии страницы редактирования кабинета
    return render_template('admin/edit_room.html', room=room, now=datetime.now())


@app.route('/admin/rooms/<int:room_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_room(room_id):
    """Включение/отключение кабинета (мягкое удаление)"""
    room = Room.query.get_or_404(room_id)

    if room.is_active:
        future_bookings = Booking.query.filter(
            Booking.room_id == room_id,
            Booking.start_time > datetime.now()
        ).first()

        if future_bookings:
            flash('Нельзя удалить кабинет с будущими бронированиями. Сначала отмените их', 'danger')
            return redirect(url_for('admin_rooms'))

        room.is_active = False
        flash(f'Кабинет "{room.name}" деактивирован', 'success')
    else:
        room.is_active = True
        flash(f'Кабинет "{room.name}" снова активен', 'success')

    db.session.commit()
    return redirect(url_for('admin_rooms'))


@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    """Управление пользователями"""
    # НОВОЕ: заявки, ожидающие решения, показываем первыми - чтобы админ сразу их видел
    users = User.query.order_by(
        db.case((User.approval_status == 'pending', 0), else_=1),
        User.username
    ).all()
    total_bookings = sum(len(u.bookings) for u in users)
    pending_count = sum(1 for u in users if u.is_pending())
    return render_template('admin/users.html', users=users, total_bookings=total_bookings,
                            pending_count=pending_count)


@app.route('/admin/users/<int:user_id>/toggle_admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    """Изменение прав администратора для пользователя"""
    if user_id == current_user.id:
        flash('Нельзя изменить свои собственные права администратора', 'danger')
        return redirect(url_for('admin_users'))

    user = User.query.get_or_404(user_id)
    user.is_admin = not user.is_admin

    db.session.commit()

    status = 'назначен администратором' if user.is_admin else 'лишен прав администратора'
    flash(f'Пользователь {user.username} {status}', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_user(user_id):
    """НОВОЕ: одобрение заявки на регистрацию - после этого пользователь сможет войти"""
    user = User.query.get_or_404(user_id)
    user.approval_status = 'approved'
    db.session.commit()
    flash(f'Регистрация пользователя {user.username} подтверждена', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_user(user_id):
    """НОВОЕ: отклонение заявки на регистрацию или блокировка уже одобренного пользователя"""
    if user_id == current_user.id:
        flash('Нельзя заблокировать самого себя', 'danger')
        return redirect(url_for('admin_users'))

    user = User.query.get_or_404(user_id)
    user.approval_status = 'rejected'
    db.session.commit()
    flash(f'Пользователю {user.username} отказано в доступе', 'warning')
    return redirect(url_for('admin_users'))


# === API ДЛЯ AJAX ЗАПРОСОВ ===

@app.route('/api/check_availability')
@login_required
def check_availability():
    """Проверка доступности кабинета на выбранное время (для AJAX)"""
    room_id = request.args.get('room_id')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    booking_id = request.args.get('booking_id')

    if not all([room_id, start_time, end_time]):
        return jsonify({'available': False, 'error': 'Не все параметры указаны'})

    start = parse_datetime_local(start_time)
    end = parse_datetime_local(end_time)

    if not start or not end:
        return jsonify({'available': False, 'error': 'Некорректный формат времени'})

    if end <= start:
        return jsonify({'available': False, 'message': 'Время окончания должно быть позже времени начала'})

    query = Booking.query.filter(
        Booking.room_id == room_id,
        Booking.start_time < end,
        Booking.end_time > start
    )

    if booking_id:
        query = query.filter(Booking.id != booking_id)

    conflict = query.first()

    if conflict:
        return jsonify({
            'available': False,
            'message': f'Это время занято: {conflict.title}'
        })

    return jsonify({'available': True})


@app.route('/api/room_bookings/<int:room_id>')
@login_required
def room_bookings(room_id):
    """Получение всех бронирований кабинета (для AJAX)"""
    date_str = request.args.get('date')

    if date_str:
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Некорректная дата'}), 400
        start_of_day = datetime(date.year, date.month, date.day, 0, 0)
        end_of_day = datetime(date.year, date.month, date.day, 23, 59, 59)

        bookings = Booking.query.filter(
            Booking.room_id == room_id,
            Booking.start_time <= end_of_day,
            Booking.end_time >= start_of_day
        ).order_by(Booking.start_time).all()
    else:
        bookings = Booking.query.filter_by(room_id=room_id).order_by(Booking.start_time).all()

    bookings_data = [{
        'id': b.id,
        'title': b.title,
        'start': b.start_time.strftime('%Y-%m-%d %H:%M'),
        'end': b.end_time.strftime('%Y-%m-%d %H:%M'),
        'user': b.user.username,
        'description': b.description
    } for b in bookings]

    return jsonify(bookings_data)


@app.route('/api/find_available_rooms')
@login_required
def find_available_rooms():
    """
    НОВОЕ: поиск свободных кабинетов на заданный промежуток времени с фильтром по вместимости.
    Используется на форме создания бронирования, чтобы быстро понять, какие кабинеты свободны.
    """
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    min_capacity = request.args.get('min_capacity', 0)

    start = parse_datetime_local(start_time)
    end = parse_datetime_local(end_time)

    if not start or not end or end <= start:
        return jsonify({'error': 'Укажите корректный промежуток времени'}), 400

    try:
        min_capacity = int(min_capacity)
    except (ValueError, TypeError):
        min_capacity = 0

    # Кабинеты без ограничений (capacity is None) подходят под любой фильтр по вместимости
    rooms = Room.query.filter(
        Room.is_active == True,  # noqa: E712
        db.or_(Room.capacity == None, Room.capacity >= min_capacity)  # noqa: E711
    ).all()
    available = [r for r in rooms if r.is_available(start, end)]

    return jsonify([{
        'id': r.id,
        'name': r.name,
        'capacity': r.capacity,
        'capacity_label': r.capacity_label(),
        'equipment': r.get_equipment_list()
    } for r in available])


# Создаем базу данных при первом запуске
with app.app_context():
    db.create_all()
    print(" База данных Firo SmartCalendar готова к работе!")

if __name__ == '__main__':
    # ИСПРАВЛЕНО: без host='0.0.0.0' Flask слушает только 127.0.0.1 (localhost) -
    # приложение недоступно снаружи сервера, даже если порт открыт в файрволе.
    # debug=True тоже небезопасно оставлять в продакшене - выключаем через переменную окружения.
    debug_mode = os.environ.get('FIRO_DEBUG', 'false').lower() == 'true'
    port = int(os.environ.get('FIRO_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
