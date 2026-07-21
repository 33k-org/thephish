#!/usr/bin/env python3
import email
import json
import re
from email import policy

import requests
from cortexutils.analyzer import Analyzer


class OllamaAnalyzer(Analyzer):
    def __init__(self):
        Analyzer.__init__(self)
        self.ollama_host = self.get_param("config.ollama_host", None, "ollama_host is missing")
        self.ollama_port = self.get_param("config.ollama_port", 11434)
        self.model = self.get_param("config.model", None, "model is missing")
        # Requests timeout, not Cortex's own job timeout (which defaults to
        # 5000s in the docker job runner) - raise this for bigger/slower models.
        self.timeout = self.get_param("config.timeout", 300)

    @staticmethod
    def _extract_body(msg):
        # Prefer the plain-text part; fall back to a crude HTML-tag strip so
        # HTML-only emails (common in phishing) still produce something.
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and not part.is_attachment():
                    return part.get_content()
            for part in msg.walk():
                if part.get_content_type() == "text/html" and not part.is_attachment():
                    return re.sub("<[^<]+?>", " ", part.get_content())
            return ""
        if msg.get_content_type() == "text/html":
            return re.sub("<[^<]+?>", " ", msg.get_content())
        return msg.get_content()

    def run(self):
        try:
            filepath = self.get_param("file", None, "File is missing")
            with open(filepath, "rb") as f:
                msg = email.message_from_binary_file(f, policy=policy.default)

            headers = {
                "from": str(msg.get("From", "")),
                "to": str(msg.get("To", "")),
                "subject": str(msg.get("Subject", "")),
                "date": str(msg.get("Date", "")),
                "return_path": str(msg.get("Return-Path", "")),
                "reply_to": str(msg.get("Reply-To", "")),
            }
            # Keep the prompt bounded - full report/raw_response still
            # includes the model's complete reasoning either way.
            body = self._extract_body(msg)[:12000]

            prompt = (
                "You are a phishing and social-engineering triage assistant. "
                "Analyze the email below and respond with ONLY a JSON object "
                'with keys "verdict" (one of "malicious", "suspicious", '
                '"safe"), "confidence" (integer 0-100), and "reasons" (a list '
                "of short strings explaining the verdict).\n\n"
                f"Headers: {json.dumps(headers)}\n\n"
                f"Body:\n{body}"
            )

            try:
                response = requests.post(
                    f"http://{self.ollama_host}:{self.ollama_port}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        # Qwen3 (this pipeline's target model) "thinks" by
                        # default - with think left on, the JSON answer lands
                        # in Ollama's "thinking" field and "response" comes
                        # back empty (confirmed by testing live against a
                        # real Qwen3 instance). Disabling it also cuts
                        # latency roughly in half.
                        "think": False,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except requests.RequestException as e:
                self.error(f"Unable to reach Ollama at {self.ollama_host}:{self.ollama_port}: {e}")

            raw_response = response.json().get("response", "")
            try:
                verdict_json = json.loads(raw_response)
            except json.JSONDecodeError:
                verdict_json = {
                    "verdict": "info",
                    "confidence": 0,
                    "reasons": ["Model response was not valid JSON", raw_response[:500]],
                }

            self.report(
                {
                    "headers": headers,
                    "model": self.model,
                    "verdict": verdict_json.get("verdict", "info"),
                    "confidence": verdict_json.get("confidence"),
                    "reasons": verdict_json.get("reasons", []),
                    "raw_response": raw_response,
                }
            )
        except Exception as e:
            self.unexpectedError(e)

    def summary(self, raw):
        level = raw.get("verdict") if raw.get("verdict") in ("malicious", "suspicious", "safe") else "info"
        return {
            "taxonomies": [
                self.build_taxonomy(level, "Ollama", "Verdict", raw.get("verdict", "unknown"))
            ]
        }


if __name__ == "__main__":
    OllamaAnalyzer().run()
