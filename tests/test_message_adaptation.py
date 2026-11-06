"""Representation changes must preserve every instruction and history turn."""
from copy import deepcopy
import tempfile
import unittest

from s5_nano.message_adaptation import adapt_messages, SYSTEM_TO_USER
from s5_nano.remaining_canary import rendered_history, uses_text_canary
import test_protocol


class MessageAdaptationTests(unittest.TestCase):
    def setUp(self):
        self.profile = dict(message_policy=SYSTEM_TO_USER, history_encoding='reasoning_field')
        self.messages = [dict(role='system', content='  Instrução\n'),
                         dict(role='user', content=' Pergunta '),
                         dict(role='assistant', content='Resposta', reasoning_content='r'),
                         dict(role='user', content='Seguimento')]

    def test_preserves_text_history_and_input_without_double_prefix(self):
        original = deepcopy(self.messages)
        result = adapt_messages(self.messages, self.profile)
        self.assertEqual(result[0]['content'], '  Instrução\n\n\n Pergunta ')
        self.assertEqual(result[1:], original[2:])
        self.assertEqual(self.messages, original)
        self.assertEqual(adapt_messages(result, self.profile), result)
        self.assertEqual(rendered_history(self.messages, self.profile), result)

    def test_default_is_byte_equivalent_and_policy_typo_fails(self):
        self.assertEqual(adapt_messages(self.messages, {}), self.messages)
        with self.assertRaises(ValueError):
            adapt_messages(self.messages, {'message_policy':'typo'})

    def test_rejects_lossy_or_ambiguous_shapes(self):
        for messages in [self.messages[:1], self.messages[1:] + self.messages[:1],
                         self.messages[:1]*2 + self.messages[1:],
                         [dict(role='system', content='x', name='metadata'), self.messages[1]],
                         [dict(role='system', content=[dict(type='text',text='x')]),self.messages[1]],
                         [dict(role='tool',content='x')]]:
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                adapt_messages(messages, self.profile)

    def test_proxy_restores_reasoning_using_original_history_before_folding(self):
        with tempfile.TemporaryDirectory() as folder:
            proxy = test_protocol.ProtocolTests().proxy('instruct', folder)
            proxy.PROFILE.update(self.profile)
            first = self.messages[:2]
            answer = self.messages[2]
            proxy.save_reasoning(first, answer, 'case-a')
            request = dict(model=proxy.MODEL, campaign_benchmark_label='magis_bench',
                           campaign_conversation_id='case-a', messages=first + [
                               dict(role='assistant',content='Resposta'), self.messages[3]])
            effective, counts = proxy.enforce(request)
            self.assertEqual(effective['messages'], adapt_messages(self.messages, self.profile))
            self.assertEqual(counts['reasoning_from_cache'], 1)
            self.assertEqual(counts['folded_system_messages'], 1)
            self.assertEqual(request['messages'][:2], first)
            self.assertEqual(effective['max_tokens'], proxy.PROFILE['max_tokens'])
            with self.assertRaises(ValueError):
                proxy.enforce(dict(request, tools=[{'type':'function'}]))
            with self.assertRaises(proxy.HistoryIntegrityError):
                proxy.enforce(dict(request, campaign_conversation_id='case-b'))

    def test_text_canary_does_not_open_tool_benchmarks(self):
        self.assertTrue(uses_text_canary('enade_qa', 'pt', self.profile))
        self.assertFalse(uses_text_canary('marca_public', 'marca', self.profile))



if __name__ == '__main__':
    unittest.main()
