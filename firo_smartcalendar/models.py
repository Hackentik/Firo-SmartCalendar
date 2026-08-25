# models.py - модели данных для Firo SmartCalendar
from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json


class User(UserMixin, db.Model):
    """
    Модель пользователя системы Firo SmartCalendar

    Хранит информацию о всех пользователях: обычных сотрудниках и администраторах.
    Новые пользователи проходят модерацию администратором перед тем, как смогут войти.
    """
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)  # Уникальный идентификатор
    username = db.Column(db.String(80), unique=True, nullable=False)  # Логин
    email = db.Column(db.String(120), unique=True, nullable=False)  # Электронная почта
    password_hash = db.Column(db.String(200), nullable=False)  # Хеш пароля
    is_admin = db.Column(db.Boolean, default=False)  # Флаг администратора
    # НОВОЕ: статус модерации регистрации - 'pending' (ждёт решения), 'approved' (одобрен),
    # 'rejected' (отклонён/заблокирован администратором)
    approval_status = db.Column(db.String(20), default='pending', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # Дата регистрации

    # Связь с бронированиями (один пользователь может создать много броней)
    bookings = db.relationship('Booking', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        """Устанавливает хеш пароля"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Проверяет соответствие пароля хешу"""
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        """
        НОВОЕ: переопределяет свойство Flask-Login - аккаунт считается активным
        (то есть в него можно войти) только после одобрения администратором.
        """
        return self.approval_status == 'approved'

    def is_pending(self):
        return self.approval_status == 'pending'

    def is_rejected(self):
        return self.approval_status == 'rejected'

    def __repr__(self):
        """Строковое представление для отладки"""
        return f'<User {self.username}>'


class Room(db.Model):
    """
    Модель переговорной комнаты

    Содержит всю информацию о доступных помещениях
    """
    __tablename__ = 'rooms'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # Название комнаты
    capacity = db.Column(db.Integer, nullable=True)  # Вместимость; NULL = без ограничений (актовые залы и т.п.)
    description = db.Column(db.Text)  # Описание, особенности комнаты
    equipment = db.Column(db.String(200))  # Оснащение (проектор, флипчарт, ТВ и т.д.)
    is_active = db.Column(db.Boolean, default=True)  # Активна ли комната
    color = db.Column(db.String(20), default='#FF6B35')  # Цвет комнаты в календаре
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связь с бронированиями (одна комната может быть забронирована много раз)
    bookings = db.relationship('Booking', backref='room', lazy=True, cascade='all, delete-orphan')

    def capacity_label(self):
        """Возвращает читаемое представление вместимости ('12 чел.' или 'Без ограничений')"""
        return f'{self.capacity} чел.' if self.capacity else 'Без ограничений'

    def get_equipment_list(self):
        """Возвращает список оборудования в удобном формате"""
        if self.equipment:
            return [item.strip() for item in self.equipment.split(',') if item.strip()]
        return []

    def is_available(self, start_time, end_time, exclude_booking_id=None):
        """
        Проверяет доступность комнаты в указанный промежуток времени
        exclude_booking_id - ID бронирования, которое нужно исключить из проверки (при редактировании)
        """
        query = Booking.query.filter(
            Booking.room_id == self.id,
            Booking.start_time < end_time,
            Booking.end_time > start_time
        )

        if exclude_booking_id:
            query = query.filter(Booking.id != exclude_booking_id)

        return query.first() is None

    def bookings_for_day(self, day):
        """Возвращает бронирования комнаты на конкретный день (объект date)"""
        day_start = datetime(day.year, day.month, day.day, 0, 0)
        day_end = datetime(day.year, day.month, day.day, 23, 59, 59)
        return Booking.query.filter(
            Booking.room_id == self.id,
            Booking.start_time <= day_end,
            Booking.end_time >= day_start
        ).order_by(Booking.start_time).all()

    def __repr__(self):
        return f'<Room {self.name}>'


class Booking(db.Model):
    """
    Модель бронирования

    Хранит информацию о каждом событии: кто, когда, где и с кем
    """
    __tablename__ = 'bookings'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)  # Название мероприятия/встречи
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)  # Какая комната
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Кто забронировал
    start_time = db.Column(db.DateTime, nullable=False)  # Начало
    end_time = db.Column(db.DateTime, nullable=False)  # Окончание
    participants = db.Column(db.Text)  # Список участников в JSON формате (ID пользователей)
    description = db.Column(db.Text)  # Дополнительное описание, повестка
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # Когда создали бронь

    def get_participants_list(self):
        """Преобразует JSON участников обратно в список ID (строки)"""
        if self.participants:
            try:
                return [p for p in json.loads(self.participants) if p]
            except (ValueError, TypeError):
                return []
        return []

    def get_participants_users(self):
        """
        Возвращает список объектов User для участников встречи (в исходном порядке).
        Раньше в списках бронирований выводились голые ID вместо имён - это исправлено здесь.
        """
        ids = self.get_participants_list()
        if not ids:
            return []
        try:
            int_ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            return []
        users = User.query.filter(User.id.in_(int_ids)).all()
        users_by_id = {u.id: u for u in users}
        return [users_by_id[i] for i in int_ids if i in users_by_id]

    def duration_minutes(self):
        """Возвращает длительность встречи в минутах"""
        delta = self.end_time - self.start_time
        return int(delta.total_seconds() / 60)

    def is_past(self):
        """Проверяет, прошло ли уже мероприятие"""
        return self.end_time < datetime.now()

    def is_ongoing(self):
        """Проверяет, идет ли мероприятие прямо сейчас"""
        now = datetime.now()
        return self.start_time <= now <= self.end_time

    def overcapacity(self):
        """Проверяет, превышает ли число участников вместимость кабинета (для кабинетов без лимита - всегда False)"""
        if not self.room or not self.room.capacity:
            return False
        participants_count = len(self.get_participants_list())
        return participants_count > self.room.capacity

    def __repr__(self):
        return f'<Booking {self.title} at {self.start_time}>'


