"""Provider selection tests without external AI calls."""

import os
import unittest
from unittest.mock import Mock, patch

from shorts_generator.local.llm import make_llm


class LLMSelectionTests(unittest.TestCase):
    def test_missing_key_is_rejected(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "API key"):
                make_llm("openrouter", "some-model")

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported AI provider"):
            make_llm("untrusted", "model", "key")

    def test_openrouter_uses_compatible_endpoint_and_selected_key(self):
        completion = Mock()
        completion.choices = [Mock(message=Mock(content='{"highlights": []}'))]
        with patch("openai.OpenAI") as client:
            client.return_value.chat.completions.create.return_value = completion
            output = make_llm("openrouter", "test-model", "test-key")("prompt")
        self.assertEqual(output, '{"highlights": []}')
        self.assertEqual(client.call_args.kwargs["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(client.call_args.kwargs["api_key"], "test-key")
        self.assertEqual(client.return_value.chat.completions.create.call_args.kwargs["model"], "test-model")

    def test_custom_requires_base_url(self):
        with self.assertRaisesRegex(ValueError, "base URL"):
            make_llm("custom", "test-model")


if __name__ == "__main__":
    unittest.main()
