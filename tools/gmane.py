"""Archive R mailing lists from Gmane's news server as pipermail-style mbox.

usage: gmane.py fetch LIST     read LIST's new articles into LIST/raw/
       gmane.py ids LIST       put back the Message-IDs Gmane rewrote
       gmane.py check LIST|all stop if a file to be published holds an address

Gmane (news.gmane.io, port 119) has carried mailing lists as newsgroups since
2002, and still does. Each article is the message as the list sent it, with
its real Message-ID, In-Reply-To and References, so threads come out whole.
Several R lists live on there after their own hosts and archives went away.

An article also carries every address it passed through: the sender's, the
list's, and those of the mail servers on the way. The mbox keeps only the
headers a pipermail text archive keeps (From, Date, Subject, Message-ID,
In-Reply-To, References) and writes the sender, and every address in a
subject or in the text, as pipermail's archives do, "user at domain". Its
text is the message's plain text in UTF-8; a text attachment follows it
after Mailman's "next part" line, and any other attachment is named there,
as Mailman's archive names one it took out.

Gmane took anything shaped like an address in In-Reply-To (and now and then
in References) for one and rewrote it, "<id-HASH@public.gmane.org>", which
leaves the reply pointing at no message. The ID is put back from the IDs
the list's messages carry unchanged (their own Message-ID, most References)
when exactly one of them is the rewritten ID's start.

LIST/config.json names the newsgroup ("gmane_group"); LIST/gmane.json
remembers the last article read, so a run asks only for newer ones and adds
them to the end of their month's file.
"""
import email
import email.policy
import glob
import html
import json
import os
import re
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.utils import getaddresses, parsedate_to_datetime

SERVER = ("news.gmane.io", 119)
PAUSE = 0.25  # seconds between articles: Gmane is run by volunteers
ADDRESS = re.compile(r"(?<![\w.+-])([\w.+-]+)(?:@|%40)([\w-]+(?:\.[\w-]+)+)")
# The check looks wider than the cut, so a shape the cut misses still stops
# a run.
WHOLE = re.compile(r"[\w.%+-]+(?:@|%40)[\w-]+(?:\.[\w-]+)+")
NEXT_PART = "-------------- next part --------------"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
# Headers and fields that hold Message-IDs: shaped like addresses, they name
# a message, not a person, and the threads are built from them.
ID_HEADERS = ("Message-ID", "In-Reply-To", "References")
ID_FIELDS = ("message_id", "in_reply_to", "references")


class News:
    """Just enough of NNTP (RFC 3977) to read a group's articles."""

    def __init__(self):
        self.sock = socket.create_connection(SERVER, timeout=120)
        self.file = self.sock.makefile("rb")
        greeting = self.line()
        if not greeting.startswith("20"):
            raise OSError(f"Gmane said: {greeting}")

    def line(self):
        raw = self.file.readline()
        if not raw:
            raise OSError("Gmane closed the connection")
        return raw.decode("latin-1").rstrip("\r\n")

    def command(self, text):
        self.sock.sendall(text.encode() + b"\r\n")
        return self.line()

    def group(self, name):
        """(first, last) article numbers of a group."""
        reply = self.command(f"GROUP {name}")
        if not reply.startswith("211"):
            raise OSError(f"GROUP {name}: {reply}")
        _, _, first, last, _ = reply.split(maxsplit=4)
        return int(first), int(last)

    def article(self, number):
        """The article's bytes, or None when the server has none by that
        number (numbers are skipped where articles were removed)."""
        reply = self.command(f"ARTICLE {number}")
        if reply.startswith("423") or reply.startswith("430"):
            return None
        if not reply.startswith("220"):
            raise OSError(f"ARTICLE {number}: {reply}")
        lines = []
        while True:
            raw = self.file.readline()
            if not raw:
                raise OSError("Gmane closed the connection")
            if raw in (b".\r\n", b".\n"):
                return b"".join(lines)
            if raw.startswith(b".."):
                raw = raw[1:]
            lines.append(raw[:-2] + b"\n" if raw.endswith(b"\r\n") else raw)

    def close(self):
        try:
            self.command("QUIT")
        except OSError:
            pass
        self.sock.close()


def obscure(text):
    return ADDRESS.sub(r"\1 at \2", text)


def encoded(value):
    """A header value, as RFC 2047 encoded words when it is not ASCII."""
    if value.isascii():
        return value
    return Header(value, "utf-8").encode(maxlinelen=998)


def header(msg, key):
    """A header's decoded text on one line, or "" when it is missing or
    cannot be read."""
    try:
        value = msg.get(key)
    except (ValueError, TypeError, IndexError):
        value = None
    if value is None:
        return ""
    return " ".join(str(value).split())