class Reminder(db.Model):
    """
    НОВОЕ: модель напоминания.

    В отличие от Booking, напоминание не бронирует кабинет и не проверяется
    на конфликт по времени - это просто пометка на календаре ("не забыть про X").
    Кабинет указывать не обязательно (room_id может быть NULL).
    """
    __tablename__ = 'reminders'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)  # О чём напоминание
    description = db.Column(db.Text)  # Подробности
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)  # Кабинет (необязательно)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Кто создал
    start_time = db.Column(db.DateTime, nullable=False)  # На какое время напоминание
    participants = db.Column(db.Text)  # Упомянутые пользователи (JSON со списком ID) - им придёт уведомление
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    room = db.relationship('Room', backref='reminders')
    creator = db.relationship('User', backref='reminders', foreign_keys=[user_id])

    def get_participants_list(self):
        """Список ID упомянутых пользователей (строки), аналогично Booking.get_participants_list"""
        if self.participants:
            try:
                return [p for p in json.loads(self.participants) if p]
            except (ValueError, TypeError):
                return []
        return []

    def get_participants_users(self):
        """Возвращает объекты User для упомянутых участников, в исходном порядке"""
        ids = self.get_participants_list()
        if not ids:
            return []
        try:
            int_ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            return []
        users = User.query.filter(User.id.in_(int_ids)).all()
        users_by_id = {u.id: u for u in users}
        return [users_by_id[i] for i in int_ids if i in users_by_id]

    def is_past(self):
        return self.start_time < datetime.now()

    def __repr__(self):
        return f'<Reminder {self.title} at {self.start_time}>'


class Notification(db.Model):
    """
    НОВОЕ: внутреннее уведомление пользователю - например, "вас упомянули в напоминании".
    Показывается колокольчиком в навигации со счётчиком непрочитанных.
    """
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Кому адресовано
    message = db.Column(db.String(300), nullable=False)  # Текст уведомления
    link_reminder_id = db.Column(db.Integer, db.ForeignKey('reminders.id'), nullable=True)  # Ссылка на напоминание
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='notifications', foreign_keys=[user_id])
    reminder = db.relationship('Reminder', backref=db.backref('notifications', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<Notification for user={self.user_id}: {self.message[:30]}>'
