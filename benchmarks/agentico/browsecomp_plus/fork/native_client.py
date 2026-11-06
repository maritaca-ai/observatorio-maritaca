"""Selected native definitions from Maritaca BrowseComp-Plus 312ffa12."""
from __future__ import annotations
import json
import openai
from transformers import AutoTokenizer

class SearchToolHandler:

    def __init__(
        self,
        searcher,
        snippet_max_tokens: int | None = None,
        k: int = 5,
        include_get_document: bool = True,   # PADRÃO MARITACA (upstream: False)
    ):
        self.searcher = searcher
        self.snippet_max_tokens = snippet_max_tokens
        self.k = k
        self.include_get_document = include_get_document

        self.tokenizer = None
        if snippet_max_tokens and snippet_max_tokens > 0:
            self.tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-0.6B")

    def get_tool_definitions(self):
        """Return tool definitions in Chat Completions API format."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": self.searcher.search_description(self.k),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query string",
                            }
                        },
                        "required": ["query"],
                    },
                },
            }
        ]

        if self.include_get_document:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "get_document",
                        "description": self.searcher.get_document_description(),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "docid": {
                                    "type": "string",
                                    "description": "Document ID to retrieve",
                                }
                            },
                            "required": ["docid"],
                        },
                    },
                }
            )

        return tools

    def execute_tool(self, tool_name: str, arguments: dict):
        if tool_name == "search":
            return self._search(arguments["query"])
        elif tool_name == "get_document":
            return self._get_document(arguments["docid"])
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    def _search(self, query: str):
        candidates = self.searcher.search(query, self.k)

        if self.snippet_max_tokens and self.snippet_max_tokens > 0 and self.tokenizer:
            for cand in candidates:
                text = cand["text"]
                tokens = self.tokenizer.encode(text, add_special_tokens=False)
                if len(tokens) > self.snippet_max_tokens:
                    truncated_tokens = tokens[: self.snippet_max_tokens]
                    cand["snippet"] = self.tokenizer.decode(
                        truncated_tokens, skip_special_tokens=True
                    )
                else:
                    cand["snippet"] = text
        else:
            for cand in candidates:
                cand["snippet"] = cand["text"]

        results = []
        for cand in candidates:
            if cand.get("score") is None:
                results.append({"docid": cand["docid"], "snippet": cand["snippet"]})
            else:
                results.append(
                    {
                        "docid": cand["docid"],
                        "score": cand["score"],
                        "snippet": cand["snippet"],
                    }
                )

        return json.dumps(results, indent=2)

    def _get_document(self, docid: str):
        result = self.searcher.get_document(docid)
        if result is None:
            return json.dumps({"error": f"Document with docid '{docid}' not found"})
        return json.dumps(result, indent=2)

def run_conversation_with_tools(
    client: openai.OpenAI,
    model: str,
    messages: list,
    tools: list,
    tool_handler: SearchToolHandler,
    max_iterations: int = 100,   # PADRÃO MARITACA (upstream: 20) — ver docs/PADRAO_MARITACA.md
    temperature: float | None = None,
    reasoning_effort: str | None = None,
):
    """Run a conversation with tool calling using Chat Completions API."""

    tool_usage = {}
    tool_outputs = {}
    status = "completed"

    for iteration in range(max_iterations):
        kwargs = {
            "model": model,
            "messages": messages,
            "tools": tools,
        }

        if temperature is not None:
            kwargs["temperature"] = temperature

        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        response = client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        assistant_message = choice.message

        # Build assistant message dict for conversation history
        msg_dict = {"role": "assistant"}
        if assistant_message.content:
            msg_dict["content"] = assistant_message.content
        if assistant_message.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_message.tool_calls
            ]
        messages.append(msg_dict)

        # If no tool calls, conversation is done
        if not assistant_message.tool_calls:
            return messages, tool_usage, tool_outputs, status

        # Execute tool calls
        for tool_call in assistant_message.tool_calls:
            try:
                arguments = json.loads(tool_call.function.arguments)
                result = tool_handler.execute_tool(tool_call.function.name, arguments)
                tool_usage[tool_call.function.name] = (
                    tool_usage.get(tool_call.function.name, 0) + 1
                )

                tool_outputs[tool_call.id] = {
                    "output": result,
                    "status": "completed",
                }

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

            except Exception as e:
                error_msg = f"Error executing {tool_call.function.name}: {str(e)}"
                tool_outputs[tool_call.id] = {
                    "output": error_msg,
                    "status": "error",
                }
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": error_msg,
                    }
                )

    print(f"Warning: Conversation hit max iterations ({max_iterations})")
    return messages, tool_usage, tool_outputs, status
