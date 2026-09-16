from django.urls import path

from . import views

urlpatterns = [
    path("", views.period_collection, name="fiscal-period-collection"),
    path("<int:pk>/close/", views.period_close, name="fiscal-period-close"),
    path("<int:pk>/reopen/", views.period_reopen, name="fiscal-period-reopen"),
    path("<int:pk>/lock/", views.period_lock, name="fiscal-period-lock"),
    path("<int:pk>/unlock/", views.period_unlock, name="fiscal-period-unlock"),
]
