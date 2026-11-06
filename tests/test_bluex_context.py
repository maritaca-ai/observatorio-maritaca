import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from s5_nano.bluex_context import generate

class ContextTests(unittest.TestCase):
 def client(self,create):return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
 def test_context_failure_is_not_retried_or_truncated(self):
  error=RuntimeError('context');error.status_code=400;error.body={'new_model_call':False,'error':{'message':'Input exceeds the native model context length','context_length':4096}}
  call=Mock(side_effect=error);prompt='Earlier answer and next subquestion'
  row=generate(self.client(call),'model',{'id':1},{'id':'a'},prompt,4096)
  self.assertEqual(call.call_count,1)
  self.assertIsNone(row['response']);self.assertEqual(row['error'],'model_context_exhausted')
  self.assertEqual(row['prompt'],prompt);self.assertEqual(row['raw_error'],error.body)
 def test_unrelated_errors_propagate(self):
  for status,body in [(500,{}),(400,{'error':{'message':'invalid JSON'}})]:
   error=RuntimeError('other');error.status_code=status;error.body=body
   call=Mock(side_effect=error)
   with self.assertRaises(RuntimeError):generate(self.client(call),'m',{}, {},'prompt',4096)
   self.assertEqual(call.call_count,1)
 def test_empty_model_answer_remains_first_generation(self):
  response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=''),finish_reason='length')],model_dump=lambda **kw:{'id':'original'})
  call=Mock(return_value=response);row=generate(self.client(call),'m',{}, {},'prompt',4096)
  self.assertEqual(call.call_count,1);self.assertEqual(row['response'],'');self.assertIsNone(row['error']);self.assertEqual(row['raw'],{'id':'original'})
