from django.urls import path

from . import views

app_name = "demands"

urlpatterns = [
    path("", views.home, name="home"),
    path(
        "requirements/<int:pk>/",
        views.requirement_detail,
        name="requirement_detail",
    ),
    path(
        "requirements/<int:pk>/start/",
        views.requirement_start,
        name="requirement_start",
    ),
    path(
        "requirements/<int:pk>/edit/",
        views.requirement_edit,
        name="requirement_edit",
    ),
    path(
        "requirements/<int:pk>/submit/",
        views.requirement_submit,
        name="requirement_submit",
    ),
    path(
        "requirements/<int:pk>/review/",
        views.requirement_review,
        name="requirement_review",
    ),
    path(
        "attachments/<int:pk>/download/",
        views.attachment_download,
        name="attachment_download",
    ),
]
