from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/verification/(?P<session_id>[^/]+)/$', consumers.VerificationConsumer.as_asgi()),
]
