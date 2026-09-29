"""Evaluate production PromQL with promtool, without GCP credentials or writes."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "monitoring" / "templates"
DST = (TEMPLATES / "daylight-saving.promql").read_text()
WINDOW = (TEMPLATES / "operating-window.promql.tftpl").read_text().replace("${daylight_saving}", DST)
METRIC = 'monitoring_googleapis_com:uptime_check_check_passed{monitored_resource="uptime_url",project_id="itsx25-lab",host="team5.itsx25.chas-lab.dev",check_id="test-check"}'
QUERY = (TEMPLATES / "availability.promql.tftpl").read_text().replace("${metric}", METRIC).replace("${operating_window}", WINDOW)
STOCKHOLM = ZoneInfo("Europe/Stockholm")


def at(expression, date):
    """Use fixed wall time so promtool needn't simulate samples since 1970."""
    return expression.replace("time()", str(int(date.timestamp())))


class AlertTests(unittest.TestCase):
    def promtool(self, tests, rules=None):
        tool = os.environ.get("PROMTOOL") or shutil.which("promtool")
        self.assertIsNotNone(tool, "Set PROMTOOL to the extracted promtool binary.")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {"evaluation_interval": "1m", "tests": tests}
            if rules:
                (root / "rules.json").write_text(json.dumps({"groups": [{"name": "headscale", "rules": rules}]}))
                config["rule_files"] = [str(root / "rules.json")]
            target = root / "tests.json"
            target.write_text(json.dumps(config))
            result = subprocess.run([tool, "test", "rules", str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stockholm_calendar_against_zoneinfo(self):
        # Month boundaries, leap year, DST Sundays and both sides of 01:00 UTC.
        dates = set()
        for year in range(2026, 2031):
            for month in range(1, 13):
                for day in (1, 15, 28):
                    for hour in (0, 1, 7, 12, 23):
                        dates.add(datetime(year, month, day, hour, tzinfo=timezone.utc))
            for month in (3, 10):
                for day in range(25, 32):
                    for hour, minute in ((0, 59), (1, 0), (1, 1)):
                        dates.add(datetime(year, month, day, hour, minute, tzinfo=timezone.utc))
        cases = [{"expr": at(DST, date), "eval_time": "0m", "exp_samples": [
            {"labels": "{}", "value": int(date.astimezone(STOCKHOLM).dst().total_seconds() / 3600)}
        ]} for date in sorted(dates)]
        self.promtool([{"promql_expr_test": cases}])

    def test_operating_window_and_schedule_contract(self):
        # Keep the operating-window logic coupled to the actual VM schedule.
        source = (ROOT / "main.tf").read_text()
        self.assertRegex(source, r'time_zone\s*=\s*"Europe/Stockholm"')
        self.assertRegex(source, r'vm_start_schedule\s*\{\s*schedule\s*=\s*"0 8 \* \* \*"')
        self.assertRegex(source, r'vm_stop_schedule\s*\{\s*schedule\s*=\s*"0 0 \* \* \*"')
        cases = []
        for month in range(1, 13):
            for day in (1, 28):
                for hour, minute in ((0, 0), (7, 59), (8, 0), (8, 9), (8, 10), (12, 0), (23, 59)):
                    date = datetime(2026, month, day, hour, minute, tzinfo=STOCKHOLM)
                    expected = [{"labels": "{}", "value": hour * 60 + minute}] if hour * 60 + minute >= 490 else []
                    cases.append({"expr": at(WINDOW, date), "eval_time": "0m", "exp_samples": expected})
        self.promtool([{"promql_expr_test": cases}])

    def test_outage_debounce_missing_data_and_recovery(self):
        noon = datetime(2026, 9, 29, 12, tzinfo=STOCKHOLM)
        rules = [{"alert": "HeadscaleUnavailable", "expr": at(QUERY, noon), "for": "3m"}]
        def series(values):
            return [{"series": METRIC[:-1] + f',checker_location="location-{index}"' + '}', "values": value}
                    for index, value in enumerate(values)]
        def test(name, values, checkpoints):
            return {"name": name, "interval": "1m", "input_series": series(values), "alert_rule_test": [
                {"eval_time": time, "alertname": "HeadscaleUnavailable", "exp_alerts": [{}] if firing else []}
                for time, firing in checkpoints
            ]}
        tests = [
            test("healthy", ["1+0x10"] * 3, [("10m", False)]),
            test("single probe failure", ["0+0x10", "1+0x10", "1+0x10"], [("10m", False)]),
            test("persistent outage", ["0+0x10", "0+0x10", "1+0x10"], [("2m", False), ("3m", True)]),
            test("short outage", ["0 0 1+0x8"] * 3, [("2m", False), ("4m", False)]),
            test("recovery", ["0+0x4 1+0x5"] * 3, [("4m", True), ("5m", False)]),
            test("lost probe data", ["1 stale _ _ _ _ _ _ _ _ _"] * 3, [("4m", False), ("9m", True)]),
            test("no data since creation", [], [("2m", False), ("3m", True)]),
        ]
        self.promtool(tests, rules)

    def test_night_suppression_and_failed_morning_start(self):
        for hour, minute, expected in ((0, 0, False), (7, 59, False), (8, 9, False), (8, 10, True), (23, 59, True)):
            with self.subTest(hour=hour, minute=minute):
                date = datetime(2026, 12, 1, hour, minute, tzinfo=STOCKHOLM)
                # No VM or guest heartbeat is required: total lack of data must alert by day.
                self.promtool([{"promql_expr_test": [{"expr": at(QUERY, date), "eval_time": "10m", "exp_samples":
                    [{"labels": "{}", "value": 1}] if expected else []}]}])

    def test_boot_messages_exclude_normal_boot_and_sudo_commands(self):
        source = (ROOT / "monitoring" / "main.tf").read_text()
        pattern = re.search(r'jsonPayload.MESSAGE=~"([^"]+)"', source).group(1)
        for message in ("Reached target emergency.target - Emergency Mode.",
                        "Started emergency.service - Emergency Shell.",
                        "systemd-fsck@dev-disk.service: Failed with result 'exit-code'.",
                        "Failed to start systemd-fsck@dev-disk.service - File System Check."):
            self.assertIsNotNone(re.search(pattern, message), message)
        for message in ("Finished systemd-fsck@dev-disk.service - File System Check.",
                        "systemd-fsck@dev-disk.service: Deactivated successfully.",
                        "Removed slice system-systemd\\x2dfsck.slice - Slice /system/systemd-fsck.",
                        "viktor : COMMAND=/usr/bin/journalctl -u systemd-fsck*",
                        "Stopped target emergency.target - Emergency Mode."):
            self.assertIsNone(re.search(pattern, message), message)


if __name__ == "__main__":
    unittest.main()
