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
                '- "suspicious": genuine ambiguity - a SPECIFIC checklist item '
                "below is partially triggered or conflicting and you cannot "
                "resolve it either way after actually working through the "
                "checklist. This is a rare, deliberate call for real "
                "uncertainty - never a default for something merely "
                "unfamiliar, unsolicited, bulk, or slightly odd. If every "
                "checklist item below comes back clean, do not choose "
                "suspicious just to be cautious.\n"
                '- "spam": unsolicited bulk/commercial email with no phishing '
                "indicators - newsletters, marketing, product announcements, "
                "cold outreach, promotional offers - even with many tracking "
                "links, unsubscribe links, or external domains, AS LONG AS "
                "the checklist below comes back clean. Spam is annoying, not "
                "dangerous - it is a safe, non-threat category, exactly like "
                '"safe", just unwanted. Being unsolicited or commercial does '
                "not make an email malicious or suspicious - spam and "
                "phishing are different things.\n"
                '- "safe": genuine, wanted correspondence with no phishing '
                "indicators and no spam/advertising characteristics - e.g. "
                "an expected reply, a real colleague/customer/vendor email, "
                "a service notification the recipient actually uses (e.g. an "
                "MFA code, a real login alert from a service they have an "
                "account with).\n\n"
                "Before deciding, work through this checklist. Answer each "
                "one specifically using what's actually in the headers/body "
                "below - do not guess or assume something is wrong without "
                "pointing to the actual text/URL/address that shows it:\n"
                "(1) Domain/URL legitimacy: for the sender's address and "
                "every link, does the domain EXACTLY match the real brand's "
                "domain (a subdomain of the correct base domain, e.g. "
                "mail2.realbrand.com, is fine) - or is it a lookalike "
                "(substituted characters, extra words, hyphens, a different "
                "TLD, e.g. paypa1.com or paypal-secure.net instead of "
                "paypal.com), or a URL shortener/redirect hiding the real "
                "destination?\n"
                "(2) Credential/payment/data requests: does it ask the "
                "recipient to enter a password, PIN, one-time code, card "
                "number, or send money/gift cards/crypto, or 'verify' "
                "account details via a link or reply?\n"
                "(3) Urgency/fear/pressure: does it threaten account "
                "suspension, legal action, a missed deadline, or use "
                "countdown/limited-time language to rush a decision before "
                "the recipient can think it through or verify it?\n"
                "(4) From/Reply-To/link mismatch: does the displayed sender "
                "name not match the actual address's domain? Does Reply-To "
                "point somewhere different from From? Does link display text "
                "claim one destination while the actual href is different?\n"
                "(5) Bypassing normal channels: does it ask the recipient to "
                "use a personal email/phone instead of official channels, "
                "keep the request confidential, or avoid verifying through "
                "IT/security/a manager before acting?\n"
                "(6) Attachment risk: does it include an executable, script, "
                "macro-enabled Office document, or password-protected "
                "archive?\n"
                "(7) Generic targeting inconsistent with the claimed "
                "relationship: does it address the recipient generically "
                "('Dear Customer', 'Dear User') while claiming to be from an "
                "entity that would normally know their name (their own bank, "
                "employer, or a service they have a real account with)?\n"
                "(8) Authority impersonation: does it impersonate an "
                "executive, manager, or vendor requesting an urgent, unusual, "
                "one-off action (wire transfer, gift cards, an off-process "
                "purchase) that skips normal approval steps?\n"
                "(9) Grammar/spelling is a WEAK signal only - noticeable "
                "errors can support a malicious read alongside other hits "
                "above, but never use grammar alone to call something "
                "malicious or suspicious, and never let clean grammar alone "
                "clear something that hit other checks - plenty of real "
                "phishing is well-written, and plenty of real legitimate "
                "mail has typos.\n\n"
                "If checks (1)-(8) are all clearly clean, it is not "
                "malicious or suspicious - decide between spam "
                "(unsolicited/bulk/commercial/mass-outreach) and safe "
                "(a genuine individual message or a real, expected account "
                "notification). Only use suspicious when a specific check "
                "above is genuinely ambiguous after you've actually checked "
                "it, not as a hedge for general unfamiliarity.\n\n"
                "Respond with ONLY a JSON object with keys \"verdict\" (one "
                'of "malicious", "suspicious", "spam", "safe"), "confidence" '
                '(integer 0-100), and "reasons" (a list of short strings '
                "explaining the verdict, citing the specific checklist "
                "item numbers that applied).\n\n"
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
        verdict = raw.get("verdict")
        # Cortex's taxonomy only has 4 fixed levels (info/safe/suspicious/
        # malicious) - "spam" isn't one of them, but it's not a security
        # threat either, so it maps to "safe" for coloring/aggregation
        # purposes. The literal "spam" value is still passed through below,
        # so it displays distinctly in Cortex/TheHive's UI and in the
        # verdict-email reply (see run_analysis.py's patched
        # terminate_analysis(), which reads the raw verdict separately from
        # this level for exactly this reason).
        if verdict in ("malicious", "suspicious", "safe"):
            level = verdict
        elif verdict == "spam":
            level = "safe"
        else:
            level = "info"
        return {
            "taxonomies": [
                self.build_taxonomy(level, "Ollama", "Verdict", raw.get("verdict", "unknown"))
            ]
        }


if __name__ == "__main__":
    OllamaAnalyzer().run()
