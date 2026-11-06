"""Match original Prosa aggregation and make missing-verdict coverage explicit."""
import importlib.util
import json
import unittest
import tempfile
from unittest.mock import Mock
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('prosa_worker',ROOT/'src/s5_nano/engines/prosa/worker.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
# Use the vendored package directly, without fetching any benchmark data.
import sys
sys.path.insert(0,str(ROOT/'benchmarks/chat/prosa_pt/fork'))
from prosa import gen_score as g, show_score as scoring, conversation as conv

class ProsaTests(unittest.TestCase):
 def test_published_protocol_matches_the_executed_native_contract(self):
  published=json.loads((ROOT/'benchmarks/chat/prosa_pt/protocol.json').read_text())['protocol']
  executed=json.loads((ROOT/'benchmarks/catalog.json').read_text())['prosa_pt']['protocol']
  self.assertEqual(published,executed)
  self.assertEqual(published['aggregation_policy'],w.AGGREGATION)
 def test_filtered_micro_and_macro_have_distinct_weights(self):
  questions=[dict(conversation_hash='a',question_excluded=False,checklist_filtered_indices=[0]),dict(conversation_hash='b',question_excluded=False,checklist_filtered_indices=[0,1,2]),dict(conversation_hash='excluded',question_excluded=True,checklist_filtered_indices=[])]
  entries=[dict(conversation_hash='a',evaluations=['YES','NO']),dict(conversation_hash='b',evaluations=['NO','NO','NO'])]
  got=w.aggregate(questions,entries,scoring)
  self.assertEqual(got['score'],25);self.assertEqual(got['macro_score'],50);self.assertEqual(got['scored_rubrics'],4)
  entries[1]['evaluations'][0]=None
  got=w.aggregate(questions,entries,scoring)
  self.assertAlmostEqual(got['score'],100/3)
  self.assertEqual(got['missing_verdicts'],1)
  self.assertEqual(got['eligible_rubrics'],4)
  with self.assertRaises(AssertionError):w.aggregate(questions,entries[:1],scoring)
 def test_first_returned_verdict_is_not_retried_to_complete_rubrics(self):
  client=Mock()
  client.chat.completions.create.return_value.model_dump.return_value={'choices':[{'message':{'content':'<EVALUATION_1>YES</EVALUATION_1><EVALUATION_2>N/A</EVALUATION_2>'}}]}
  q=dict(conversation_hash='synthetic',checklist='1. A\n2. B',last_query='Pergunta')
  with tempfile.TemporaryDirectory() as d:
   got=w.judgment(q,{'content':'Resposta'},g,client,Path(d),dict(judge='test',judge_temperature=0,judge_max_tokens=4096))
   self.assertEqual(got['evaluations'],['YES',None])
   self.assertEqual(got['judge_attempt'],0)
   self.assertEqual(client.chat.completions.create.call_count,1)
 def test_all_invalid_conversation_remains_in_coverage(self):
  q=[dict(conversation_hash=h,question_excluded=False,checklist_filtered_indices=[0]) for h in ['a','b']]
  got=w.aggregate(q,[dict(conversation_hash='a',evaluations=['YES']),dict(conversation_hash='b',evaluations=[None])],scoring)
  self.assertEqual(got['score'],100)
  self.assertEqual(got['n'],2)
  self.assertEqual(got['valid_conversations'],1)
  self.assertEqual(got['rubric_coverage'],.5)
 def test_native_history_and_system_are_retained(self):
  q={'conversation_input':[dict(role='user',content='Primeira pergunta'),dict(role='assistant',content='Resposta do histórico'),dict(role='user',content='Pergunta final')]}
  result=w.messages(q,conv)
  self.assertEqual(result[0]['content'],conv.get_conv_template('zero_shot').system_message)
  self.assertEqual(result[1:],q['conversation_input'])
 def test_native_rubric_parser_keeps_missing_verdicts_visible(self):
  self.assertEqual(g.parse_evaluations('<EVALUATION_1>SIM</EVALUATION_1>',2),['YES',None])
  self.assertEqual(g.parse_checklist('1. Critério A\n continuação\n2. Critério B'),['Critério A continuação','Critério B'])

if __name__=='__main__':unittest.main()
