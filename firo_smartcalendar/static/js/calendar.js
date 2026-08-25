// calendar.js - общие интерактивные улучшения Firo SmartCalendar

document.addEventListener('DOMContentLoaded', function () {
    // НОВОЕ: flash-уведомления теперь автоматически скрываются через 5 секунд,
    // чтобы не загромождать интерфейс
    document.querySelectorAll('.alert.alert-dismissible').forEach(function (alertEl) {
        setTimeout(function () {
            if (window.bootstrap && window.bootstrap.Alert) {
                const alert = window.bootstrap.Alert.getOrCreateInstance(alertEl);
                alert.close();
            } else {
                alertEl.style.display = 'none';
            }
        }, 5000);
    });

});
