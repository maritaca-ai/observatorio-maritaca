import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from draco_benchmark.api import Client, rate_limit_delay


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    def test_retry_after_formats_and_invalid_values(self):
        self.assertEqual(rate_limit_delay('150', 0), 150)
        for value in (None, '', 'invalid', 'NaN', 'Infinity', '-1'):
            self.assertEqual(rate_limit_delay(value, 0), 60)
        self.assertEqual(rate_limit_delay(None, 1), 120)
        with patch('draco_benchmark.api.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)
            self.assertEqual(rate_limit_delay('Fri, 06 Nov 2026 18:03:00 GMT', 0), 180)

    async def test_throttling_waits_without_changing_body_or_exposing_auth(self):
        requests = []
        def reply(request):
            requests.append(json.loads(request.content))
            if len(requests) == 1:
                return httpx.Response(429, headers={'Retry-After':'90'}, text='sensitive upstream error')
            return httpx.Response(200, json={'model':'test/model', 'choices':[
                {'finish_reason':'stop', 'message':{'content':'report'}}]})
        client = Client('openrouter', 'test-private-key')
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        try:
            with tempfile.TemporaryDirectory() as directory, patch('draco_benchmark.api.asyncio.sleep') as sleep:
                root = Path(directory)
                result = await client.request('/chat/completions', {'model':'test/model','max_tokens':32768}, root, str)
                self.assertEqual(result[0], 'report')
                sleep.assert_awaited_once_with(90)
                self.assertEqual(requests[0], requests[1])
                records = ''.join(p.read_text() for p in root.glob('*.json'))
                self.assertNotIn('test-private-key', records)
                self.assertNotIn('sensitive upstream error', records)
                self.assertEqual(json.loads((root/'0001.json').read_text())['retry_delay_seconds'], 90)
        finally:
            await client.close()
