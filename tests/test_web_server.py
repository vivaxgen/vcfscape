"""
Unit tests for the local web server launcher.
"""

import os
import unittest
import sys

# Ensure src is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from vcfscape.web_server import (
    find_web_directory,
    is_port_in_use,
    SpaStaticHTTPHandler,
)


class TestWebServer(unittest.TestCase):
    def test_find_web_directory(self):
        web_dir = find_web_directory()
        self.assertTrue(len(web_dir) > 0, "Web directory should be located")
        self.assertTrue(os.path.isdir(web_dir), f"{web_dir} should be a directory")
        index_file = os.path.join(web_dir, "index.html")
        self.assertTrue(os.path.isfile(index_file), "index.html should exist in web directory")

    def test_port_check(self):
        # Port 65530 is likely unused
        in_use = is_port_in_use(65530)
        self.assertIsInstance(in_use, bool)

    def test_mime_types(self):
        exts = SpaStaticHTTPHandler.extensions_map
        self.assertEqual(exts.get(".js"), "application/javascript")
        self.assertEqual(exts.get(".mjs"), "application/javascript")
        self.assertEqual(exts.get(".css"), "text/css")
        self.assertEqual(exts.get(".json"), "application/json")
        self.assertEqual(exts.get(".vcf"), "text/plain; charset=utf-8")

    def test_load_vcf_payload(self):
        from vcfscape.web_server import load_vcf_payload
        example_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "examples", "pf3d7_surveillance_demo.vcf")
        )
        self.assertTrue(os.path.exists(example_path))
        payload = load_vcf_payload(example_path)
        self.assertEqual(payload["filename"], "pf3d7_surveillance_demo.vcf")
        self.assertGreater(payload["totalVariants"], 0)
        self.assertGreater(payload["totalSamples"], 0)
        self.assertIn("samples", payload)
        self.assertIn("cohorts", payload)
        self.assertIn("variants", payload)
        # Check first variant structure
        v0 = payload["variants"][0]
        self.assertIn("chrom", v0)
        self.assertIn("pos", v0)
        self.assertIn("samples", v0)

    def test_network_detection(self):
        from vcfscape.web_server import get_local_ip, get_fqdn
        ip = get_local_ip()
        self.assertIsInstance(ip, str)
        self.assertTrue(len(ip) > 0)

        fqdn = get_fqdn()
        self.assertIsInstance(fqdn, str)
        self.assertTrue(len(fqdn) > 0)

    def test_token_authentication(self):
        class DummyServer:
            auth_token = "secure_token_abc"
            vcf_payload = None

        handler = SpaStaticHTTPHandler.__new__(SpaStaticHTTPHandler)
        handler.server = DummyServer()

        # 1. Unauthenticated request
        handler.path = "/"
        handler.headers = {}
        is_authed, token_in_query = handler._is_authenticated()
        self.assertFalse(is_authed)
        self.assertFalse(token_in_query)

        # 2. Authenticated via query parameter
        handler.path = "/?token=secure_token_abc"
        handler.headers = {}
        is_authed, token_in_query = handler._is_authenticated()
        self.assertTrue(is_authed)
        self.assertTrue(token_in_query)

        # 3. Authenticated via cookie
        handler.path = "/api/vcf-data"
        handler.headers = {"Cookie": "malaria_vcf_token=secure_token_abc"}
        is_authed, token_in_query = handler._is_authenticated()
        self.assertTrue(is_authed)
        self.assertFalse(token_in_query)

        # 4. Authenticated via Bearer header
        handler.path = "/index.html"
        handler.headers = {"Authorization": "Bearer secure_token_abc"}
        is_authed, token_in_query = handler._is_authenticated()
        self.assertTrue(is_authed)
        self.assertFalse(token_in_query)

        # 5. Invalid token rejected
        handler.path = "/?token=wrong_token"
        handler.headers = {}
        is_authed, token_in_query = handler._is_authenticated()
        self.assertFalse(is_authed)

        # 6. Disabled token mode (auth_token = None)
        handler.server.auth_token = None
        handler.path = "/"
        handler.headers = {}
        is_authed, _ = handler._is_authenticated()
        self.assertTrue(is_authed)


if __name__ == "__main__":
    unittest.main()
