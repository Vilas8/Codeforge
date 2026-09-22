from __future__ import annotations

import re
from dataclasses import dataclass, asdict


@dataclass
class TestDiagnostic:
    severity: str
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None


class TestDiagnosticsParser:
    PATTERNS = (
        re.compile(r'(?P<file>[^\s:]+):(\s*)?(?P<line>\d+)(?::(?P<column>\d+))?\s*-?\s*(?P<message>.+)'),
        re.compile(r'(?P<file>[^\s:]+)\((?P<line>\d+),(?P<column>\d+)\)\s*:\s*(?P<message>.+)'),
    )

    @classmethod
    def parse(cls, output: str, status: str = "unknown"):
        diagnostics = []
        for raw in output.splitlines()[-500:]:
            line = raw.strip()
            if not line:
                continue
            severity = "error" if re.search(r'\b(error|failed|failure|traceback|exception)\b', line, re.I) else "warning" if re.search(r'\bwarn(ing)?\b', line, re.I) else "info"
            match = next((p.search(line) for p in cls.PATTERNS if p.search(line)), None)
            if match:
                diagnostics.append(TestDiagnostic(
                    severity=severity,
                    message=match.group("message").strip()[:1000],
                    file=match.groupdict().get("file"),
                    line=int(match.group("line")) if match.groupdict().get("line") else None,
                    column=int(match.group("column")) if match.groupdict().get("column") else None,
                ))
            elif severity in {"error", "warning"}:
                diagnostics.append(TestDiagnostic(severity=severity, message=line[:1000]))
        unique = {}
        for item in diagnostics:
            key = (item.severity, item.file, item.line, item.message)
            unique[key] = item
        return [asdict(item) for item in list(unique.values())[:100]]

    @classmethod
    def summarize(cls, output: str, status: str = "unknown"):
        diagnostics = cls.parse(output, status)
        errors = sum(1 for d in diagnostics if d["severity"] == "error")
        warnings = sum(1 for d in diagnostics if d["severity"] == "warning")
        return {"status": status, "errors": errors, "warnings": warnings, "diagnostics": diagnostics}
