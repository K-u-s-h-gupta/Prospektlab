import asyncio
import httpx

async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        # We need a token or bypass header.
        headers = {'X-Bypass-Token-Limit': 'true'}
        try:
            resp = await client.post('http://localhost:8000/chat/research', json={'message': 'Infosys vs TCS', 'mode': 'deep'}, headers=headers)
            print("POST Status:", resp.status_code)
        except Exception as e:
            print("Error:", e)

asyncio.run(main())
