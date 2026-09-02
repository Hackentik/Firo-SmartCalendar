# migrate_db.py
"""
Скрипт для миграции старой базы данных Firo SmartCalendar к новой версии.
Сохраняет все существующие данные (пользователи, кабинеты, бронирования).
Запускать ТОЛЬКО на копии базы данных!
"""

import sqlite3
import os
from datetime import datetime
import json

def backup_database(db_path):
    """Создаёт резервную копию базы данных"""
    if not os.path.exists(db_path):
        print(f"❌ База данных не найдена: {db_path}")
        return None
    
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Копируем файл
    import shutil
    shutil.copy2(db_path, backup_path)
    print(f"✅ Резервная копия создана: {backup_path}")
    return backup_path

def migrate_database(db_path):
    """Выполняет миграцию базы данных"""
    
    # 1. Создаём резервную копию
    backup_path = backup_database(db_path)
    if not backup_path:
        return False
    
    # 2. Подключаемся к базе
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # ====== Проверяем существующие таблицы ======
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"📊 Найдены таблицы: {', '.join(tables)}")
        
        # ====== МИГРАЦИЯ 1: Добавляем поле approval_status в users ======
        if 'users' in tables:
            # Проверяем, есть ли колонка approval_status
            cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'approval_status' not in columns:
                print("🔧 Добавляем поле approval_status в таблицу users...")
                # Добавляем колонку с дефолтным значением 'approved' для существующих пользователей
                cursor.execute("ALTER TABLE users ADD COLUMN approval_status VARCHAR(20) DEFAULT 'approved' NOT NULL")
                
                # Если есть админы, они точно должны быть approved
                cursor.execute("UPDATE users SET approval_status = 'approved' WHERE is_admin = 1")
                print("   ✅ Поле approval_status добавлено")
            else:
                print("   ✅ Поле approval_status уже существует")
        
        # ====== МИГРАЦИЯ 2: Добавляем таблицу reminders ======
        if 'reminders' not in tables:
            print("🔧 Создаём таблицу reminders...")
            cursor.execute("""
                CREATE TABLE reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title VARCHAR(200) NOT NULL,
                    description TEXT,
                    room_id INTEGER,
                    user_id INTEGER NOT NULL,
                    start_time DATETIME NOT NULL,
                    participants TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(room_id) REFERENCES rooms(id),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
            """)
            print("   ✅ Таблица reminders создана")
        else:
            print("   ✅ Таблица reminders уже существует")
        
        # ====== МИГРАЦИЯ 3: Добавляем таблицу notifications ======
        if 'notifications' not in tables:
            print("🔧 Создаём таблицу notifications...")
            cursor.execute("""
                CREATE TABLE notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    message VARCHAR(300) NOT NULL,
                    link_reminder_id INTEGER,
                    link_booking_id INTEGER,
                    is_read BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(link_reminder_id) REFERENCES reminders(id),
                    FOREIGN KEY(link_booking_id) REFERENCES bookings(id)
                )
            """)
            print("   ✅ Таблица notifications создана")
        else:
            print("   ✅ Таблица notifications уже существует")
        
        # ====== МИГРАЦИЯ 4: Проверяем поле capacity в rooms ======
        if 'rooms' in tables:
            cursor.execute("PRAGMA table_info(rooms)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # В старой версии capacity мог быть NOT NULL
            # Нужно проверить и исправить если нужно
            if 'capacity' in columns:
                # Проверяем, есть ли записи с capacity = 0 или NULL
                cursor.execute("SELECT id, capacity FROM rooms")
                rooms = cursor.fetchall()
                
                for room_id, capacity in rooms:
                    if capacity == 0:
                        # В новой версии 0 означает "без ограничений" → превращаем в NULL
                        cursor.execute("UPDATE rooms SET capacity = NULL WHERE id = ?", (room_id,))
                        print(f"   🔄 Кабинет #{room_id}: вместимость 0 → NULL (без ограничений)")
                
                print("   ✅ Поле capacity проверено")
            else:
                print("   ⚠️ Поле capacity не найдено в таблице rooms")
        
        # ====== МИГРАЦИЯ 5: Добавляем индексы для производительности ======
        print("🔧 Создаём индексы...")
        
        # Индексы для bookings
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_room_id ON bookings(room_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user_id ON bookings(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_start_time ON bookings(start_time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_end_time ON bookings(end_time)")
        
        # Индексы для reminders
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_id ON reminders(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_start_time ON reminders(start_time)")
        
        # Индексы для notifications
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read)")
        
        print("   ✅ Индексы созданы")
        
        # ====== ФИКС: Проверяем, что у всех существующих пользователей есть approval_status ======
        # Если были добавлены пользователи до миграции, у них может быть NULL
        cursor.execute("UPDATE users SET approval_status = 'approved' WHERE approval_status IS NULL")
        
        # Сохраняем изменения
        conn.commit()
        
        # ====== ИТОГ ======
        print("\n" + "="*50)
        print("✅ МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА!")
        print("="*50)
        
        # Показываем статистику
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM rooms")
        rooms_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM bookings")
        bookings_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM reminders")
        reminders_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM notifications")
        notifications_count = cursor.fetchone()[0]
        
        print(f"📊 Статистика:")
        print(f"   👤 Пользователей: {users_count}")
        print(f"   🏢 Кабинетов: {rooms_count}")
        print(f"   📅 Бронирований: {bookings_count}")
        print(f"   🔔 Напоминаний: {reminders_count}")
        print(f"   📬 Уведомлений: {notifications_count}")
        print("="*50)
        
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Ошибка при миграции: {e}")
        print(f"💡 Восстановите базу из резервной копии: {backup_path}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    # Путь к базе данных
    db_path = "firo_calendar.db"
    
    # Проверяем, существует ли база
    if not os.path.exists(db_path):
        print(f"❌ Файл базы данных не найден: {db_path}")
        print("💡 Если база называется по-другому, укажите путь вручную:")
        print("   python migrate_db.py /path/to/your/database.db")
        exit(1)
    
    print("="*50)
    print("🔄 Firo SmartCalendar - Миграция базы данных")
    print("="*50)
    print(f"📁 База данных: {db_path}")
    print()
    print("⚠️  ПЕРЕД ЗАПУСКОМ убедитесь, что:")
    print("   1. Приложение НЕ запущено")
    print("   2. У вас есть резервная копия (будет создана автоматически)")
    print()
    
    response = input("Продолжить миграцию? (y/N): ")
    if response.lower() != 'y':
        print("❌ Миграция отменена")
        exit(0)
    
    # Запускаем миграцию
    success = migrate_database(db_path)
    
    if success:
        print("\n🎉 Теперь можно запускать приложение!")
        print("   python app.py")
    else:
        print("\n❌ Миграция не удалась. Проверьте резервную копию.")