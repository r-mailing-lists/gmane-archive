"""Tests for gmane.py: run with python3 -I tools/gmane_test.py"""
import email
import email.policy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmane  # noqa: E402

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)

ARTICLE = b"""Path: news.gmane.io!.POSTED!not-for-mail
From: Ann Example <ann.example@uni.example.org>
Newsgroups: gmane.comp.lang.r.zelig
Subject: Re: setx() for ann.example@uni.example.org
Date: Tue, 20 Feb 2007 09:45:28 +0100
Message-ID: <45DAB3F8.1@uni.example.org>
In-Reply-To: <abc.123@mail.example.com>
References: <abc.122@mail.example.com>
 <abc.123@mail.example.com>
To: zelig@lists.example.edu
Original-Received: from mx.example.com ([10.0.0.1]) by host@relay.example.net
NNTP-Posting-Date: Tue, 20 Feb 2007 08:46:00 +0000
Xref: news.gmane.io gmane.comp.lang.r.zelig:1
Content-Type: text/plain; charset=utf-8

Bob <bob@example.com> wrote:
From the start, mail me at ann%40uni.example.org.
> z.out <- zelig(y ~ x, model = "ls")
"""


def parse(raw):
    return email.message_from_bytes(raw, policy=email.policy.default)


class Convert(unittest.TestCase):
    def setUp(self):
        msg = parse(ARTICLE)
        self.text = gmane.convert(msg, gmane.sent(msg, NOW))

    def test_sender_is_written_pipermails_way(self):
        self.assertTrue(self.text.startswith("From ann.example at uni.example.org  Tue Feb 20 08:45:28 2007\n"))
        self.assertIn("\nFrom: ann.example at uni.example.org (Ann Example)\n", self.text)

    def test_addresses_in_subject_and_text_are_written_with_at(self):
        self.assertIn("Subject: Re: setx() for ann.example at uni.example.org\n", self.text)
        self.assertIn("Bob <bob at example.com> wrote:", self.text)
        self.assertIn("ann at uni.example.org.", self.text)

    def test_message_ids_are_kept_and_threads_with_them(self):
        self.assertIn("Message-ID: <45DAB3F8.1@uni.example.org>\n", self.text)
        self.assertIn("In-Reply-To: <abc.123@mail.example.com>\n", self.text)
        self.assertIn("References: <abc.122@mail.example.com> <abc.123@mail.example.com>\n", self.text)

    def test_only_pipermails_headers_are_kept(self):
        headers = self.text.split("\n\n", 1)[0].split("\n")[1:]
        self.assertEqual([h.split(":")[0] for h in headers],
                         ["From", "Date", "Subject", "In-Reply-To", "References", "Message-ID"])

    def test_a_line_starting_with_from_is_escaped(self):
        self.assertIn("\n>From the start", self.text)

    def test_no_whole_address_is_left_outside_the_message_ids(self):
        self.assertEqual(gmane.addresses_in_mbox(self.text), 0)

    def test_text_attachment_follows_and_binary_is_named(self):
        raw = (b"From: a@b.example.org\nSubject: s\nDate: Tue, 20 Feb 2007 09:45:28 +0100\n"
               b"Message-ID: <m@b>\nMIME-Version: 1.0\n"
               b"Content-Type: multipart/mixed; boundary=XX\n\n"
               b"--XX\nContent-Type: text/plain\n\nthe text\n"
               b"--XX\nContent-Type: text/x-r; name=f.R\nContent-Disposition: attachment; filename=f.R\n\nx <- 1\n"
               b"--XX\nContent-Type: application/pdf; name=p.pdf\nContent-Disposition: attachment; filename=p.pdf\n"
               b"Content-Transfer-Encoding: base64\n\nJVBERi0=\n--XX--\n")
        msg = parse(raw)
        text = gmane.convert(msg, gmane.sent(msg, NOW))
        self.assertIn("the text\n", text)
        self.assertIn(gmane.NEXT_PART + "\nx <- 1\n", text)
        self.assertIn("Name: p.pdf\nType: application/pdf\nSize: 5 bytes", text)
        self.assertNotIn("JVBERi0", text)


