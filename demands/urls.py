from django.urls import path

from . import views

app_name = "demands"

urlpatterns = [
    path("", views.home, name="home"),
]