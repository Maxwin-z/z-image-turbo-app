"""
WebSocket Connection Manager

Manages WebSocket connections and job subscriptions.
Provides broadcast capabilities to notify subscribers of job updates.
Supports client_id for reconnection with subscription persistence.
"""

from typing import Dict, Set, Any, Optional
from fastapi import WebSocket
import json
import asyncio


class WebSocketManager:
    """
    Manages WebSocket connections and job subscriptions.
    
    Features:
    - Connection lifecycle management
    - Many-to-many relationship between connections and job_ids
    - Broadcast messages to all subscribers of a job_id
    - Client ID support for reconnection with subscription persistence
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # All active WebSocket connections
        self.active_connections: Set[WebSocket] = set()
        
        # client_id -> WebSocket (current active connection for this client)
        self.client_connections: Dict[str, WebSocket] = {}
        
        # WebSocket -> client_id (reverse mapping)
        self.connection_client_ids: Dict[WebSocket, str] = {}
        
        # job_id -> Dict[client_id, request_id (or None)]
        # Using client_id for subscriptions instead of WebSocket for reconnection support
        self.job_subscriptions: Dict[str, Dict[str, Optional[str]]] = {}
        
        # client_id -> Set of job_ids this client is subscribed to
        self.client_subscriptions: Dict[str, Set[str]] = {}
        
        # Event loop reference for thread-safe broadcasts
        self._loop: asyncio.AbstractEventLoop = None
        
        self._initialized = True
    
    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """Set the event loop for thread-safe operations."""
        self._loop = loop
    
    async def connect(self, websocket: WebSocket, client_id: Optional[str] = None):
        """
        Accept and register a new WebSocket connection.
        
        Args:
            websocket: The WebSocket connection
            client_id: Optional client identifier for reconnection support.
                      If provided, subscriptions persist across reconnections.
        """
        await websocket.accept()
        self.active_connections.add(websocket)
        
        if client_id:
            # If this client_id already has an active connection, close the old one
            if client_id in self.client_connections:
                old_ws = self.client_connections[client_id]
                if old_ws in self.active_connections:
                    # Don't clean up subscriptions - just remove the old WebSocket
                    self.active_connections.discard(old_ws)
                    if old_ws in self.connection_client_ids:
                        del self.connection_client_ids[old_ws]
                    try:
                        await old_ws.close()
                    except Exception:
                        pass
            
            # Register new connection with client_id
            self.client_connections[client_id] = websocket
            self.connection_client_ids[websocket] = client_id
            
            # Initialize client subscriptions if needed
            if client_id not in self.client_subscriptions:
                self.client_subscriptions[client_id] = set()
            
            print(f"WS Client connected with client_id: {client_id}")
        else:
            print("WS Client connected without client_id")
    
    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection and clean up its subscriptions."""
        if websocket in self.active_connections:
            self.active_connections.discard(websocket)
        
        client_id = self.connection_client_ids.get(websocket)
        
        if client_id:
            # Remove WebSocket mapping but KEEP subscriptions for reconnection
            if self.client_connections.get(client_id) == websocket:
                del self.client_connections[client_id]
            if websocket in self.connection_client_ids:
                del self.connection_client_ids[websocket]
            print(f"WS Client disconnected (client_id: {client_id}), subscriptions preserved")
        else:
            # No client_id - no subscriptions to preserve
            print("WS Client disconnected (no client_id)")
    
    def subscribe(self, job_id: str, websocket: WebSocket, request_id: Optional[str] = None):
        """Subscribe a WebSocket connection to a job_id."""
        client_id = self.connection_client_ids.get(websocket)
        
        if client_id:
            # Use client_id for subscription
            if job_id not in self.job_subscriptions:
                self.job_subscriptions[job_id] = {}
            self.job_subscriptions[job_id][client_id] = request_id
            
            if client_id in self.client_subscriptions:
                self.client_subscriptions[client_id].add(job_id)
        else:
            # Fallback: use websocket object hash as pseudo client_id
            pseudo_id = f"_ws_{id(websocket)}"
            if job_id not in self.job_subscriptions:
                self.job_subscriptions[job_id] = {}
            self.job_subscriptions[job_id][pseudo_id] = request_id
            
            # Store this pseudo mapping temporarily
            self.connection_client_ids[websocket] = pseudo_id
            self.client_connections[pseudo_id] = websocket
            if pseudo_id not in self.client_subscriptions:
                self.client_subscriptions[pseudo_id] = set()
            self.client_subscriptions[pseudo_id].add(job_id)
    
    def unsubscribe(self, job_id: str, websocket: WebSocket):
        """Unsubscribe a WebSocket connection from a job_id."""
        client_id = self.connection_client_ids.get(websocket)
        
        if client_id and job_id in self.job_subscriptions:
            if client_id in self.job_subscriptions[job_id]:
                del self.job_subscriptions[job_id][client_id]
            if not self.job_subscriptions[job_id]:
                del self.job_subscriptions[job_id]
        
        if client_id and client_id in self.client_subscriptions:
            self.client_subscriptions[client_id].discard(job_id)
    
    async def send_to_connection(self, websocket: WebSocket, message: dict):
        """Send a message to a specific WebSocket connection."""
        try:
            print(f"WS Sending to client: {json.dumps(message)}")
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            print(f"Error sending to WebSocket: {e}")
            self.disconnect(websocket)
    
    async def broadcast_to_job(self, job_id: str, message: dict):
        """
        Broadcast a message to all WebSocket connections subscribed to a job_id.
        """
        if job_id not in self.job_subscriptions:
            return
        
        message_text = json.dumps(message)
        dead_clients = []
        
        for client_id, request_id in self.job_subscriptions[job_id].items():
            websocket = self.client_connections.get(client_id)
            
            if websocket is None:
                # Client is disconnected, skip but don't remove subscription
                # They might reconnect
                print(f"WS Broadcast skipped for client_id={client_id} (disconnected)")
                continue
            
            try:
                # If requester specified request_id, inject into message
                if request_id:
                    # Create a copy to avoid mutating for other subscribers
                    msg_copy = message.copy()
                    msg_copy["request_id"] = request_id
                    print(f"WS Broadcast to client_id={client_id} (req_id={request_id}): {json.dumps(msg_copy)}")
                    await websocket.send_text(json.dumps(msg_copy))
                else:
                    print(f"WS Broadcast to client_id={client_id}: {message_text}")
                    await websocket.send_text(message_text)
            except Exception as e:
                print(f"Error broadcasting to client_id={client_id}: {e}")
                dead_clients.append(client_id)
        
        # Clean up dead connections (but keep subscriptions for potential reconnect)
        for client_id in dead_clients:
            if client_id in self.client_connections:
                ws = self.client_connections[client_id]
                self.active_connections.discard(ws)
                del self.client_connections[client_id]
                if ws in self.connection_client_ids:
                    del self.connection_client_ids[ws]
    
    def broadcast_to_job_threadsafe(self, job_id: str, message: dict):
        """
        Thread-safe version of broadcast_to_job.
        Call this from non-async contexts (e.g., thread pool workers).
        """
        if self._loop is None:
            print("Warning: Event loop not set, cannot broadcast")
            return
        
        asyncio.run_coroutine_threadsafe(
            self.broadcast_to_job(job_id, message),
            self._loop
        )
    
    async def broadcast_all(self, message: dict):
        """Broadcast a message to all active connections."""
        message_text = json.dumps(message)
        dead_connections = []
        
        for websocket in self.active_connections:
            try:
                await websocket.send_text(message_text)
            except Exception as e:
                print(f"Error broadcasting to WebSocket: {e}")
                dead_connections.append(websocket)
        
        for ws in dead_connections:
            self.disconnect(ws)
    
    def get_subscriber_count(self, job_id: str) -> int:
        """Get the number of subscribers for a job_id."""
        return len(self.job_subscriptions.get(job_id, {}))
    
    def get_connection_count(self) -> int:
        """Get the total number of active connections."""
        return len(self.active_connections)
    
    def get_client_id(self, websocket: WebSocket) -> Optional[str]:
        """Get the client_id associated with a WebSocket connection."""
        return self.connection_client_ids.get(websocket)


# Global singleton instance
ws_manager = WebSocketManager()
