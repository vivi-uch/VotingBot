from django.urls import path
from . import views

app_name = 'bot'

urlpatterns = [
    path('webhook/', views.webhook, name='webhook'),
    path('session/<uuid:session_id>/result/', views.session_result, name='session_result'),
    path('session/<uuid:session_id>/update/', views.update_session, name='update_session'),
]