class Dates(unittest.TestCase):
    def test_date_header_in_utc(self):
        self.assertEqual(gmane.sent(parse(ARTICLE), NOW), datetime(2007, 2, 20, 8, 45, 28, tzinfo=timezone.utc))

    def test_bad_or_future_date_gives_way_to_gmanes(self):
        for bad in (b"Date: someday\n", b"Date: Mon, 1 Jan 2099 00:00:00 +0000\n", b"Date: Thu, 1 Jan 1970 00:00:00 +0000\n"):
            msg = parse(bad + b"NNTP-Posting-Date: Tue, 20 Feb 2007 08:46:00 +0000\n\nx\n")
            self.assertEqual(gmane.sent(msg, NOW), datetime(2007, 2, 20, 8, 46, tzinfo=timezone.utc))

    def test_no_date_at_all(self):
        self.assertIsNone(gmane.sent(parse(b"Subject: x\n\nx\n"), NOW))

    def test_month_file_is_named_like_pipermails(self):
        when = datetime(2007, 2, 20, tzinfo=timezone.utc)
        self.assertEqual(gmane.month_file("zelig", when), os.path.join("zelig", "raw", "2007-February.mbox"))


class RestoreIds(unittest.TestCase):
    MBOX = ("From a at b.org  Tue Feb 20 08:45:28 2007\n"
            "Message-ID: <first.1-x@host.example.org>\n\nquestion\n\n"
            "From c at d.org  Tue Feb 20 09:45:28 2007\n"
            "In-Reply-To: <first.1-x-iVBQNJaOZh0U2dTyv8gORQ@public.gmane.org>\n"
            "References: <first.1-x@host.example.org>\n"
            "Message-ID: <second@d.org>\n\nanswer quoting <user-iVBQNJaOZh0U2dTyv8gORQ@public.gmane.org>\n\n"
            "From e at f.org  Tue Feb 20 10:45:28 2007\n"
            "In-Reply-To: <gone-AbCdEfGhIjKlMnOpQrStUv+wx/@public.gmane.org>\n"
            "References: <second@d.org>\n <first.1-x-AbCdEfGhIjKlMnOpQrStUv+wx/@public.gmane.org>\n"
            "Message-ID: <third@f.org>\n\nmore\n")

    def test_rewritten_ids_are_put_back_and_text_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "demo", "raw"))
            path = os.path.join(d, "demo", "raw", "2007-February.mbox")
            with open(path, "w") as f:
                f.write(self.MBOX)
            with redirect_stderr(io.StringIO()) as err:
                gmane.restore_ids(os.path.join(d, "demo"))
            with open(path) as f:
                text = f.read()
        self.assertIn("In-Reply-To: <first.1-x@host.example.org>\n", text)
        self.assertIn("References: <second@d.org>\n <first.1-x@host.example.org>\n", text)
        self.assertIn("In-Reply-To: <gone-AbCdEfGhIjKlMnOpQrStUv+wx/@public.gmane.org>\n", text)
        self.assertIn("quoting <user-iVBQNJaOZh0U2dTyv8gORQ@public.gmane.org>", text)
        self.assertIn("2 rewritten Message-IDs put back, 1 left", err.getvalue())


class Check(unittest.TestCase):
    def run_check(self, files):
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                os.makedirs("demo/raw")
                os.makedirs("demo/processed")
                with open("demo/config.json", "w") as f:
                    json.dump({"list": "demo"}, f)
                for path, text in files.items():
                    with open(path, "w") as f:
                        f.write(text)
                err = io.StringIO()
                with redirect_stderr(err):
                    try:
                        gmane.cmd_check("all")
                        code = 0
                    except SystemExit as e:
                        code = e.code
                return code, err.getvalue()
            finally:
                os.chdir(cwd)

    def test_message_ids_pass(self):
        code, _ = self.run_check({
            "demo/raw/2007-February.mbox": "From a at b.org  Tue Feb 20 08:45:28 2007\nMessage-ID: <x@y.org>\n"
                                           "References: <p@q.org>\n <r@s.org>\n\nhi\n",
            "demo/processed/2007-02.json": json.dumps([{"message_id": "x@y.org", "references": ["p@q.org"],
                                                        "body_plain": "a at b.org"}]),
        })
        self.assertEqual(code, 0)

    def test_an_address_stops_it_and_is_not_printed(self):
        code, err = self.run_check({
            "demo/raw/2007-February.mbox": "From a at b.org  Tue Feb 20 08:45:28 2007\n\nwrite to ann@uni.example.org\n",
            "demo/processed/2007-02.json": json.dumps([{"from_name": "ann%40uni.example.org"}]),
        })
        self.assertNotEqual(code, 0)
        self.assertIn("demo/raw/2007-February.mbox: 1 whole addresses", err)
        self.assertIn("demo/processed/2007-02.json: 1 whole addresses (from_name 1)", err)
        self.assertNotIn("uni.example.org", err)


if __name__ == "__main__":
    unittest.main()
