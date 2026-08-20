# extensions.py - общие расширения Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect

# Создаем экземпляры расширений без привязки к приложению
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()  # защита всех POST-форм от CSRF-атак
