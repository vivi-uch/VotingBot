from django.urls import path
from . import views

app_name = 'verification'

urlpatterns = [
    path('capture/<uuid:session_id>/', views.capture_face, name='capture_face'),
    path('api/process-image/<uuid:session_id>/', views.process_image, name='process_image'),
]
