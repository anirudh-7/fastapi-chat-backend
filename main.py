from typing import Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import logging
import asyncio

# Logging set to info for debugging during dev
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level = logging.INFO,
)
log = logging.getLogger("chat")
app = FastAPI(title="FastAPI WebSocket Chat")

# CORS - to allow the frontend app to work
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins = origins,
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers = ["*"]
)

# Connection Manager

class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket) -> None:
        #Accept the websocket and store it
        await websocket.accept()
        self.active_connections.add(websocket)
        log.info("Client connected. Active=%d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        log.info("Client disconnected. Active=%d", len(self.active_connections))
    
    async def send_personal_message(self, message: str, websocket: WebSocket) -> None:
        await websocket.send_text(message)

    async def broadcast(self, message:str, exclude: WebSocket | None = None) -> None:
        #Broadcast message to all connected clients.
        #Using asyncio.gather so a slow client doesn't block others
        if not self.active_connections:
            return

        send_tasks = []
        for conn in list(self.active_connections):
            if exclude is not None and conn is exclude:
                continue
            send_tasks.append(conn.send_text(message))
        
        #Shield against single-client failures so one bad socket doesn't crash broadcast
        if send_tasks:
            try:
                await asyncio.gather(*send_tasks, return_exceptions=True)
            except Exception as e:
                log.exception("Broadcast error: %s", e)

manager = ConnectionManager()

# Simple HHTP healthcheck - done for testing

@app.get("/")
def health():
    return {"status": "ok", "clients": len(manager.active_connections)}

#Websocket endpoint

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id:str):
    await manager.connect(websocket)

    try:
        await manager.broadcast(f"Client #{client_id} joined", exclude=None)

        while True:
            data = await websocket.receive_text()
            #Echo back to sender
            await manager.send_personal_message(f"You wrote: {data}", websocket)
            
            #Broadcast to everyone, including sender to match current React behaviour
            await manager.broadcast(f"Client #{client_id} says: {data}", exclude=websocket)
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(f"Client #{client_id} left the chat")
    
    except Exception as e:
        log.exception("Unexpected error: %s", e)
        try:
            await websocket.close()
        finally:
            manager.disconnect(websocket)
            await manager.broadcast(f"Client #{client_id} left the chat(error)")