def html_to_text(markup):
    markup = re.sub(r"(?is)<(script|style).*?</\1>", "", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", markup)
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


def part_text(part):
    try:
        return part.get_content()
    except (LookupError, UnicodeError, AssertionError, KeyError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def body_of(msg):
    """The message's text, then its attachments in Mailman's form."""
    text, extras, html_body = None, [], None
    parts = [p for p in msg.walk() if not p.is_multipart()] or [msg]
    for part in parts:
        ctype = part.get_content_type()
        attached = part.get_content_disposition() == "attachment"
        if ctype == "text/plain" and not attached and text is None:
            text = part_text(part)
        elif ctype == "text/html":
            if html_body is None:
                html_body = part_text(part)
        elif ctype.startswith("text/"):
            extras.append(f"{NEXT_PART}\n{part_text(part).rstrip()}\n")
        else:
            size = len(part.get_payload(decode=True) or b"")
            extras.append(
                f"{NEXT_PART}\nA non-text attachment was scrubbed...\n"
                f"Name: {part.get_filename() or 'not available'}\n"
                f"Type: {ctype}\nSize: {size} bytes\n"
            )
    if text is None:
        text = html_to_text(html_body) if html_body is not None else ""
    body = "\n".join([text.rstrip() + "\n"] + extras)
    body = obscure(body.replace("\r\n", "\n").replace("\r", "\n"))
    return re.sub(r"(?m)^(>*From )", r">\1", body)


def sender(msg):
    pairs = getaddresses([header(msg, "From")])
    name, addr = pairs[0] if pairs else ("", "")
    local, _, domain = addr.partition("@")
    who = f"{local} at {domain}" if domain else (obscure(local) or "unknown")
    return who, obscure(name)


def sent(msg, now):
    """When the message was sent, in UTC. A Date that will not parse, or
    one before 1990 or in the future, gives way to the time Gmane posted
    it."""
    for key in ("Date", "NNTP-Posting-Date", "Injection-Date"):
        try:
            when = parsedate_to_datetime(header(msg, key))
        except (TypeError, ValueError, IndexError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(timezone.utc)
        if datetime(1990, 1, 1, tzinfo=timezone.utc) <= when <= now + timedelta(days=2):
            return when
    return None


def convert(msg, when):
    """The message as an mbox entry, pipermail's way."""
    who, name = sender(msg)
    stamp = when.strftime("%a %b ") + f"{when.day:2d}" + when.strftime(" %H:%M:%S %Y")
    lines = [f"From {who}  {stamp}", f"From: {who} ({encoded(name)})" if name else f"From: {who}"]
    date = header(msg, "Date")
    try:
        parsedate_to_datetime(date)
    except (TypeError, ValueError, IndexError):
        date = email.utils.format_datetime(when)
    lines.append(f"Date: {date}")
    lines.append(f"Subject: {encoded(obscure(header(msg, 'Subject')))}")
    for key in ("In-Reply-To", "References", "Message-ID"):
        value = header(msg, key)
        if value:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n\n" + body_of(msg) + "\n"


def month_file(lst, when):
    return os.path.join(lst, "raw", f"{when.year}-{MONTHS[when.month - 1]}.mbox")


def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_fetch(lst):
    config = load(os.path.join(lst, "config.json"), None)
    if config is None:
        sys.exit(f"No such list: {lst}")
    state_path = os.path.join(lst, "gmane.json")
    state = load(state_path, {"last_article": 0})
    os.makedirs(os.path.join(lst, "raw"), exist_ok=True)
    now = datetime.now(timezone.utc)
    news = News()
    added = skipped = borrowed = 0
    previous = None
    try:
        first, last = news.group(config["gmane_group"])
        start = max(first, state["last_article"] + 1)
        for number in range(start, last + 1):
            raw = news.article(number)
            time.sleep(PAUSE)
            if raw is None:
                skipped += 1
            else:
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                when = sent(msg, now)
                if when is None:
                    # Gmane numbers articles as they arrive, so the one
                    # before is the nearest date there is.
                    when = previous or now
                    borrowed += 1
                with open(month_file(lst, when), "a", encoding="utf-8") as f:
                    f.write(convert(msg, when))
                previous = when
                added += 1
            # Saved after every article, so a run cut short never writes
            # one twice.
            state["last_article"] = number
            save_state(state_path, state)
    finally:
        news.close()
    print(f"{lst}: {added} messages added, {skipped} article numbers empty"
          + (f", {borrowed} dated by the article before" if borrowed else ""), file=sys.stderr)


REWRITTEN = re.compile(r"<([^<>\s@]+)@public\.gmane\.org>")
ID = re.compile(r"<([^<>\s@]+)@([^<>\s]+)>")


def id_lines(text):
    """(start, end) of each Message-ID, In-Reply-To or References header in
    an mbox, continuation lines included."""
    spans, start, pos = [], None, 0
    for line in text.split("\n"):
        end = pos + len(line)
        if start is not None and line[:1] in (" ", "\t"):
            spans[-1] = (start, end)
        elif line.split(":", 1)[0] in ID_HEADERS and ":" in line:
            start = pos
            spans.append((start, end))
        else:
            start = None
        pos = end + 1
    return spans


def restore_ids(lst):
    """Put back, in LIST/raw/, the Message-IDs Gmane rewrote."""
    paths = sorted(glob.glob(os.path.join(lst, "raw", "*.mbox")))
    texts = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            texts[path] = f.read()
    known = {}
    for text in texts.values():
        for start, end in id_lines(text):
            for local, domain in ID.findall(text[start:end]):
                if domain != "public.gmane.org":
                    known.setdefault(local, set()).add(f"<{local}@{domain}>")

    def original(m):
        rewritten = m.group(1)
        found = []
        for i, c in enumerate(rewritten):
            if c == "-" and len(rewritten) - i > 16 and rewritten[:i] in known:
                found.append(rewritten[:i])
        if not found:
            return m.group(0)
        ids = known[max(found, key=len)]
        return next(iter(ids)) if len(ids) == 1 else m.group(0)

    restored = left = 0
    for path, text in texts.items():
        parts, last = [], 0
        for start, end in id_lines(text):
            block = text[start:end]
            new = REWRITTEN.sub(original, block)
            restored += len(REWRITTEN.findall(block)) - len(REWRITTEN.findall(new))
            left += len(REWRITTEN.findall(new))
            parts += [text[last:start], new]
            last = end
        new_text = "".join(parts) + text[last:]
        if new_text != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
    print(f"{lst}: {restored} rewritten Message-IDs put back, {left} left as Gmane wrote them",
          file=sys.stderr)


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)
        f.write("\n")


def addresses_in_mbox(text):
    """Whole addresses in an mbox, leaving out its Message-ID headers."""
    keep = []
    in_id = False
    for line in text.split("\n"):
        if line[:1] in (" ", "\t") and in_id:
            continue
        in_id = line.split(":", 1)[0] in ID_HEADERS and ":" in line
        if not in_id:
            keep.append(line)
    return len(WHOLE.findall("\n".join(keep)))


def json_strings(value, key=""):
    """(field, text) for every string in a decoded JSON value, keys
    included."""
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield "(key)", k
            yield from json_strings(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from json_strings(v, key)


def addresses_in_json(text):
    """Whole addresses in a JSON file's strings once decoded, by field,
    leaving out the fields that hold Message-IDs."""
    counts = {}
    for field, s in json_strings(json.loads(text)):
        if field in ID_FIELDS:
            continue
        n = len(WHOLE.findall(s))
        if n:
            counts[field or "(value)"] = counts.get(field or "(value)", 0) + n
    return counts


def cmd_check(which):
    """Stop if any file about to be published holds a whole address. It
    says where, never what: the run's log is public."""
    lists = [which] if which != "all" else sorted(
        os.path.dirname(c) for c in glob.glob("*/config.json"))
    paths = ["lists.tsv"] if which == "all" and os.path.exists("lists.tsv") else []
    for lst in lists:
        for top, _, files in os.walk(lst):
            paths += [os.path.join(top, f) for f in sorted(files) if not f.startswith(".")]
    found = 0
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        if path.endswith(".json"):
            counts = addresses_in_json(text)
            n = sum(counts.values())
            where = " (" + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + ")" if n else ""
        else:
            n, where = addresses_in_mbox(text), ""
        if n:
            print(f"{path}: {n} whole addresses{where}", file=sys.stderr)
            found += n
    if found:
        sys.exit(f"check: {found} whole addresses; nothing is published until they are cut")
    print(f"check: no whole address in {len(paths)} files", file=sys.stderr)


def main(argv):
    if len(argv) != 3 or argv[1] not in ("fetch", "ids", "check"):
        sys.exit(__doc__.split("\n\n")[1])
    name = argv[2].rstrip("/")
    if name != "all" and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        sys.exit(f"Not a list name: {name}")
    if argv[1] == "fetch":
        cmd_fetch(name)
    elif argv[1] == "ids":
        restore_ids(name)
    else:
        cmd_check(name)


if __name__ == "__main__":
    main(sys.argv)
