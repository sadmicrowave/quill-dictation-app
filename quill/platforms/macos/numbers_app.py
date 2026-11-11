"""Which Numbers Quill talks to.

A Mac can have more than one Numbers (the classic ``com.apple.iWork.Numbers`` and a newer one, ``com.apple.Numbers``), and asking for
"Numbers" by name reaches only one of them: the other one's documents are then invisible (nothing detected, the sheet never followed).
:data:`NUMBERS_APP_JS` is a piece of JavaScript for Automation every Numbers script starts with: ``numbersApp()`` answers the running
Numbers that has documents open (else any running one, else Numbers by name).
"""
from __future__ import annotations

NUMBERS_BUNDLE_IDS = ("com.apple.Numbers", "com.apple.iWork.Numbers")

NUMBERS_APP_JS = """
function numbersApp() {
  let running = null;
  for (const id of ["com.apple.Numbers", "com.apple.iWork.Numbers"]) {
    try {
      const candidate = Application(id);
      if (!candidate.running()) continue;
      if (candidate.documents().length > 0) return candidate;
      if (running === null) running = candidate;
    } catch (e) {}
  }
  return running !== null ? running : Application("Numbers");
}
"""

#: Answers the bundle identifier of the Numbers Quill talks to (empty when none is running).
NUMBERS_BUNDLE_JS = NUMBERS_APP_JS + """
function run() {
  try { const app = numbersApp(); return app.running() ? app.id() : ""; } catch (e) { return ""; }
}
"""
