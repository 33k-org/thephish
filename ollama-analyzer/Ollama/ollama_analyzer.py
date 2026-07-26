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
                "You are a phishing and social-engineering triage assistant "
                "reviewing an email forwarded by an employee who found it "
                "suspicious. Classify it using these definitions:\n\n"
                '- "malicious": clear phishing/fraud/social-engineering intent '
                "- e.g. a lookalike/spoofed domain impersonating a real brand, "
                "a credential-harvesting or payment request, manufactured "
                "urgency or threats (account suspension, legal action, limited "
                "time) pressuring the recipient to click or act, a "
                "sender/reply-to mismatch designed to deceive, or a request "
                "for sensitive data or a wire transfer from an unverified "
                "party.\n"
                '- "suspicious": genuine ambiguity - some signals are present '
                "but not enough to be sure either way, and a human should "
                "double-check. This is for real uncertainty, not a default "
                "choice when the sender is merely unfamiliar or the email is "
                "bulk/commercial.\n"
                '- "safe": no phishing indicators. This includes ordinary '
                "bulk email - newsletters, marketing, product announcements, "
                "automated notifications - even with many tracking links, "
                "unsubscribe links, or external domains, AS LONG AS there is "
                "no credential harvesting, brand impersonation via a "
                "lookalike domain, manufactured urgency, or request for "
                "sensitive information/payment. Being unsolicited or "
                "commercial does not make an email malicious or suspicious - "
                "spam and phishing are different things.\n\n"
                "Before deciding, check: (1) Does a link's domain impersonate "
                "a real brand the email claims to be from (e.g. paypa1.com "
                "instead of paypal.com)? (2) Does it ask for credentials, "
                "payment, or sensitive data? (3) Does it use urgency or "
                "threats to pressure action? (4) Do the From/Reply-To/links "
                "mismatch in a way designed to deceive? If none of these "
                "apply, classify as safe even if the email is unsolicited "
                "bulk mail you don't recognize.\n\n"
                "Respond with ONLY a JSON object with keys \"verdict\" (one "
                'of "malicious", "suspicious", "safe"), "confidence" (integer '
                '0-100), and "reasons" (a list of short strings explaining '
                "the verdict, referencing the specific checklist items above "
                "where relevant).\n\n"
                f"Headers: {json.dumps(headers)}\n\n"
                f"Body:\n{body}"
            )

            try:
                # /api/chat (message-based), not /api/generate (raw prompt
                # completion) - confirmed by testing live that gpt-oss's
                # chat template doesn't apply correctly through /api/generate
                # (produces garbled, unparseable output), while /api/chat
                # handles it correctly for both gpt-oss and Qwen3.
                response = requests.post(
                    f"http://{self.ollama_host}:{self.ollama_port}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "format": "json",
                        # Reasoning models (Qwen3, gpt-oss) "think" by
                        # default - with think left on, the JSON answer lands
                        # in Ollama's "thinking" field instead of the actual
                        # message content (confirmed live against both).
                        # Disabling it also cuts latency substantially.
                        "think": False,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except requests.RequestException as e:
                self.error(f"Unable to reach Ollama at {self.ollama_host}:{self.ollama_port}: {e}")

            raw_response = response.json().get("message", {}).get("content", "")
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
