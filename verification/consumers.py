import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from bot.models import VerificationSession

logger = logging.getLogger(__name__)

class VerificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.group_name = f'verification_{self.session_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Check if session exists
        session_exists = await self.check_session_exists()
        if not session_exists:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Session not found'
            }))
            await self.close()
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'status_update':
                # Update session status
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        'type': 'status_update',
                        'status': data.get('status'),
                        'message': data.get('message')
                    }
                )
        except Exception as e:
            logger.error(f"Error in websocket receive: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))
    
    async def status_update(self, event):
        # Send status update to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'status': event['status'],
            'message': event['message']
        }))
    
    @database_sync_to_async
    def check_session_exists(self):
        try:
            return VerificationSession.objects.filter(id=self.session_id).exists()
        except Exception:
            return False
