import unittest
from s5_nano.context_failures import is_context_limit_response


class ContextFailures(unittest.TestCase):
    def test_only_real_native_context_overflow_qualifies(self):
        body={'error':{'message':"This model's maximum context length is 262144 tokens. However, your prompt contains at least 262145 input tokens."}}
        self.assertTrue(is_context_limit_response(400,body,262144))
        self.assertFalse(is_context_limit_response(400,body,131072))
        for status in [401,429,500,503]:
            self.assertFalse(is_context_limit_response(status,body,262144))
        self.assertFalse(is_context_limit_response(400,{'message':'Invalid model or tool schema'},262144))
        body['error']['message']=body['error']['message'].replace('262145','262143')
        self.assertFalse(is_context_limit_response(400,body,262144))


if __name__=='__main__':unittest.main()
