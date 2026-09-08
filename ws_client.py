import asyncio
from datetime import datetime
from websockets.asyncio.client import connect

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1IiwiZXhwIjoxNzg4ODU4MDUyfQ.2rwoPRzHsDwqonKuSpcQAJL1dgx_OnVClFQEWdKwmzA"

async def main():
    async with connect(f"ws://localhost:8000/ws?token={TOKEN}") as ws:
        print("connected")
        async for msg in ws:
            print(f"[{datetime.now():%H:%M:%S}] {msg}")

asyncio.run(main())
