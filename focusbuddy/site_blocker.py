"""
site_blocker.py — real website blocking through the system "hosts" file.

How it works: the hosts file maps domain names to IP addresses before any DNS lookup.
Adding the line "127.0.0.1 youtube.com" makes the browser try to load YouTube from your own
computer, which fails, so the site is blocked in every browser at once.

This is the same technique used by the open-source blockers listed in docs/DESIGN.md
(e.g. SelfControl for macOS, https://github.com/SelfControlApp/selfcontrol, and the
StevenBlack hosts project, https://github.com/StevenBlack/hosts). No code was copied from
them: the idea of wrapping our lines between two marker comments, so we can always remove
exactly what we added and nothing else, is a common convention implemented here from scratch.

Safety rules built into this class:
* We only ever touch lines between our own START/END markers.
* If the app crashed during a session, the markers are still there; the GUI calls
  unblock() on start-up to clean them away (crash recovery).
* Editing the hosts file needs administrator/root rights. Without them we report the
  problem instead of failing silently, and the rest of the app keeps working.
* Domains are validated in config.py so no user text can inject other hosts entries.

Note: browsers cache DNS for a minute or so, so a tab that is already open may keep working
briefly. New tabs/loads are blocked immediately.
"""

import os
import platform
import re
from pathlib import Path

START_MARK = "# >>> StudyFocusBuddy block START (added automatically, safe to delete)"
END_MARK = "# <<< StudyFocusBuddy block END"
# Matches our whole block including markers; DOTALL lets "." cross line breaks.
BLOCK_PATTERN = re.compile(re.escape(START_MARK) + r".*?" + re.escape(END_MARK) + r"\n?",
                           re.DOTALL)


def default_hosts_path() -> Path:
    """Location of the hosts file on the current operating system."""
    if platform.system() == "Windows":
        root = os.environ.get("SystemRoot", r"C:\Windows")
        return Path(root) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")                   # macOS and Linux


class HostsBlocker:
    """Adds and removes a block of '127.0.0.1 domain' lines in the hosts file.

    Args:
        hosts_path: which file to edit. Tests pass a temporary file instead of the real one.
    """

    def __init__(self, hosts_path: Path = None):
        self.hosts_path = Path(hosts_path) if hosts_path else default_hosts_path()

    def can_write(self) -> bool:
        """True if we have permission to edit the hosts file."""
        return self.hosts_path.exists() and os.access(self.hosts_path, os.W_OK)

    def is_blocking(self) -> bool:
        """True if our block is currently in the file (also used for crash recovery)."""
        try:
            return START_MARK in self.hosts_path.read_text(encoding="utf-8")
        except OSError:
            return False

    def block(self, domains) -> tuple:
        """Block the given domains. Returns (success, message for the user)."""
        domains = [d for d in domains if d]
        if not domains:
            return False, "No websites in the block list."
        if not self.can_write():
            return False, ("Website blocking needs administrator rights. Re-run the app as "
                           "admin (see README) or turn website blocking off in Settings.")
        lines = [START_MARK]
        for domain in domains:
            for host in (domain, "www." + domain):       # block both forms of the address
                lines.append(f"127.0.0.1 {host}")
                lines.append(f"::1 {host}")              # IPv6, otherwise some browsers bypass it
        lines.append(END_MARK)
        try:
            text = self._strip_block(self.hosts_path.read_text(encoding="utf-8"))
            if text and not text.endswith("\n"):
                text += "\n"
            self.hosts_path.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")
        except OSError as err:
            return False, f"Could not edit the hosts file: {err}"
        return True, f"Blocking {len(domains)} website(s) until this session ends."

    def unblock(self) -> tuple:
        """Remove our block (and only our block). Returns (success, message)."""
        try:
            text = self.hosts_path.read_text(encoding="utf-8")
        except OSError as err:
            return False, f"Could not read the hosts file: {err}"
        if START_MARK not in text:
            return True, "Nothing to unblock."
        try:
            self.hosts_path.write_text(self._strip_block(text), encoding="utf-8")
        except OSError as err:
            return False, f"Could not restore the hosts file: {err}"
        return True, "Websites unblocked."

    @staticmethod
    def _strip_block(text: str) -> str:
        """Return text with our marked block removed."""
        return BLOCK_PATTERN.sub("", text)
