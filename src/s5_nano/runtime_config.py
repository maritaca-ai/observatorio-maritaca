"""An explicit per-model profile is the sole source of generation parameters."""
import json,os
from pathlib import Path

SAMPLING=('temperature','top_p','top_k','min_p','presence_penalty','repetition_penalty')
def read_profile(path):
 profile=json.loads(Path(path).read_text())
 if type(profile.get('enable_thinking')) is not bool:raise ValueError('Profile must specify enable_thinking')
 if set(profile.get('sampling',{}))!=set(SAMPLING):raise ValueError('Profile must specify all six sampling parameters')
 if 'max_tokens' not in profile or (profile['max_tokens'] is not None and (type(profile['max_tokens']) is not int or profile['max_tokens']<1)):raise ValueError('Profile needs an explicit positive output limit or null')
 if profile.get('reasoning_effort') is not None:raise ValueError('This protocol does not set reasoning_effort')
 if type(profile.get('context_length')) is not int or profile['context_length']<1:raise ValueError('Profile needs its model context length')
 if profile.get('mode_supported',True) is not True:raise ValueError('This reasoning mode is not supported by the model protocol')
 if profile.get('history_encoding','qwen_think_tags') not in ('qwen_think_tags','reasoning_field'):raise ValueError('Unknown reasoning history encoding')
 if 'generation_stop' in profile:
  stops=profile['generation_stop']
  if not isinstance(stops,list) or not stops or any(not isinstance(s,str) or not s for s in stops):raise ValueError('Invalid generation stop sequences')
 from .message_adaptation import message_policy
 message_policy(profile)
 if profile.get('tool_adapter') not in (None,'google-adk-gemma3-text-v1'):raise ValueError('Unknown tool adapter')
 return profile

PROFILE=read_profile(os.environ['S5_NANO_PROFILE']) if 'S5_NANO_PROFILE' in os.environ else None
POLICY=PROFILE['sampling'] if PROFILE else {}
THINKING=PROFILE['enable_thinking'] if PROFILE else None
MAX_TOKENS=PROFILE['max_tokens'] if PROFILE else None
WORKERS=int(os.environ.get('S5_NANO_WORKERS','4'))
if WORKERS<1:raise ValueError('workers must be positive')
