import asyncio
import httpx

async def main():
    async with httpx.AsyncClient(timeout=300) as client:
        # We need a token or bypass header.
        headers = {'X-Bypass-Token-Limit': 'true'}
        try:
            resp = await client.post('http://localhost:8000/chat/research', json={'message': 'Infosys vs TCS', 'mode': 'standard'}, headers=headers)
            print("POST Status:", resp.status_code)
            print("POST Response:", resp.text)
            
            data = resp.json()
            session_id = data.get('session_id')
            if not session_id:
                return
            
            # Now stream events
            async with client.stream('GET', f"http://localhost:8000/sessions/{session_id}/stream", headers=headers) as stream:
                async for chunk in stream.aiter_text():
                    print("SSE:", chunk)
        except Exception as e:
            print("Error:", e)

asyncio.run(main())
